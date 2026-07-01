"""
Provider 4 — Google Gemini
Modelo por defecto: gemini-2.5-flash (vivo a jul-2026, usado como
fallback estable en todas las cadenas).

NOTA: gemini-1.5-flash fue APAGADO por Google (las peticiones devuelven
404). El default se lee de la env var GEMINI_MODEL (ver task_chains.py);
alternativa cuando el 2.5 caduque (16-oct-2026): gemini-3.x-flash.

Se acepta override por llamada vía el parámetro `model`.
"""
import os
from typing import Optional

import requests

from src.services.providers.base_provider import BaseProvider, AIResponse, ProviderError

_ENV_KEY = "GEMINI_API_KEY"


class GeminiProvider(BaseProvider):
    name     = "Gemini"
    # `or` en vez de segundo arg de getenv: si la env var está definida
    # pero vacía, el default SÍ debe aplicarse (ver groq_provider.py).
    # Si no, el modelo queda "" y la URL final es ".../models/:generateContent"
    # (sin nombre de modelo) → Google devuelve 404.
    model    = os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"
    priority = 3

    _API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self):
        key = os.getenv(_ENV_KEY, "")
        status = "✓ OK" if len(key) > 10 else "✗ MISSING"
        print(f"[AIManager] Cargando proveedor Gemini...          {status}")

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

        # Gemini REST API: system_prompt va como systemInstruction
        body: dict = {
            "contents": [{"parts": [{"text": prompt}], "role": "user"}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048},
        }
        if system_prompt:
            body["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        def _call() -> str:
            url = f"{self._API_BASE}/{effective_model}:generateContent?key={self._api_key}"
            resp = requests.post(url, json=body, timeout=30)
            if resp.status_code in self.RETRYABLE_STATUS_CODES:
                raise ProviderError(self.name, resp.status_code, resp.text[:200])
            resp.raise_for_status()
            candidates = resp.json().get("candidates", [])
            if not candidates:
                raise ValueError("Gemini devolvió respuesta vacía")
            return candidates[0]["content"]["parts"][0]["text"]

        return self._timed_complete(_call, model=effective_model)
