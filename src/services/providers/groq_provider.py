"""
Provider 1 — Groq Cloud
Modelo por defecto: llama-3.1-70b-versatile (alta calidad)

El parámetro `model` de complete() permite usar otros modelos del
catálogo de Groq según la tarea (p.ej. llama-3.1-8b-instant para
validaciones rápidas).
"""
import os
from typing import Optional

import requests

from src.services.providers.base_provider import BaseProvider, AIResponse, ProviderError

_ENV_KEY = "GROQ_API_KEY"


class GroqProvider(BaseProvider):
    name     = "Groq"
    # Modelo por defecto cuando no se pasa override (alta calidad).
    model    = "llama-3.1-70b-versatile"
    priority = 0

    _API_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self):
        key = os.getenv(_ENV_KEY, "")
        status = "✓ OK" if len(key) > 10 else "✗ MISSING"
        print(f"[AIManager] Cargando proveedor Groq...           {status}")

    @property
    def _api_key(self) -> str:
        """Lectura lazy — siempre lee el valor actual del entorno."""
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
                timeout=20,
            )
            if resp.status_code in self.RETRYABLE_STATUS_CODES:
                raise ProviderError(self.name, resp.status_code, resp.text[:200])
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

        return self._timed_complete(_call, model=effective_model)
