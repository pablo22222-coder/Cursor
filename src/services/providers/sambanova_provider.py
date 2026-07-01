"""
Provider 3 — SambaNova Cloud
Modelo por defecto: Meta-Llama-3.3-70B-Instruct (vivo a jul-2026).

NOTA: Meta-Llama-3.1-405B-Instruct fue RETIRADO del cloud de SambaNova
en jun-2025 (solo queda On-Request/SambaStack). El default se lee de la
env var SAMBANOVA_MODEL (ver task_chains.py); alternativa si caduca:
DeepSeek-V3.1 o gpt-oss-120b.

Se acepta override por llamada vía el parámetro `model`.
"""
import os
from typing import Optional

import requests

from src.services.providers.base_provider import BaseProvider, AIResponse, ProviderError

_ENV_KEY = "SAMBANOVA_API_KEY"


class SambanovaProvider(BaseProvider):
    name     = "SambaNova"
    # `or` en vez de segundo arg de getenv: si la env var está definida
    # pero vacía, el default SÍ debe aplicarse (ver groq_provider.py).
    model    = os.getenv("SAMBANOVA_MODEL") or "Meta-Llama-3.3-70B-Instruct"
    priority = 2

    _API_URL = "https://api.sambanova.ai/v1/chat/completions"

    def __init__(self):
        key = os.getenv(_ENV_KEY, "")
        status = "✓ OK" if len(key) > 10 else "✗ MISSING"
        print(f"[AIManager] Cargando proveedor SambaNova...       {status}")

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
                    "stream": False,
                },
                timeout=30,
            )
            if resp.status_code in self.RETRYABLE_STATUS_CODES:
                raise ProviderError(self.name, resp.status_code, resp.text[:200])
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

        return self._timed_complete(_call, model=effective_model)
