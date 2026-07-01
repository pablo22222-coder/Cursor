"""
Provider 2 — Cerebras AI
Modelo por defecto: llama3.1-8b (rapidísimo, ideal para validación
binaria SI/NO; vivo a jul-2026).

Configurable por env var CEREBRAS_MODEL. Grande disponible:
llama-3.3-70b. Se acepta también override por llamada vía `model`.
"""
import os
from typing import Optional

import requests

from src.services.providers.base_provider import BaseProvider, AIResponse, ProviderError

_ENV_KEY = "CEREBRAS_API_KEY"


class CerebrasProvider(BaseProvider):
    name     = "Cerebras"
    model    = os.getenv("CEREBRAS_MODEL", "llama3.1-8b")
    priority = 1

    _API_URL = "https://api.cerebras.ai/v1/chat/completions"

    def __init__(self):
        key = os.getenv(_ENV_KEY, "")
        status = "✓ OK" if len(key) > 10 else "✗ MISSING"
        print(f"[AIManager] Cargando proveedor Cerebras...        {status}")

    @property
    def _api_key(self) -> str:
        return os.getenv(_ENV_KEY, "")

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

        effective_model = model or self.model
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        def _call() -> str:
            resp = requests.post(
                self._API_URL,
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
                timeout=25,
            )
            if resp.status_code in self.RETRYABLE_STATUS_CODES:
                raise ProviderError(self.name, resp.status_code, resp.text[:200])
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

        return self._timed_complete(_call, model=effective_model)
