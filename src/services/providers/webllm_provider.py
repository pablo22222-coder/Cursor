"""
Provider 5 — WebLLM / Local LLM (Último Recurso)
Modelo: Llama-3.2-3B-Instruct (WASM/CPU, sin GPU requerida)
Prioridad: Funcionamiento offline/local sin ninguna API key

Gestión de memoria (8 GB de RAM total):
- Los 3 workers del scraper consumen ~1.5-2 GB
- Playwright (3 browsers) consume ~0.8 GB
- Llama-3.2-3B en GGUF Q4_K_M ≈ 2 GB de RAM
- Total estimado: ~5 GB → seguro en 8 GB

Se usa llama-cpp-python con el modelo en formato GGUF descargado
automáticamente en el primer uso. Configuración optimizada para CPU
(no requiere WebGPU ni GPU dedicada).

Si llama-cpp-python no está instalado, el provider falla con is_available()=False
y AIManager registra el error sin lanzar excepción.
"""
import os
import json
import re
from typing import Optional

from src.services.providers.base_provider import BaseProvider, AIResponse, ProviderError

# Nombre del modelo GGUF — Q4_K_M equilibra calidad y RAM
_MODEL_REPO  = "bartowski/Llama-3.2-3B-Instruct-GGUF"
_MODEL_FILE  = "Llama-3.2-3B-Instruct-Q4_K_M.gguf"
# Ruta local de caché
_MODEL_CACHE = os.path.join(os.path.expanduser("~"), ".cache", "domain_finder_llm", _MODEL_FILE)

_llama_instance: Optional[object] = None


def _get_llama():
    """Carga el modelo en memoria (singleton, lazy)."""
    global _llama_instance
    if _llama_instance is not None:
        return _llama_instance

    try:
        from llama_cpp import Llama
    except ImportError:
        raise ImportError(
            "llama-cpp-python no instalado. "
            "Instalar con: pip install llama-cpp-python"
        )

    if not os.path.exists(_MODEL_CACHE):
        _download_model()

    _llama_instance = Llama(
        model_path=_MODEL_CACHE,
        n_ctx=2048,          # Contexto reducido para ahorrar RAM
        n_threads=4,         # Usar 4 hilos CPU
        n_gpu_layers=0,      # Forzar CPU — no saturar si no hay GPU
        verbose=False,
    )
    return _llama_instance


def _download_model():
    """Descarga el modelo GGUF desde Hugging Face Hub."""
    os.makedirs(os.path.dirname(_MODEL_CACHE), exist_ok=True)
    print(f"[WebLLM] Descargando modelo {_MODEL_FILE} (~2GB, solo la primera vez)...")
    try:
        from huggingface_hub import hf_hub_download
        path = hf_hub_download(
            repo_id=_MODEL_REPO,
            filename=_MODEL_FILE,
            local_dir=os.path.dirname(_MODEL_CACHE),
        )
        if path != _MODEL_CACHE:
            import shutil
            shutil.copy(path, _MODEL_CACHE)
    except Exception as e:
        raise RuntimeError(f"No se pudo descargar el modelo: {e}")


class WebLLMProvider(BaseProvider):
    name     = "WebLLM-Local"
    model    = "Llama-3.2-3B-Instruct-Q4_K_M"
    priority = 4

    def is_available(self) -> bool:
        """True si llama-cpp-python está instalado."""
        try:
            import llama_cpp  # noqa: F401
            return True
        except ImportError:
            return False

    def complete(self, prompt: str, system_prompt: str = "") -> AIResponse:
        if not self.is_available():
            raise ImportError(
                "llama-cpp-python no instalado. "
                "Instalar con: pip install llama-cpp-python"
            )

        def _call() -> str:
            llama = _get_llama()
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            output = llama.create_chat_completion(
                messages=messages,
                temperature=0.1,
                max_tokens=1024,   # Reducido para ahorrar tiempo/RAM en local
            )
            return output["choices"][0]["message"]["content"]

        return self._timed_complete(_call)
