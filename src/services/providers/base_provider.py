"""
BaseProvider — Interfaz común para todos los proveedores de LLM.

Todos los providers deben heredar de esta clase e implementar `complete()`.
La salida siempre es un AIResponse con el mismo formato, independientemente
del proveedor que haya respondido.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AIResponse:
    """Respuesta normalizada que devuelven todos los providers."""
    text: str                          # Texto completo de la respuesta
    provider: str                      # Nombre del provider que respondió
    model: str                         # Modelo específico utilizado
    latency_ms: float = 0.0            # Tiempo de respuesta en milisegundos
    success: bool = True
    error: Optional[str] = None        # Mensaje de error si success=False
    is_fallback: bool = False          # True si no es el provider primario


class BaseProvider(ABC):
    """
    Clase base abstracta para proveedores de LLM.

    Cada provider concreto debe:
    1. Implementar complete(prompt, system_prompt) → AIResponse
    2. Leer su API key desde variables de entorno (nunca hardcodeada)
    3. Propagar correctamente errores 429 y 5xx para que AIManager
       sepa cuándo saltar al siguiente provider
    """

    # Nombre legible del provider (sobreescribir en cada subclase)
    name: str = "unknown"
    # Modelo por defecto
    model: str = "unknown"
    # Prioridad en la cadena (0 = primario, 4 = último recurso)
    priority: int = 99

    # Códigos HTTP que disparan salto al siguiente provider
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    @abstractmethod
    def complete(
        self,
        prompt: str,
        system_prompt: str = "",
        *,
        model: Optional[str] = None,
    ) -> AIResponse:
        """
        Envía `prompt` al LLM y devuelve la respuesta normalizada.

        Args:
            prompt:        Mensaje del usuario / contenido principal.
            system_prompt: Instrucciones de sistema (si el provider lo soporta).
            model:         Modelo concreto a usar para ESTA llamada. Si es
                           None se usa el atributo ``self.model``.
                           Permite que el mismo provider sirva varios
                           modelos a través de distintas cadenas de tareas
                           (p.ej. Groq con 8B para validación y 70B para
                           análisis sin instanciar dos veces el provider).

        Returns:
            AIResponse con el texto generado.

        Raises:
            ProviderError: Para errores recuperables (429, 5xx).
            Exception:     Para errores no recuperables (auth, config).
        """

    @abstractmethod
    def is_available(self) -> bool:
        """True si el provider está configurado (API key presente)."""

    def _timed_complete(self, call, *, model: Optional[str] = None) -> AIResponse:
        """
        Wrapper que mide la latencia de una llamada y devuelve AIResponse.
        `call` es un callable () → str (texto bruto). `model` es el modelo
        efectivo usado en esta llamada (puede diferir de ``self.model``
        cuando se le pasa un override al provider).
        """
        t0 = time.monotonic()
        text = call()
        latency = (time.monotonic() - t0) * 1000
        return AIResponse(
            text=text,
            provider=self.name,
            model=model or self.model,
            latency_ms=round(latency, 1),
            success=True,
        )


class ProviderError(Exception):
    """
    Error recuperable de un provider.
    AIManager capturará este error y saltará al siguiente provider.
    """
    def __init__(self, provider: str, status_code: int, message: str):
        self.provider = provider
        self.status_code = status_code
        super().__init__(f"[{provider}] HTTP {status_code}: {message}")
