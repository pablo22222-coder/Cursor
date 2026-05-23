"""
AIManager — Orquestador de Fallback entre Proveedores de LLM

Gestiona las peticiones de IA siguiendo una cadena ordenada de
proveedores. Si un eslabón falla con un error recuperable (429, 5xx,
timeout), el sistema salta automáticamente al siguiente en menos de un
segundo.

CADENAS DE FALLBACK POR TAREA
-----------------------------
Existen tres cadenas distintas según el tipo de tarea (ver
`src/services/task_chains.py`):

  1. **Análisis de prompt** (`TASK_PROMPT_ANALYSIS`):
       Groq 70B → SambaNova 405B → Gemini Flash → User Own

  2. **Generación de queries** (`TASK_QUERY_GENERATION`):
       SambaNova 405B → Groq 70B → Gemini Flash → User Own

  3. **Validación final** (`TASK_VALIDATION`):
       Cerebras 8B → Groq 70B → Groq 8B → Gemini Flash → User Own

Para usar la cadena correcta llama a ``get_ai_manager_for_task(task)``
o al helper ``complete_for_task(task, prompt, system_prompt)``.

CADENA LEGACY
-------------
Si alguien crea ``AIManager()`` sin pasar `chain`, se usa la cadena
combinada (todos los providers, en orden histórico). Es solo para
compatibilidad con código antiguo — los nuevos call-sites deben usar
``get_ai_manager_for_task(...)``.

Reglas de reintento:
- Errores 429 / 5xx → salto inmediato (<1s) al siguiente eslabón
- Timeout de red    → salto inmediato al siguiente eslabón
- Error de auth     → eslabón deshabilitado para esta sesión
- Si todos fallan   → devuelve AIResponse(success=False) con el texto de
                       error para que el caller use el fallback local

System Prompt por defecto:
  Obliga a todos los modelos a devolver ÚNICAMENTE un objeto JSON válido,
  sin texto adicional ni bloques markdown. Esto garantiza que el resto
  del código siempre reciba JSON parseable independientemente del modelo.
  Si la tarea NO espera JSON (p.ej. el juez SI/NO), pasa
  ``json_mode=False`` para desactivarlo por llamada.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from src.services.providers.base_provider import BaseProvider, AIResponse, ProviderError
from src.services.providers.groq_provider      import GroqProvider
from src.services.providers.cerebras_provider  import CerebrasProvider
from src.services.providers.sambanova_provider import SambanovaProvider
from src.services.providers.gemini_provider    import GeminiProvider
from src.services.providers.webllm_provider    import WebLLMProvider
from src.services.providers.user_own_provider  import UserOwnProvider


# System prompt inyectado en TODAS las peticiones que esperan JSON.
DEFAULT_SYSTEM_PROMPT = (
    "Eres un asistente especializado en análisis semántico de búsquedas web. "
    "Responde SIEMPRE y ÚNICAMENTE con un objeto JSON válido. "
    "No incluyas texto explicativo, no uses bloques de código markdown (```), "
    "no añadas prefijos ni sufijos. "
    "Solo el objeto JSON, empezando con { y terminando con }."
)


# ─────────────────────────────────────────────────────────────────────
#  Bloque por eslabón (provider concreto + modelo concreto)
# ─────────────────────────────────────────────────────────────────────

@dataclass
class _ChainEntry:
    """Un eslabón ya instanciado: un provider con su modelo override."""
    provider: BaseProvider
    model: Optional[str] = None

    @property
    def label(self) -> str:
        if self.model and self.model != self.provider.model:
            return f"{self.provider.name}[{self.model}]"
        return self.provider.name


def _build_legacy_chain() -> List[_ChainEntry]:
    """
    Cadena combinada por compatibilidad. Usa los providers con sus
    modelos por defecto, en el orden histórico.
    """
    return [
        _ChainEntry(GroqProvider()),
        _ChainEntry(CerebrasProvider()),
        _ChainEntry(SambanovaProvider()),
        _ChainEntry(GeminiProvider()),
        _ChainEntry(WebLLMProvider()),
        _ChainEntry(UserOwnProvider()),
    ]


class AIManager:
    """
    Gestor de proveedores de LLM con fallback automático.

    Uso básico (cadena legacy):
        manager = AIManager()
        response = manager.complete("Analiza este prompt: ...")
        if response.success:
            data = json.loads(response.text)

    Uso por tarea (recomendado):
        from src.services.ai_manager import complete_for_task
        from src.services.task_chains import TASK_VALIDATION
        response = complete_for_task(TASK_VALIDATION, prompt, system_prompt)
    """

    def __init__(
        self,
        extra_system_prompt: str = "",
        chain: Optional[List[_ChainEntry]] = None,
        task_name: str = "legacy",
    ):
        self._chain: List[_ChainEntry] = chain if chain is not None else _build_legacy_chain()
        self._task_name = task_name
        # Providers deshabilitados temporalmente por error de auth en esta sesión.
        # Indexamos por label (nombre+modelo) en lugar de por nombre, para que
        # deshabilitar Groq[8B] no afecte a Groq[70B].
        self._disabled: set = set()
        self._lock = threading.Lock()
        self._history: List[Dict] = []      # últimas N llamadas para debug
        self._extra_system = extra_system_prompt

    # ── Interfaz pública ─────────────────────────────────────────────────────

    def complete(
        self,
        prompt: str,
        system_prompt: str = "",
        *,
        json_mode: bool = True,
    ) -> AIResponse:
        """
        Envía `prompt` a los proveedores en orden de la cadena de esta
        instancia y devuelve la primera respuesta exitosa. Salta
        automáticamente al siguiente si el actual falla con error
        recuperable. Nunca lanza excepción al llamador.

        Args:
            prompt:        Contenido principal a procesar.
            system_prompt: Instrucciones de sistema adicionales.
                           Se fusionan con DEFAULT_SYSTEM_PROMPT cuando
                           ``json_mode=True``.
            json_mode:     Si True (default), se inyecta el prompt que
                           obliga a devolver JSON. Pásalo a False cuando
                           la tarea espera texto plano (p.ej. veredicto
                           SI/NO del juez).

        Returns:
            AIResponse. Si success=False, .error contiene el detalle.
        """
        full_system = ""
        if json_mode:
            full_system = DEFAULT_SYSTEM_PROMPT
        if self._extra_system:
            full_system = (full_system + "\n\n" + self._extra_system) if full_system else self._extra_system
        if system_prompt:
            full_system = (full_system + "\n\n" + system_prompt) if full_system else system_prompt

        errors: List[str] = []

        for idx, entry in enumerate(self._chain):
            provider = entry.provider
            label = entry.label

            # Saltar providers sin API key / no operativos.
            if not provider.is_available():
                continue

            # Saltar providers deshabilitados por error de auth.
            with self._lock:
                if label in self._disabled:
                    continue

            try:
                response = provider.complete(prompt, full_system, model=entry.model)
                response.is_fallback = (idx > 0)
                self._log(label, response.latency_ms, "ok")
                if response.is_fallback:
                    print(
                        f"[AIManager:{self._task_name}] Usando {label} "
                        f"(fallback #{idx}) — {response.latency_ms:.0f}ms"
                    )
                else:
                    print(
                        f"[AIManager:{self._task_name}] {label} "
                        f"— {response.latency_ms:.0f}ms"
                    )
                return response

            except ProviderError as e:
                # Error recuperable (429, 5xx) → saltar inmediatamente
                self._log(label, 0, f"skip HTTP {e.status_code}")
                print(
                    f"[AIManager:{self._task_name}] {label} → HTTP "
                    f"{e.status_code}, saltando al siguiente..."
                )
                errors.append(str(e))
                continue

            except (ConnectionError, TimeoutError, OSError) as e:
                self._log(label, 0, f"network: {type(e).__name__}")
                print(f"[AIManager:{self._task_name}] {label} → Error de red, saltando...")
                errors.append(str(e))
                continue

            except (ValueError, PermissionError, KeyError) as e:
                with self._lock:
                    self._disabled.add(label)
                self._log(label, 0, f"auth_error: {e}")
                print(f"[AIManager:{self._task_name}] {label} → Error de auth, deshabilitando...")
                errors.append(str(e))
                continue

            except Exception as e:
                self._log(label, 0, f"unknown: {e}")
                print(f"[AIManager:{self._task_name}] {label} → Error inesperado: {e}")
                errors.append(str(e))
                continue

        # Todos fallaron
        error_summary = " | ".join(errors[-3:]) if errors else "Todos los providers fallaron"
        print(f"[AIManager:{self._task_name}] ❌ Toda la cadena falló: {error_summary}")
        return AIResponse(
            text="",
            provider="none",
            model="none",
            success=False,
            error=error_summary,
        )

    def available_providers(self) -> List[str]:
        """Eslabones de la cadena que están disponibles ahora."""
        return [
            e.label for e in self._chain
            if e.provider.is_available() and e.label not in self._disabled
        ]

    def status(self) -> Dict:
        """Estado del manager para monitorización / debug."""
        return {
            "task":  self._task_name,
            "chain": [
                {
                    "label":     e.label,
                    "provider":  e.provider.name,
                    "model":     e.model or e.provider.model,
                    "available": e.provider.is_available(),
                    "disabled":  e.label in self._disabled,
                }
                for e in self._chain
            ],
            "history": self._history[-5:],
        }

    # ── Helpers internos ─────────────────────────────────────────────────────

    def _log(self, label: str, latency_ms: float, outcome: str):
        ts = time.strftime("%H:%M:%S")
        with self._lock:
            self._history.append({
                "ts": ts, "label": label,
                "latency_ms": round(latency_ms, 1), "outcome": outcome,
            })
            if len(self._history) > 50:
                self._history.pop(0)


# ─────────────────────────────────────────────────────────────────────
#  Singletons globales (legacy + por tarea)
# ─────────────────────────────────────────────────────────────────────

_legacy_manager: Optional[AIManager] = None
_task_managers: Dict[str, AIManager] = {}
_manager_lock = threading.Lock()


def get_ai_manager() -> AIManager:
    """
    Singleton legacy. Devuelve un manager con la cadena combinada
    (todos los providers, orden histórico). Se mantiene por
    compatibilidad — el resto del código debería usar
    ``get_ai_manager_for_task(...)``.
    """
    global _legacy_manager
    with _manager_lock:
        if _legacy_manager is None:
            _legacy_manager = AIManager(task_name="legacy")
        return _legacy_manager


def get_ai_manager_for_task(task_name: str) -> AIManager:
    """
    Devuelve un singleton de AIManager configurado con la cadena de
    fallback correspondiente al nombre de tarea (ver
    ``src/services/task_chains.py``).
    """
    from src.services.task_chains import get_chain  # lazy: evita ciclos

    with _manager_lock:
        cached = _task_managers.get(task_name)
        if cached is not None:
            return cached

        chain_def = get_chain(task_name)
        entries: List[_ChainEntry] = []
        for step in chain_def:
            try:
                provider = step.instantiate()
            except Exception as exc:  # pragma: no cover — defensivo
                print(f"[AIManager] No se pudo instanciar {step.provider_class.__name__}: {exc}")
                continue
            entries.append(_ChainEntry(provider=provider, model=step.model))

        manager = AIManager(chain=entries, task_name=task_name)
        _task_managers[task_name] = manager
        return manager


def complete_for_task(
    task_name: str,
    prompt: str,
    system_prompt: str = "",
    *,
    json_mode: bool = True,
) -> AIResponse:
    """
    Atajo: usa la cadena de la tarea y devuelve la AIResponse.

    Args:
        task_name:     Uno de ``TASK_PROMPT_ANALYSIS``,
                       ``TASK_QUERY_GENERATION`` o ``TASK_VALIDATION``
                       (ver ``src/services/task_chains.py``).
        prompt:        Mensaje principal.
        system_prompt: Instrucciones extra.
        json_mode:     Desactiva el system prompt de "responde solo JSON"
                       cuando la tarea espera texto plano.
    """
    return get_ai_manager_for_task(task_name).complete(
        prompt, system_prompt, json_mode=json_mode,
    )
