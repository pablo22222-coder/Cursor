"""
Provider 5 — Clave propia del usuario (fallback final)

Esta entrada de la cadena de fallback usa una clave de API que el propio
usuario configura en su `.env`. Sirve para que el sistema siga
funcionando aunque todos los providers gratuitos se hayan agotado o
estén bloqueando peticiones.

Compatibilidad
--------------
El provider usa el contrato OpenAI Chat Completions, así que funciona
con cualquier servicio compatible:
  · OpenAI         (https://api.openai.com/v1)
  · OpenRouter     (https://openrouter.ai/api/v1)
  · Mistral        (https://api.mistral.ai/v1)
  · Together.ai    (https://api.together.xyz/v1)
  · Anyscale       (https://api.endpoints.anyscale.com/v1)
  · Fireworks      (https://api.fireworks.ai/inference/v1)
  · DeepSeek       (https://api.deepseek.com/v1)
  · Cualquier proxy que exponga `POST /chat/completions` OpenAI-style.

Variables de entorno
--------------------
  USER_OWN_API_KEY        Obligatoria. La clave del usuario.
  USER_OWN_BASE_URL       URL base SIN /chat/completions. Default:
                          "https://api.openai.com/v1".
  USER_OWN_MODEL          Nombre del modelo. Default: "gpt-4o-mini".
  USER_OWN_PROVIDER_NAME  Nombre legible para logs. Default: "UserOwn".

Si la clave no está configurada, ``is_available()`` devuelve False y el
sistema simplemente salta este eslabón de la cadena.
"""
from __future__ import annotations

import os
from typing import Optional

import requests

from src.services.providers.base_provider import BaseProvider, AIResponse, ProviderError


_ENV_KEY      = "USER_OWN_API_KEY"
_ENV_BASE_URL = "USER_OWN_BASE_URL"
_ENV_MODEL    = "USER_OWN_MODEL"
_ENV_NAME     = "USER_OWN_PROVIDER_NAME"

_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_DEFAULT_MODEL    = "gpt-4o-mini"
_DEFAULT_NAME     = "UserOwn"


class UserOwnProvider(BaseProvider):
    """
    Provider con configuración 100% controlada por el usuario.

    Se inicializa una sola vez; las variables se releen en cada
    petición para permitir cambiar la configuración en caliente sin
    reiniciar el servidor.
    """
    # `name` y `model` se asignan dinámicamente en __init__ para que el
    # log de arranque muestre lo que el usuario haya configurado, pero
    # las propiedades los releen para soportar hot-reload.
    name     = _DEFAULT_NAME
    model    = _DEFAULT_MODEL
    # Se considera el último eslabón antes de fallar.
    priority = 9

    def __init__(self):
        # Reflejar la configuración inicial en los atributos de clase
        # (sin sobrescribir si el usuario no ha definido nada).
        configured_name = os.getenv(_ENV_NAME, "").strip() or _DEFAULT_NAME
        configured_model = os.getenv(_ENV_MODEL, "").strip() or _DEFAULT_MODEL
        # Asignación a instancia: deja la clase intacta para evitar
        # efectos secundarios entre instancias en tests.
        self.name = configured_name
        self.model = configured_model
        key = os.getenv(_ENV_KEY, "")
        status = "✓ OK" if len(key) > 10 else "✗ MISSING (opcional)"
        print(f"[AIManager] Cargando proveedor {configured_name}...  {status}")

    # ── Lectura lazy de la configuración ─────────────────────────────

    @property
    def _api_key(self) -> str:
        return os.getenv(_ENV_KEY, "")

    @property
    def _base_url(self) -> str:
        url = (os.getenv(_ENV_BASE_URL, "") or "").strip().rstrip("/")
        return url or _DEFAULT_BASE_URL

    @property
    def _model(self) -> str:
        return (os.getenv(_ENV_MODEL, "").strip() or _DEFAULT_MODEL)

    @property
    def _display_name(self) -> str:
        return (os.getenv(_ENV_NAME, "").strip() or _DEFAULT_NAME)

    # ── Interfaz BaseProvider ────────────────────────────────────────

    def is_available(self) -> bool:
        return len(self._api_key) > 10

    def complete(
        self,
        prompt: str,
        system_prompt: str = "",
        *,
        model: Optional[str] = None,
    ) -> AIResponse:
        if not self.is_available():
            raise ValueError(f"{_ENV_KEY} no configurada")

        # En cada llamada actualizamos el nombre del provider y del
        # modelo "por defecto" según la env actual. Esto permite que
        # los logs reflejen los valores reales sin reiniciar.
        self.name = self._display_name
        self.model = self._model

        effective_model = model or self._model
        url = f"{self._base_url}/chat/completions"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        def _call() -> str:
            resp = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": effective_model,
                    "messages": messages,
                    "temperature": 0.1,
                    "max_tokens": 2048,
                },
                timeout=30,
            )
            if resp.status_code in self.RETRYABLE_STATUS_CODES:
                raise ProviderError(self.name, resp.status_code, resp.text[:200])
            resp.raise_for_status()
            data = resp.json()
            try:
                return data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise ValueError(
                    f"Respuesta inesperada del endpoint {self._base_url}: {exc}"
                )

        return self._timed_complete(_call, model=effective_model)
