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
#  Modelos canónicos (etiquetas explícitas)
#
#  Mantenemos los nombres de modelo aquí para que las cadenas queden
#  super claras y se puedan cambiar sin tocar los providers.
# ─────────────────────────────────────────────────────────────────────

# Groq
GROQ_LLAMA_70B = "llama-3.1-70b-versatile"
GROQ_LLAMA_8B  = "llama-3.1-8b-instant"

# SambaNova
SAMBA_LLAMA_405B = "Meta-Llama-3.1-405B-Instruct"
SAMBA_LLAMA_70B  = "Meta-Llama-3.1-70B-Instruct"

# Cerebras (alias del catálogo público)
CEREBRAS_LLAMA_70B = "llama3.1-70b"
CEREBRAS_LLAMA_8B  = "llama3.1-8b"

# Gemini
GEMINI_FLASH = "gemini-1.5-flash"


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
