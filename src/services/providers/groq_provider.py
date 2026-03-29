"""
Provider 1 — Groq Cloud (Primario)
Modelo: llama-3.2-3b-preview
Prioridad: Velocidad (inferencia más rápida disponible)
"""
import os
import requests

from src.services.providers.base_provider import BaseProvider, AIResponse, ProviderError

_ENV_KEY = "GROQ_API_KEY"


class GroqProvider(BaseProvider):
    name     = "Groq"
    model    = "llama-3.2-3b-preview"
    priority = 0

    _API_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self):
        # Leer en tiempo de init para el log de arranque, pero siempre releer en is_available/complete
        key = os.getenv(_ENV_KEY, "")
        status = "✓ OK" if len(key) > 10 else "✗ MISSING"
        print(f"[AIManager] Cargando proveedor Groq...           {status}")

    @property
    def _api_key(self) -> str:
        """Lectura lazy — siempre lee el valor actual del entorno."""
        return os.getenv(_ENV_KEY, "")

    def is_available(self) -> bool:
        return len(self._api_key) > 10

    def complete(self, prompt: str, system_prompt: str = "") -> AIResponse:
        if not self.is_available():
            raise ValueError(f"{_ENV_KEY} no configurada")

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
                timeout=20,
            )
            if resp.status_code in self.RETRYABLE_STATUS_CODES:
                raise ProviderError(self.name, resp.status_code, resp.text[:200])
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

        return self._timed_complete(_call)
