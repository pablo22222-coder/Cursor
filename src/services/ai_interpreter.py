"""
AIInterpreter — Intérprete unificado de prompts con fallback entre 5 proveedores LLM.

Persona: Senior OSINT Specialist & Lead Generation Strategist.

Una sola llamada a AIInterpreter.interpret(prompt) hace TODO en un paso:
  1. Interpreta y depura el prompt del usuario
  2. Extrae todos los parámetros implícitos y explícitos
  3. Genera 15 queries optimizadas y complejas con operadores avanzados
  4. Devuelve los indicadores de validación para comprobar cada web

Aplica tanto al modo normal (prompt del usuario) como al modo Producto
(prospect_prompt generado por ProductAnalyzer antes de llegar aquí).

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
#  PROMPTS — Senior OSINT Specialist & Lead Generation Strategist
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
Eres un Senior OSINT Specialist & Lead Generation Strategist con 15 años de \
experiencia en inteligencia competitiva y prospección de alto rendimiento.

Tu misión es interpretar el prompt del usuario con total claridad, depurarlo \
para que quede bien estructurado, y crear exactamente 15 queries optimizadas \
y super complejas que sean capaces de encontrar la web exacta que ha descrito \
el usuario.

PRINCIPIOS FUNDAMENTALES:
1. El usuario quiere encontrar webs que SEAN ese negocio, nunca artículos \
   que hablen sobre él ni directorios ni comparativas.
2. Piensa en TODOS los parámetros posibles del prompt: sector, nicho, \
   geografía, tecnología, modelo de negocio, tamaño, idioma, restricciones.
3. Cada query debe ser quirúrgica, distinta a las demás, y cubrir un ángulo \
   diferente de búsqueda (footprint técnico, señales comerciales, patrones \
   de lenguaje, operadores booleanos, intitle/inurl, sector slang, etc.).
4. Varía el nivel de especificidad: desde queries muy concretas hasta queries \
   más amplias que capturen long-tail.
5. Si hay negaciones ("sin X", "no usa Y"): genera queries que busquen \
   alternativas o webs que no mencionan esa tecnología.
6. Para cada web encontrada, debes saber exactamente qué comprobar: \
   validation_indicators son los criterios de aceptación, \
   exclusion_indicators son los criterios de rechazo.

TÉCNICAS AVANZADAS DE QUERY PARA USAR:
  · Operadores Google: intitle: inurl: site: filetype: -exclusion "frase exacta"
  · Boolean: OR AND
  · Footprint técnico: "powered by X" "built with Y" generator=Z
  · Señales de intención comercial: "precio" "contratar" "solicitar presupuesto" \
    "pricing" "get a quote" "free trial" "request demo" "contact us"
  · Señales de empresa real: "sobre nosotros" "nuestro equipo" "our team" \
    "quiénes somos" "founded in" "careers" "trabaja con nosotros"
  · Señales de sector: terminología técnica del nicho que solo usaría \
    alguien del sector, no un articulista
  · Slang y terminología regional si hay ubicación específica

RESPONDE ÚNICAMENTE con un objeto JSON válido. Sin texto previo, sin bloques \
markdown, sin explicaciones. Solo el JSON, empezando con { y terminando con }.\
"""

