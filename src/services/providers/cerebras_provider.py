"""
Provider 2 — Cerebras AI (Secundario)
Modelo: llama3.1-8b
Prioridad: Fiabilidad (infraestructura independiente de otros proveedores)
"""
import os
import requests

from src.services.providers.base_provider import BaseProvider, AIResponse, ProviderError


class CerebrasProvider(BaseProvider):
    name     = "Cerebras"
    model    = "llama3.1-8b"
    priority = 1

    _API_URL = "https://api.cerebras.ai/v1/chat/completions"

    def __init__(self):
        self._api_key = os.getenv("CEREBRAS_API_KEY", "")

    def is_available(self) -> bool:
        return bool(self._api_key and len(self._api_key) > 10)

    def complete(self, prompt: str, system_prompt: str = "") -> AIResponse:
        if not self.is_available():
            raise ValueError("CEREBRAS_API_KEY no configurada")

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
                    "model": self.model,
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

        return self._timed_complete(_call)
