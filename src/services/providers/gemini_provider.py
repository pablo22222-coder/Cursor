"""
Provider 4 — Google Gemini (Emergencia)
Modelo: gemini-1.5-flash
Prioridad: Estabilidad casi infinita (15 RPM free tier)
"""
import os
import requests

from src.services.providers.base_provider import BaseProvider, AIResponse, ProviderError

_ENV_KEY = "GEMINI_API_KEY"


class GeminiProvider(BaseProvider):
    name     = "Gemini"
    model    = "gemini-1.5-flash"
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

    def complete(self, prompt: str, system_prompt: str = "") -> AIResponse:
        if not self.is_available():
            raise ValueError(f"{_ENV_KEY} no configurada")

        # Gemini REST API: system_prompt va como systemInstruction
        body: dict = {
            "contents": [{"parts": [{"text": prompt}], "role": "user"}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048},
        }
        if system_prompt:
            body["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        def _call() -> str:
            url = f"{self._API_BASE}/{self.model}:generateContent?key={self._api_key}"
            resp = requests.post(url, json=body, timeout=30)
            if resp.status_code in self.RETRYABLE_STATUS_CODES:
                raise ProviderError(self.name, resp.status_code, resp.text[:200])
            resp.raise_for_status()
            candidates = resp.json().get("candidates", [])
            if not candidates:
                raise ValueError("Gemini devolvió respuesta vacía")
            return candidates[0]["content"]["parts"][0]["text"]

        return self._timed_complete(_call)
