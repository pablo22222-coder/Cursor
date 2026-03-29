"""
AIInterpreter — Intérprete unificado de prompts con fallback entre 5 proveedores LLM.

Reemplaza completamente a SemanticParser + GeminiInterpreter.
Una sola llamada a AIInterpreter.interpret(prompt) devuelve un SearchIntent
con TODO lo que el resto del sistema necesita:

  · business_type        → tipo de negocio real que busca el usuario
  · niche / location     → nicho específico y geografía
  · must_have / must_not → filtros de tecnología (Wappalyzer)
  · search_queries       → queries creadas por la IA bajo demanda, no plantillas
  · validation_indicators → palabras clave que confirman que una web ES lo buscado
  · exclusion_indicators  → palabras que indican que NO es lo buscado

Cadena de fallback (< 1 segundo de transición entre proveedores):
  0 → Groq          llama-3.2-3b-preview   (velocidad)
  1 → Cerebras      llama3.1-8b            (fiabilidad)
  2 → SambaNova     Meta-Llama-3.2-3B      (alta cuota)
  3 → Gemini        gemini-1.5-flash       (emergencia)
  4 → WebLLM local  Llama-3.2-3B GGUF     (offline)
  5 → Análisis local regex                 (último recurso sin IA)
"""
from __future__ import annotations

import json
import re
import os
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from src.services.ai_manager import get_ai_manager


# ─────────────────────────────────────────────────────────────────────────────
#  PROMPTS EXPERTOS
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
Eres un experto en prospección digital B2B/B2C con 15 años de experiencia \
encontrando negocios reales en internet. Tu especialidad es traducir peticiones \
en lenguaje natural a estrategias de búsqueda quirúrgicas que localicen \
EMPRESAS Y WEBS OPERATIVAS, nunca artículos informativos ni directorios.

REGLA FUNDAMENTAL: el usuario quiere encontrar webs que SEAN ese negocio, \
no webs que HABLEN sobre ese tipo de negocio.

EJEMPLOS DE DISTINCIÓN:
  ✗ MAL → artículo "Qué es un ecommerce de electrónica"
  ✓ BIEN → tienda online real que vende electrónica con carrito y precios
  ✗ MAL → "Las 10 mejores agencias de marketing digital"
  ✓ BIEN → una agencia real con página de servicios, equipo y contacto
  ✗ MAL → "Cómo crear un SaaS de gestión de proyectos"
  ✓ BIEN → una herramienta SaaS real con pricing, trial o demo

CRITERIOS DE CALIDAD PARA QUERIES:
  · Usa términos que los CLIENTES reales usarían para contratar/comprar
  · Combina intención comercial con términos descriptivos del sector
  · Incluye operadores implícitos: palabras como "comprar", "contratar", "precio",
    "presupuesto", "demo", "trial", "contactar"
  · Varía idioma (español e inglés) si el nicho es internacional
  · Si hay ubicación: incluye ciudad/país en algunas queries
  · Si hay negación ("sin X"): genera queries que encuentren alternativas a X
  · Genera entre 8 y 15 queries ordenadas de mayor a menor especificidad

RESPONDE ÚNICAMENTE con un objeto JSON válido, sin texto previo, sin bloques \
de código markdown, sin explicaciones. El JSON debe empezar con { y terminar con }.\
"""

_USER_PROMPT_TEMPLATE = """\
Analiza en profundidad la siguiente petición de búsqueda y devuelve el JSON \
con la estructura exacta indicada.

PETICIÓN DEL USUARIO:
"{prompt}"

ESTRUCTURA JSON REQUERIDA:
{{
  "business_type": "tipo de negocio exacto (ecommerce | saas | agencia | \
consultoria | marketplace | directorio | blog | app | plataforma | \
servicio_local | corporativa | portfolio | otro)",

  "product_category": "categoría de producto si aplica, null si no",
  "service_type": "tipo de servicio si aplica, null si no",
  "niche": "nicho específico si se menciona (luxury, budget, eco, old-money, etc.), null si no",
  "location": {{
    "country": "código ISO 2 letras o null",
    "region": "región/comunidad o null",
    "city": "ciudad o null"
  }},
  "target_audience": "B2B | B2C | ambos | null",
  "language": "es | en | ambos",

  "must_have": ["tecnologías o categorías que la web DEBE tener, array vacío si no"],
  "must_not": ["tecnologías o categorías que la web NO debe tener, array vacío si no"],

  "search_queries": [
    "lista de 8 a 15 queries específicas creadas para este prompt concreto",
    "NO uses plantillas genéricas — cada query debe ser única y pensada para este caso",
    "mezcla español e inglés según el mercado objetivo",
    "incluye queries con intención comercial directa"
  ],

  "validation_indicators": [
    "palabras o frases que al aparecer en una web confirman que ES lo buscado"
  ],
  "exclusion_indicators": [
    "palabras o frases que al aparecer en una web indican que NO es lo buscado"
  ],

  "confidence": número entre 0 y 1 indicando seguridad en el análisis,
  "analysis_notes": "una línea explicando la estrategia de búsqueda elegida"
}}

