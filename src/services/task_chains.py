"""
TaskChains — cadenas de fallback de LLM por tipo de tarea.

El sistema usa proveedores distintos según la tarea, en lugar de una
cadena global única. La motivación es que no todas las tareas necesitan
los mismos modelos: la generación de queries se beneficia mucho de los
modelos más grandes (405B), la validación final necesita un razonamiento
rápido y consistente, y el análisis de prompts es un equilibrio.

Las tres tareas son:

  - TASK_PROMPT_ANALYSIS  → analizar el prompt del usuario, extraer
    parámetros, decidir si activar Wappalyzer/ADN/PageSpeed, y demás
    decisiones de routing previas a la búsqueda.

  - TASK_QUERY_GENERATION → generar las queries de Google que mandamos
    a Serper. Aquí la creatividad y la cobertura amplia importan
    mucho — favorecemos los modelos más grandes.

  - TASK_VALIDATION       → veredicto SI/NO sobre cada web ya extraída,
    cruzando el prompt con el HTML + Wappalyzer/ADN + PageSpeed.
    Necesita rapidez y consistencia.

Cada cadena se define como una lista ordenada de eslabones
``ChainStep(ProviderClass, model_override)``. El primer eslabón
disponible y operativo gana; si falla con un error recuperable, se salta
al siguiente. El último eslabón en TODAS las cadenas es la clave propia
del usuario (UserOwnProvider) para que el sistema nunca se quede sin
opciones siempre que el usuario haya configurado su `.env`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Type

from src.services.providers.base_provider import BaseProvider
from src.services.providers.cerebras_provider  import CerebrasProvider
from src.services.providers.gemini_provider    import GeminiProvider
from src.services.providers.groq_provider      import GroqProvider
from src.services.providers.sambanova_provider import SambanovaProvider
from src.services.providers.user_own_provider  import UserOwnProvider


# ─────────────────────────────────────────────────────────────────────
#  Nombres canónicos de tarea (constantes públicas)
# ─────────────────────────────────────────────────────────────────────

TASK_PROMPT_ANALYSIS  = "prompt_analysis"
TASK_QUERY_GENERATION = "query_generation"
TASK_VALIDATION       = "validation"


# ─────────────────────────────────────────────────────────────────────
#  Modelos por proveedor — CONFIGURABLES POR VARIABLE DE ENTORNO
#
#  IMPORTANTE: los IDs de modelo de los proveedores caducan cada pocos
#  meses. Para que el software NUNCA se rompa cuando eso pase, cada
#  modelo se lee de una variable de entorno y solo se usa un valor por
#  defecto (vivo a fecha de hoy) si la variable no está definida.
#
#  Cuando un proveedor deprecie un modelo, basta con poner el nuevo ID
#  en tu `.env` (p.ej. GROQ_MODEL_LARGE=openai/gpt-oss-120b) SIN tocar
#  el código.
#
#  Estado de los defaults (revisado jul-2026):
#    · Groq  llama-3.3-70b-versatile → vivo (sustituye al 3.1-70B que
#            fue DECOMISIONADO en ene-2025). Alternativa estable si
#            caduca: openai/gpt-oss-120b.
#    · Groq  llama-3.1-8b-instant    → vivo. Alternativa: openai/gpt-oss-20b.
#    · SambaNova Meta-Llama-3.3-70B-Instruct → vivo (el 405B fue RETIRADO
#            del cloud en jun-2025). Alternativa: DeepSeek-V3.1.
#    · Cerebras llama3.1-8b          → vivo. Grande: llama-3.3-70b.
#    · Gemini gemini-2.5-flash       → vivo (el 1.5-flash fue APAGADO,
#            devolvía 404). Alternativa futura: gemini-3.x-flash.
# ─────────────────────────────────────────────────────────────────────

def _env_model(env_key: str, default: str) -> str:
    """
    Lee el modelo desde una variable de entorno con fallback SEGURO.

    CRÍTICO: usamos ``os.getenv(key) or default`` en vez de
    ``os.getenv(key, default)``. La diferencia importa muchísimo aquí:
    si el usuario dejó la variable DEFINIDA PERO VACÍA en su `.env`
    (tal y como invita `.env.example`: "deja en blanco para usar el
    default"), ``os.getenv(key, default)`` NO usaría el default porque
    la variable SÍ existe — devolvería ``""`` y rompería la cadena
    entera de IA (modelo vacío → URL/payload inválido → 404/400 en
    Groq, SambaNova y Gemini simultáneamente).

    Con ``os.getenv(key) or default`` cualquier valor "vacío" (None,
    "", o solo espacios tras strip) cae al default.
    """
    value = os.getenv(env_key)
    if value is not None:
        value = value.strip()
    if value:
        return value
    return default


# Groq  (grande = análisis/queries; pequeño = validación rápida)
GROQ_LLAMA_70B = _env_model("GROQ_MODEL_LARGE", "llama-3.3-70b-versatile")
GROQ_LLAMA_8B  = _env_model("GROQ_MODEL_SMALL", "llama-3.1-8b-instant")

# SambaNova  (el 405B ya no está en el cloud; usamos el mayor Llama vivo)
SAMBA_LLAMA_405B = _env_model("SAMBANOVA_MODEL", "Meta-Llama-3.3-70B-Instruct")
SAMBA_LLAMA_70B  = _env_model("SAMBANOVA_MODEL", "Meta-Llama-3.3-70B-Instruct")

# Cerebras
CEREBRAS_LLAMA_70B = _env_model("CEREBRAS_MODEL_LARGE", "llama-3.3-70b")
CEREBRAS_LLAMA_8B  = _env_model("CEREBRAS_MODEL", "llama3.1-8b")

# Gemini
GEMINI_FLASH = _env_model("GEMINI_MODEL", "gemini-2.5-flash")


# ─────────────────────────────────────────────────────────────────────
#  Eslabón de la cadena
# ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ChainStep:
    """
    Un eslabón en la cadena de fallback de una tarea.

    Args:
        provider_class: Clase del provider a usar. Se instancia con
            argumentos por defecto (todos leen su API key del entorno).
        model: Nombre del modelo concreto que ese provider debe usar
            para esta tarea. None → usa el modelo por defecto del
            provider.
    """
    provider_class: Type[BaseProvider]
    model: Optional[str] = None

    def instantiate(self) -> BaseProvider:
        return self.provider_class()


# ─────────────────────────────────────────────────────────────────────
#  Definición de las 3 cadenas
# ─────────────────────────────────────────────────────────────────────

# 1. Análisis de prompt + decisiones de routing (Wappalyzer / ADN /
#    PageSpeed). Queremos una primera respuesta de alta calidad: Groq
#    70B es rápido y muy capaz; SambaNova 405B es el plan B con la
#    mejor calidad disponible; Gemini Flash como tercero por
#    estabilidad; y la clave propia del usuario al final.
PROMPT_ANALYSIS_CHAIN: List[ChainStep] = [
    ChainStep(GroqProvider,      GROQ_LLAMA_70B),
    ChainStep(SambanovaProvider, SAMBA_LLAMA_405B),
    ChainStep(GeminiProvider,    GEMINI_FLASH),
    ChainStep(UserOwnProvider,   None),
]

# 2. Generación de queries Google. Esta es la tarea donde más beneficia
#    un modelo grande (cobertura, sinónimos, slang del sector,
#    operadores avanzados): SambaNova 405B primero; Groq 70B como
#    respaldo rápido; Gemini Flash como tercer eslabón.
QUERY_GENERATION_CHAIN: List[ChainStep] = [
    ChainStep(SambanovaProvider, SAMBA_LLAMA_405B),
    ChainStep(GroqProvider,      GROQ_LLAMA_70B),
    ChainStep(GeminiProvider,    GEMINI_FLASH),
    ChainStep(UserOwnProvider,   None),
]

# 3. Validación final SI/NO. Aquí queremos velocidad y consistencia
#    sobre todo: Cerebras 8B es ultra rápido y suficientemente bueno
#    para un binario; Groq con 70B o 8B como segundo (el usuario pidió
#    "8B o 70B" — el catálogo cambia, así que probamos primero 70B
#    porque suele estar disponible y si falla la cadena salta al 8B
#    como un segundo eslabón de Groq con menor coste).
VALIDATION_CHAIN: List[ChainStep] = [
    ChainStep(CerebrasProvider, CEREBRAS_LLAMA_8B),
    ChainStep(GroqProvider,     GROQ_LLAMA_70B),
    ChainStep(GroqProvider,     GROQ_LLAMA_8B),
    ChainStep(GeminiProvider,   GEMINI_FLASH),
    ChainStep(UserOwnProvider,  None),
]


TASK_CHAINS: Dict[str, List[ChainStep]] = {
    TASK_PROMPT_ANALYSIS:  PROMPT_ANALYSIS_CHAIN,
    TASK_QUERY_GENERATION: QUERY_GENERATION_CHAIN,
    TASK_VALIDATION:       VALIDATION_CHAIN,
}


def get_chain(task_name: str) -> List[ChainStep]:
    """
    Devuelve la cadena de fallback para el nombre de tarea dado. Si el
    nombre no es conocido devuelve la cadena de PROMPT_ANALYSIS como
    valor sensato por defecto.
    """
    return TASK_CHAINS.get(task_name) or PROMPT_ANALYSIS_CHAIN


__all__ = [
    "TASK_PROMPT_ANALYSIS",
    "TASK_QUERY_GENERATION",
    "TASK_VALIDATION",
    "ChainStep",
    "PROMPT_ANALYSIS_CHAIN",
    "QUERY_GENERATION_CHAIN",
    "VALIDATION_CHAIN",
    "TASK_CHAINS",
    "get_chain",
]
