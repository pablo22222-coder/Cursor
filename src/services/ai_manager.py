"""
AIManager — Orquestador de Fallback entre Proveedores de LLM

Gestiona las peticiones de IA siguiendo un orden de prioridad estricto.
Si un provider falla con un error recuperable (429, 5xx, timeout), el
sistema salta automáticamente al siguiente en menos de 1 segundo.

Orden de prioridad:
  0 → Groq          (llama-3.2-3b-preview)   — Velocidad
  1 → Cerebras      (llama3.1-8b)             — Fiabilidad
  2 → SambaNova     (Meta-Llama-3.2-3B)       — Alta cuota gratuita
  3 → Gemini        (gemini-1.5-flash)         — Emergencia / 15 RPM
  4 → WebLLM Local  (Llama-3.2-3B GGUF)       — Offline / sin API

Reglas de reintento:
- Errores 429 / 5xx → salto inmediato (<1s) al siguiente provider
- Timeout de red    → salto inmediato al siguiente provider
- Error de auth     → proveedor marcado como no disponible para esta sesión
- Si todos fallan   → devuelve AIResponse(success=False) con el texto de error
                       para que el sistema use _local_parse() como último recurso

System Prompt por defecto:
  Obliga a todos los modelos a devolver ÚNICAMENTE un objeto JSON válido,
  sin texto adicional ni bloques markdown. Esto garantiza que el resto
  del código siempre reciba JSON parseable independientemente del modelo.
"""
from __future__ import annotations

import threading
import time
from typing import List, Optional, Dict

from src.services.providers.base_provider import BaseProvider, AIResponse, ProviderError
from src.services.providers.groq_provider      import GroqProvider
from src.services.providers.cerebras_provider  import CerebrasProvider
from src.services.providers.sambanova_provider import SambanovaProvider
from src.services.providers.gemini_provider    import GeminiProvider
from src.services.providers.webllm_provider    import WebLLMProvider


# System prompt inyectado en TODAS las peticiones para garantizar JSON limpio
DEFAULT_SYSTEM_PROMPT = (
    "Eres un asistente especializado en análisis semántico de búsquedas web. "
    "Responde SIEMPRE y ÚNICAMENTE con un objeto JSON válido. "
    "No incluyas texto explicativo, no uses bloques de código markdown (```), "
    "no añadas prefijos ni sufijos. "
    "Solo el objeto JSON, empezando con { y terminando con }."
)


class AIManager:
    """
    Gestor de proveedores de LLM con fallback automático.

    Uso básico:
        manager = AIManager()
        response = manager.complete("Analiza este prompt: ...")
        if response.success:
            data = json.loads(response.text)

    Uso con system prompt personalizado:
        response = manager.complete(prompt, system_prompt="Instrucciones...")

    Uso como singleton (recomendado en producción):
        manager = get_ai_manager()
    """

    def __init__(self, extra_system_prompt: str = ""):
        self._providers: List[BaseProvider] = [
            GroqProvider(),
            CerebrasProvider(),
            SambanovaProvider(),
            GeminiProvider(),
            WebLLMProvider(),
        ]
        # Providers deshabilitados temporalmente por error de auth en esta sesión
        self._disabled: set = set()
        self._lock = threading.Lock()
        self._history: List[Dict] = []      # últimas N llamadas para debug
        self._extra_system = extra_system_prompt

    # ── Interfaz pública ─────────────────────────────────────────────────────

    def complete(self, prompt: str, system_prompt: str = "") -> AIResponse:
        """
        Envía `prompt` a los providers en orden de prioridad.
        Salta automáticamente al siguiente si el actual falla con error
        recuperable. Nunca lanza excepción al llamador.

        Args:
            prompt:        Contenido principal a procesar.
            system_prompt: Instrucciones de sistema adicionales.
                           Se fusionan con DEFAULT_SYSTEM_PROMPT.

        Returns:
            AIResponse. Si success=False, .error contiene el detalle.
        """
        full_system = DEFAULT_SYSTEM_PROMPT
        if self._extra_system:
            full_system += "\n\n" + self._extra_system
        if system_prompt:
            full_system += "\n\n" + system_prompt

        errors = []

        for provider in self._providers:
            # Saltar providers sin API key configurada
            if not provider.is_available():
                continue

            # Saltar providers deshabilitados por error de auth
            with self._lock:
                if provider.name in self._disabled:
                    continue

            try:
                response = provider.complete(prompt, full_system)
                response.is_fallback = (provider.priority > 0)
                self._log(provider.name, response.latency_ms, "ok")
                if response.is_fallback:
                    print(
                        f"[AIManager] Usando {provider.name} (fallback #{provider.priority}) "
                        f"— {response.latency_ms:.0f}ms"
                    )
                else:
                    print(f"[AIManager] {provider.name} — {response.latency_ms:.0f}ms")
                return response

            except ProviderError as e:
                # Error recuperable (429, 5xx) → saltar inmediatamente
                self._log(provider.name, 0, f"skip HTTP {e.status_code}")
                print(
                    f"[AIManager] {provider.name} → HTTP {e.status_code}, "
                    f"saltando al siguiente provider..."
                )
                errors.append(str(e))
                continue

            except (ConnectionError, TimeoutError, OSError) as e:
                # Error de red → saltar
                self._log(provider.name, 0, f"network: {type(e).__name__}")
                print(f"[AIManager] {provider.name} → Error de red, saltando...")
                errors.append(str(e))
                continue

            except (ValueError, PermissionError, KeyError) as e:
                # Error de autenticación / configuración → deshabilitar para esta sesión
                with self._lock:
                    self._disabled.add(provider.name)
                self._log(provider.name, 0, f"auth_error: {e}")
                print(f"[AIManager] {provider.name} → Error de auth, deshabilitando...")
                errors.append(str(e))
                continue

            except Exception as e:
                # Error desconocido → registrar y saltar
                self._log(provider.name, 0, f"unknown: {e}")
                print(f"[AIManager] {provider.name} → Error inesperado: {e}")
                errors.append(str(e))
                continue

        # Todos fallaron
        error_summary = " | ".join(errors[-3:]) if errors else "Todos los providers fallaron"
        print(f"[AIManager] ❌ Todos los providers fallaron: {error_summary}")
        return AIResponse(
            text="",
            provider="none",
            model="none",
            success=False,
            error=error_summary,
        )

    def available_providers(self) -> List[str]:
        """Lista de providers disponibles (con API key configurada)."""
        return [
            p.name for p in self._providers
            if p.is_available() and p.name not in self._disabled
        ]

    def status(self) -> Dict:
        """Estado del manager para monitorización / debug."""
        return {
            "providers": [
                {
                    "name":      p.name,
                    "model":     p.model,
                    "priority":  p.priority,
                    "available": p.is_available(),
                    "disabled":  p.name in self._disabled,
                }
                for p in self._providers
            ],
            "history": self._history[-5:],
        }

    # ── Helpers internos ─────────────────────────────────────────────────────

    def _log(self, provider: str, latency_ms: float, outcome: str):
        ts = time.strftime("%H:%M:%S")
        with self._lock:
            self._history.append({
                "ts": ts, "provider": provider,
                "latency_ms": round(latency_ms, 1), "outcome": outcome,
            })
            if len(self._history) > 50:
                self._history.pop(0)


# ── Singleton global ─────────────────────────────────────────────────────────
_manager: Optional[AIManager] = None
_manager_lock = threading.Lock()


def get_ai_manager() -> AIManager:
    """Devuelve el singleton de AIManager (crea uno si no existe)."""
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = AIManager()
        return _manager