INSTRUCCIONES CRÍTICAS PARA search_queries:
- Analiza el prompt palabra por palabra antes de generar las queries
- Si el prompt menciona una tecnología en negativo ("sin Shopify"), genera queries
  que encuentren alternativas, NO webs con Shopify
- Si hay un nicho muy específico ("old money", "eco-friendly"), úsalo literalmente
  en algunas queries para máxima precisión
- Incluye siempre al menos: 3 queries en español, 2 en inglés, 2 con operadores
  de compra/contacto ("precio", "contratar", "buy", "pricing")
- Las queries deben ser lo que escribiría un comprador real en Google, no un académico\
"""


# ─────────────────────────────────────────────────────────────────────────────
#  DATACLASS DE SALIDA (compatible con todo el sistema existente)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SearchIntent:
    """
    Resultado unificado del análisis de prompt.
    Compatible con DomainValidator, DomainPipelineOrchestrator y SerperSearch.
    """
    # Obligatorios
    original_prompt: str
    business_type: str
    search_queries: List[str]

    # Opcionales
    product_category: Optional[str] = None
    service_type: Optional[str] = None
    niche: Optional[str] = None
    location: Dict[str, Optional[str]] = field(default_factory=dict)
    target_audience: Optional[str] = None
    language: str = "es"

    # Filtros tecnológicos (para Wappalyzer en Fase 2)
    must_have: List[str] = field(default_factory=list)
    must_not: List[str] = field(default_factory=list)

    # Indicadores de validación (para DomainValidator)
    validation_indicators: List[str] = field(default_factory=list)
    exclusion_indicators: List[str] = field(default_factory=list)

    # Meta
    confidence: float = 0.5
    analysis_notes: str = ""
    provider_used: str = "local"   # qué LLM respondió

    # Alias de compatibilidad para módulos que usaban PromptAnalysis
    @property
    def required_tools(self) -> List[str]:
        return self.must_have

    @property
    def excluded_tools(self) -> List[str]:
        return self.must_not

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_prompt":       self.original_prompt,
            "business_type":         self.business_type,
            "product_category":      self.product_category,
            "service_type":          self.service_type,
            "niche":                 self.niche,
            "location":              self.location,
            "target_audience":       self.target_audience,
            "language":              self.language,
            "must_have":             self.must_have,
            "must_not":              self.must_not,
            "search_queries":        self.search_queries,
            "validation_indicators": self.validation_indicators,
            "exclusion_indicators":  self.exclusion_indicators,
            "confidence":            self.confidence,
            "analysis_notes":        self.analysis_notes,
            "provider_used":         self.provider_used,
        }


# ─────────────────────────────────────────────────────────────────────────────
#  INTÉRPRETE PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

class AIInterpreter:
    """
    Intérprete unificado de prompts de usuario.

    Uso:
        intent = AIInterpreter().interpret("ecommerce de crema facial sin shopify")
        # intent.search_queries → lista de queries generadas por IA
        # intent.must_not       → ["shopify"]
        # intent.business_type  → "ecommerce"
    """

    def __init__(self):
        self._ai = get_ai_manager()

    def interpret(self, user_prompt: str) -> SearchIntent:
        """
        Analiza el prompt y devuelve un SearchIntent completo.
        Usa AIManager para fallback automático entre proveedores.
        Si todos fallan, ejecuta análisis local basado en regex.
        """
        user_message = _USER_PROMPT_TEMPLATE.format(prompt=user_prompt)

        response = self._ai.complete(
            prompt=user_message,
            system_prompt=_SYSTEM_PROMPT,
        )

        if response.success and response.text.strip():
            try:
                data = _parse_json_response(response.text)
                return _build_intent(data, user_prompt, response.provider)
            except Exception as e:
                print(f"[AIInterpreter] Error parseando JSON de {response.provider}: {e}")

        # Fallback local
        print("[AIInterpreter] Usando análisis local (todos los providers fallaron)")
        return _local_analyze(user_prompt)


# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS INTERNOS
# ─────────────────────────────────────────────────────────────────────────────

def _parse_json_response(text: str) -> Dict[str, Any]:
    """Extrae y parsea JSON de la respuesta del LLM."""
    cleaned = text.strip()
    # Eliminar bloques markdown si el modelo los incluyó a pesar del system prompt
    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'\s*```$', '', cleaned, flags=re.MULTILINE)
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Intentar extraer el objeto JSON más externo
        match = re.search(r'\{[\s\S]*\}', cleaned)
        if match:
            return json.loads(match.group())
        raise ValueError(f"No se encontró JSON válido en: {cleaned[:300]}")


def _build_intent(data: Dict[str, Any], original_prompt: str, provider: str) -> SearchIntent:
    """Construye SearchIntent desde el dict parseado."""
    location = data.get("location") or {}
    if not isinstance(location, dict):
        location = {}

    queries = data.get("search_queries", [])
    # Filtrar instrucciones que el modelo pudo haber incluido como queries
    queries = [
        q for q in queries
        if isinstance(q, str) and len(q) > 5
        and not q.lower().startswith("lista de")
        and not q.lower().startswith("no uses")
        and not q.lower().startswith("mezcla")
        and not q.lower().startswith("incluye")
    ]

    return SearchIntent(
        original_prompt      = original_prompt,
        business_type        = str(data.get("business_type", "otro")).lower(),
        product_category     = data.get("product_category") or None,
        service_type         = data.get("service_type") or None,
        niche                = data.get("niche") or None,
        location             = {
            "country": location.get("country"),
            "region":  location.get("region"),
            "city":    location.get("city"),
        },
        target_audience      = data.get("target_audience") or None,
        language             = str(data.get("language", "es")),
        must_have            = list(data.get("must_have") or []),
        must_not             = list(data.get("must_not") or []),
        search_queries       = queries,
        validation_indicators= list(data.get("validation_indicators") or []),
        exclusion_indicators = list(data.get("exclusion_indicators") or []),
        confidence           = float(data.get("confidence", 0.7)),
        analysis_notes       = str(data.get("analysis_notes", "")),
        provider_used        = provider,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  ANÁLISIS LOCAL (sin IA — último recurso)
# ─────────────────────────────────────────────────────────────────────────────

_BT_KEYWORDS = {
    "ecommerce": ["tienda", "shop", "ecommerce", "comprar", "vender", "producto", "online store"],
    "saas":      ["saas", "software", "herramienta", "plataforma", "app", "tool"],
    "agencia":   ["agencia", "agency", "estudio", "consultora", "freelance"],
    "blog":      ["blog", "artículos", "noticias", "revista", "media"],
    "marketplace":["marketplace", "plataforma de venta", "multi-vendor"],
    "servicio_local":["restaurante", "bar", "peluquería", "clínica", "dentista", "fontanero"],
}

_TECH_NEGATIONS = re.compile(
    r'\b(?:sin|no|without|excluir|evitar|que no use[n]?|que no ten[ga]+)\s+'
    r'([a-zA-Z0-9_\- ]+?)(?=\s*(?:y|,|$|\.))',
    re.IGNORECASE
)
_TECH_REQUIRED = re.compile(
    r'\b(?:con|with|que use[n]?|que ten[ga]+|usando)\s+'
    r'([a-zA-Z0-9_\- ]+?)(?=\s*(?:y|,|$|\.))',
    re.IGNORECASE
)


def _local_analyze(prompt: str) -> SearchIntent:
    """Análisis de emergencia basado en regex cuando toda la IA falla."""
    p = prompt.lower()

    # Detectar tipo de negocio
    business_type = "otro"
    for bt, keywords in _BT_KEYWORDS.items():
        if any(kw in p for kw in keywords):
            business_type = bt
            break

    # Detectar negaciones tecnológicas
    must_not = [m.group(1).strip() for m in _TECH_NEGATIONS.finditer(prompt)]
    must_have = [m.group(1).strip() for m in _TECH_REQUIRED.finditer(prompt)]

    # Queries básicas
    clean_prompt = re.sub(r'\b(?:sin|con|que|no|sin)\b\s+\S+', '', prompt, flags=re.IGNORECASE).strip()
    queries = [
        f"{business_type} {clean_prompt}",
        f"{clean_prompt} sitio web",
        f"{clean_prompt} contacto",
        f"{clean_prompt} empresa",
        f"site:{business_type} {clean_prompt}",
    ]

    return SearchIntent(
        original_prompt = prompt,
        business_type   = business_type,
        search_queries  = [q for q in queries if len(q) > 5],
        must_have       = must_have,
        must_not        = must_not,
        confidence      = 0.25,
        analysis_notes  = "Análisis local (emergencia — sin IA disponible)",
        provider_used   = "local",
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Función de conveniencia
# ─────────────────────────────────────────────────────────────────────────────

def interpret_prompt(prompt: str) -> SearchIntent:
    """Función de conveniencia. Crea AIInterpreter y ejecuta interpret()."""
    return AIInterpreter().interpret(prompt)
