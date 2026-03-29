"""
Provider 3 — SambaNova Cloud (Terciario)
Modelo: Meta-Llama-3.2-3B-Instruct
Prioridad: Alta cuota gratuita
"""
import os
import requests

from src.services.providers.base_provider import BaseProvider, AIResponse, ProviderError


class SambanovaProvider(BaseProvider):
    name     = "SambaNova"
    model    = "Meta-Llama-3.2-3B-Instruct"
    priority = 2

    _API_URL = "https://api.sambanova.ai/v1/chat/completions"

    def __init__(self):
        self._api_key = os.getenv("SAMBANOVA_API_KEY", "")

    def is_available(self) -> bool:
        return bool(self._api_key and len(self._api_key) > 10)

    def complete(self, prompt: str, system_prompt: str = "") -> AIResponse:
        if not self.is_available():
            raise ValueError("SAMBANOVA_API_KEY no configurada")

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
                    "stream": False,
                },
                timeout=30,
            )
            if resp.status_code in self.RETRYABLE_STATUS_CODES:
                raise ProviderError(self.name, resp.status_code, resp.text[:200])
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

        return self._timed_complete(_call)