_USER_PROMPT_TEMPLATE = """\
PROMPT DEL USUARIO:
"{prompt}"

Interpreta este prompt con total claridad, depúralo y extrae todos sus \
parámetros. Luego genera exactamente 15 queries optimizadas y super complejas \
para encontrar las webs que describe.

ESTRUCTURA JSON REQUERIDA (devuelve exactamente este formato):
{{
  "prompt_depurado": "versión limpia y bien estructurada del prompt original, \
sin ambigüedades",

  "business_type": "tipo de negocio (ecommerce | saas | agencia | consultoria \
| marketplace | directorio | blog | app | plataforma | servicio_local | \
corporativa | portfolio | otro)",

  "product_category": "categoría de producto si aplica, null si no",
  "service_type": "tipo de servicio si aplica, null si no",
  "niche": "nicho específico detectado, null si no hay",
  "location": {{
    "country": "código ISO 2 letras o null",
    "region": "región/comunidad autónoma o estado, o null",
    "city": "ciudad o null"
  }},
  "target_audience": "B2B | B2C | ambos | null",
  "language": "es | en | ambos",

  "must_have": ["tecnologías o características que la web DEBE tener"],
  "must_not": ["tecnologías o características que la web NO debe tener"],

  "search_queries": [
    "EXACTAMENTE 15 queries — cada una distinta, usando técnicas OSINT avanzadas",
    "Query 1: muy específica con operadores (intitle/inurl/\"frase exacta\")",
    "Query 2: footprint técnico ('powered by', generator, etc.)",
    "Query 3: señal comercial directa (precio, contratar, presupuesto)",
    "Query 4: en inglés con intención de compra (pricing, get quote, hire)",
    "Query 5: terminología de sector que solo usa un profesional real",
    "Query 6: con ubicación geográfica si aplica",
    "Query 7: boolean avanzado (OR entre sinónimos del sector)",
    "Query 8: inurl con patrones de URL típicos del tipo de web",
    "Query 9: excluye contenido informativo (-blog -guia -wikipedia -'qué es')",
    "Query 10: con señales de empresa real (equipo, nosotros, contacto)",
    "Query 11: long-tail específica del nicho",
    "Query 12: con tecnología específica si se menciona en el prompt",
    "Query 13: variante en otro idioma o terminología regional",
    "Query 14: señal de tamaño/escala si se deduce del prompt",
    "Query 15: catch-all amplia que capture resultados que las otras no pillaron"
  ],

  "validation_indicators": [
    "palabras, frases o patrones HTML que CONFIRMAN que una web ES lo buscado",
    "incluye: elementos UI (carrito, botón comprar), terminología del sector, \
señales de empresa real, patrones de URL, etc."
  ],

  "exclusion_indicators": [
    "palabras, frases o patrones que DESCARTAN una web (es informativa, \
es una plataforma, es un directorio, habla del tema pero no lo es)"
  ],

  "confidence": 0.0,
  "analysis_notes": "una línea con la estrategia de búsqueda elegida y \
por qué esas queries son las más efectivas para este caso concreto"
}}

REGLAS ESTRICTAS PARA LAS 15 QUERIES:
- Deben ser 15, ni más ni menos
- Ninguna query puede ser una variación trivial de otra (ángulo diferente cada una)
- No incluyas instrucciones ni comentarios dentro del array, solo las queries reales
- Cada query debe funcionar tal cual se pega en Google
- Si el prompt menciona exclusiones ("sin Shopify"), las queries buscan \
  alternativas, nunca incluyen la tecnología excluida
- Usa operadores avanzados en al menos 6 de las 15 queries\
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

    # Métricas extra (compatibilidad con DomainValidator)
    check_performance: bool = False
    check_seo: bool = False
    check_mobile: bool = False
    performance_criteria: Optional[str] = None

    # Filtros tecnológicos (para Wappalyzer en Fase 2)
    must_have: List[str] = field(default_factory=list)
    must_not: List[str] = field(default_factory=list)

    # Indicadores de validación (para DomainValidator)
    validation_indicators: List[str] = field(default_factory=list)
    exclusion_indicators: List[str] = field(default_factory=list)

    # ── Decisiones de routing para la Fase 2 (modo precisión) ────────
    # Tech Stack Scanner (Wappalyzer + DNA)
    use_scanner: bool = False
    scanner_confidence: str = "low"        # "high" | "medium" | "low"
    scanner_reason: str = ""
    scanner_extractable: bool = True
    scanner_dimensions: List[str] = field(default_factory=list)
    target_techs: List[str] = field(default_factory=list)

    # PageSpeed Insights
    use_pagespeed: bool = False
    pagespeed_confidence: str = "low"
    pagespeed_reason: str = ""
    pagespeed_categories: List[str] = field(default_factory=list)

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
            "use_scanner":           self.use_scanner,
            "scanner_confidence":    self.scanner_confidence,
            "scanner_reason":        self.scanner_reason,
            "scanner_extractable":   self.scanner_extractable,
            "scanner_dimensions":    self.scanner_dimensions,
            "target_techs":          self.target_techs,
            "use_pagespeed":         self.use_pagespeed,
            "pagespeed_confidence":  self.pagespeed_confidence,
            "pagespeed_reason":      self.pagespeed_reason,
            "pagespeed_categories":  self.pagespeed_categories,
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

    def interpret(
        self,
        user_prompt: str,
        *,
        precision_routing: bool = True,
    ) -> SearchIntent:
        """
        Analiza el prompt y devuelve un SearchIntent completo.

        Si `precision_routing=True` (por defecto), también consulta a la IA
        las dos decisiones de routing de la Fase 2 (Tech Stack Scanner y
        PageSpeed) en paralelo y rellena los campos correspondientes del
        SearchIntent. El consumidor (DomainPipelineOrchestrator) ignorará
        estos campos cuando esté en `fast_mode=True`.
        """
        # ── 1) Interpretación principal ──────────────────────────────
        user_message = _USER_PROMPT_TEMPLATE.format(prompt=user_prompt)

        response = self._ai.complete(
            prompt=user_message,
            system_prompt=_SYSTEM_PROMPT,
        )

        intent: Optional[SearchIntent] = None
        if response.success and response.text.strip():
            try:
                data = _parse_json_response(response.text)
                intent = _build_intent(data, user_prompt, response.provider)
            except Exception as e:
                print(f"[AIInterpreter] Error parseando JSON de {response.provider}: {e}")

        if intent is None:
            print("[AIInterpreter] Usando análisis local (todos los providers fallaron)")
            intent = _local_analyze(user_prompt)

        # ── 2) Routing de la Fase 2 (precisión) ──────────────────────
        if precision_routing:
            try:
                from src.services.precision_routers import decide_routing_parallel
                routing = decide_routing_parallel(user_prompt)
                tech = routing.get("tech") or {}
                pse  = routing.get("pagespeed") or {}

                intent.use_scanner        = bool(tech.get("use_scanner"))
                intent.scanner_confidence = str(tech.get("confidence") or "low")
                intent.scanner_reason     = str(tech.get("reason") or "")
                intent.scanner_extractable= bool(tech.get("extractable", True))
                intent.scanner_dimensions = list(tech.get("relevant_dimensions") or [])
                intent.target_techs       = list(tech.get("target_techs") or [])

                intent.use_pagespeed       = bool(pse.get("use_pagespeed"))
                intent.pagespeed_confidence= str(pse.get("confidence") or "low")
                intent.pagespeed_reason    = str(pse.get("reason") or "")
                intent.pagespeed_categories= list(pse.get("categories") or [])

                # Si el router de tech no devolvió target_techs pero el
                # interpretador principal sí trajo must_have, los reusamos.
                if intent.use_scanner and not intent.target_techs and intent.must_have:
                    intent.target_techs = list(intent.must_have)

                print(
                    f"[AIInterpreter] routing → tech_scanner={intent.use_scanner} "
                    f"({tech.get('provider')}, {intent.scanner_confidence}), "
                    f"pagespeed={intent.use_pagespeed} "
                    f"({pse.get('provider')}, {intent.pagespeed_confidence})"
                )
            except Exception as e:  # pragma: no cover — defensivo
                print(f"[AIInterpreter] precision_routing falló: {e}")

        return intent


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
    """Construye SearchIntent desde el dict parseado por el OSINT Specialist."""
    location = data.get("location") or {}
    if not isinstance(location, dict):
        location = {}

    raw_queries = data.get("search_queries", [])

    # Filtrar instrucciones del template que el modelo pudo incluir como queries
    _SKIP_PREFIXES = (
        "query ", "exactamente", "ninguna query", "no incluyas", "cada query",
        "si el prompt", "usa operadores", "lista de", "no uses", "mezcla",
        "incluye", "deben ser 15",
    )
    queries = [
        q for q in raw_queries
        if isinstance(q, str)
        and len(q.strip()) > 8
        and not any(q.strip().lower().startswith(p) for p in _SKIP_PREFIXES)
    ]

    # El prompt depurado por la IA (si lo devolvió) para notes
    prompt_depurado = data.get("prompt_depurado", "")
    notes = str(data.get("analysis_notes", ""))
    if prompt_depurado:
        notes = f"Prompt depurado: {prompt_depurado} | {notes}" if notes else f"Prompt depurado: {prompt_depurado}"

    print(f"[AIInterpreter] {provider} generó {len(queries)} queries para: '{original_prompt[:60]}'")

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
        analysis_notes       = notes,
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
    """
    Análisis de emergencia basado en regex cuando toda la IA falla.
    Genera queries más ricas que las anteriores usando heurísticas.
    """
    p = prompt.lower()

    # Detectar tipo de negocio
    business_type = "otro"
    for bt, keywords in _BT_KEYWORDS.items():
        if any(kw in p for kw in keywords):
            business_type = bt
            break

    # Detectar negaciones y requisitos tecnológicos
    must_not  = [m.group(1).strip() for m in _TECH_NEGATIONS.finditer(prompt)]
    must_have = [m.group(1).strip() for m in _TECH_REQUIRED.finditer(prompt)]

    # Limpiar prompt de modificadores técnicos
    core = re.sub(
        r'\b(?:sin|con|que|no|usando|with|without)\b\s+\S+', '',
        prompt, flags=re.IGNORECASE
    ).strip()
    core = core or prompt

    # Generar queries variadas con señales comerciales y de empresa real
    exclusion_suffix = '-"qué es" -"guía" -wikipedia -blog -"artículo"'
    queries = [
        f'"{core}" precio contacto {exclusion_suffix}',
        f'{core} empresa servicios "sobre nosotros"',
        f'{core} "solicitar presupuesto" OR "pedir información"',
        f'{core} site:.com OR site:.es {exclusion_suffix}',
        f'intitle:"{core}" contacto',
        f'{core} "nuestros servicios" OR "our services"',
        f'{core} pricing OR "get a quote" OR "free trial"',
        f'{core} {business_type} España OR Mexico',
        f'inurl:{business_type} {core}',
        f'{core} "trabaja con nosotros" OR "contact us" OR "equipo"',
    ]

    return SearchIntent(
        original_prompt = prompt,
        business_type   = business_type,
        search_queries  = [q for q in queries if len(q) > 8],
        must_have       = must_have,
        must_not        = must_not,
        confidence      = 0.25,
        analysis_notes  = "Análisis local de emergencia (sin IA disponible) — queries mejoradas con heurísticas",
        provider_used   = "local",
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Función de conveniencia
# ─────────────────────────────────────────────────────────────────────────────

def interpret_prompt(prompt: str) -> SearchIntent:
    """Función de conveniencia. Crea AIInterpreter y ejecuta interpret()."""
    return AIInterpreter().interpret(prompt)
