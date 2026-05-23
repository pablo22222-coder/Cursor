"""
AIInterpreter — Intérprete unificado de prompts con dos cadenas de
fallback de LLM ejecutadas en paralelo.

Arquitectura
------------
``AIInterpreter.interpret(prompt)`` hace tres trabajos a la vez:

  1. **Análisis estructurado del prompt** (cadena
     ``TASK_PROMPT_ANALYSIS`` → Groq 70B → SambaNova 405B → Gemini →
     User Own). Extrae sector, nicho, ubicación, audiencia, idioma,
     listas must_have/must_not, indicadores de validación, etc.

  2. **Generación de queries de Google** (cadena
     ``TASK_QUERY_GENERATION`` → SambaNova 405B → Groq 70B → Gemini →
     User Own). Produce 15 queries OSINT optimizadas, distintas y
     accionables.

  3. **Routing de Fase 2 en modo precisión** (cadena
     ``TASK_PROMPT_ANALYSIS``): decide si activar Tech Scanner y/o
     PageSpeed. Se hace en paralelo con los dos puntos anteriores.

Los tres se lanzan en threads para minimizar la latencia. Si alguna
falla, los demás siguen y se rellena con defaults seguros. Si las dos
llamadas principales (analysis + queries) fallan, cae al
``_local_analyze`` basado en regex.
"""
from __future__ import annotations

import concurrent.futures
import json
import re
import os
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from src.services.ai_manager import complete_for_task
from src.services.task_chains import (
    TASK_PROMPT_ANALYSIS,
    TASK_QUERY_GENERATION,
)


# ─────────────────────────────────────────────────────────────────────────────
#  PROMPT — Análisis estructurado del prompt
# ─────────────────────────────────────────────────────────────────────────────

_ANALYSIS_SYSTEM_PROMPT = """\
Eres "Prompt Analyst", un analista sénior de inteligencia comercial \
especializado en transformar descripciones libres del usuario en una \
ficha técnica estructurada y machine-readable.

Tu único trabajo es DECODIFICAR el prompt y devolver SUS PARÁMETROS en \
un JSON con un schema fijo. NO generas queries de Google, NO escribes \
copys, NO razonas por escrito — solo extraes datos.

PRINCIPIOS

  1. Distingue siempre WEB-TARGET vs WEB-AUDIENCE.
     · WEB-TARGET: el usuario pide "encuéntrame webs que SON X".
     · WEB-AUDIENCE: el usuario describe el comprador ideal de su
       producto. En ambos casos tu output describe la web a encontrar.

  2. Sé minucioso pero conservador.
     · Si un parámetro NO está claro en el prompt, devuélvelo como null
       o lista vacía. NO inventes ubicaciones, tecnologías o tamaños.
     · Si el usuario dice "sin Shopify" o "que no use X" → mete X en
       ``must_not``. Si dice "con Klaviyo" o "que use Y" → en
       ``must_have``. Usa nombres canónicos (Shopify, Klaviyo,
       WordPress, Google Analytics, HubSpot, Stripe...). Para
       categorías genéricas usa minúsculas: crm, cms, analytics,
       email_marketing, live_chat, payment, ecommerce.

  3. Indicadores de validación y exclusión deben ser cadenas concretas
     que un parser pueda buscar en el HTML: textos visibles, clases
     CSS comunes, patrones de URL, terminología del sector, palabras
     que confirmen ("añadir al carrito", "pedir presupuesto",
     "pricing") o que descarten ("qué es", "definición", "wikipedia",
     "comparativa").

  4. ``business_type`` debe pertenecer al enum cerrado:
     ecommerce | saas | agencia | consultoria | marketplace |
     directorio | blog | app | plataforma | servicio_local |
     corporativa | portfolio | otro.

  5. ``language`` ∈ { "es", "en", "ambos" }.
     ``target_audience`` ∈ { "B2B", "B2C", "ambos", null }.

  6. Si el prompt está limpio y bien expresado, ``prompt_depurado``
     puede ser idéntico al original. Si está mal redactado, ofrece
     una versión equivalente sin ambigüedades pero SIN CAMBIAR LA
     INTENCIÓN.

FORMATO DE SALIDA — JSON ESTRICTO, sin comentarios, sin texto antes ni \
después, sin bloques markdown. Empieza con `{` y termina con `}`.\
"""

_ANALYSIS_USER_TEMPLATE = """\
PROMPT DEL USUARIO:
\"\"\"{prompt}\"\"\"

Devuelve EXACTAMENTE este objeto JSON con los datos extraídos del \
prompt. Si un campo no tiene información, devuelve null o lista vacía \
(NO lo inventes).

{{
  "prompt_depurado": "string · versión clara y unívoca del prompt",
  "business_type":   "ecommerce | saas | agencia | consultoria | marketplace | directorio | blog | app | plataforma | servicio_local | corporativa | portfolio | otro",
  "product_category": "string o null",
  "service_type":    "string o null",
  "niche":           "string o null",
  "location": {{
    "country": "código ISO-3166-1 alfa-2 o null",
    "region":  "string o null",
    "city":    "string o null"
  }},
  "target_audience": "B2B | B2C | ambos | null",
  "language":        "es | en | ambos",
  "must_have":       ["lista de strings — tecnologías/atributos OBLIGATORIOS"],
  "must_not":        ["lista de strings — tecnologías/atributos PROHIBIDOS"],
  "validation_indicators": [
    "palabras o patrones HTML que CONFIRMAN que una web encaja"
  ],
  "exclusion_indicators": [
    "palabras o patrones HTML que DESCARTAN una web (informativos, \
directorios, comparativas, contenido genérico, etc.)"
  ],
  "confidence":     0.0,
  "analysis_notes": "una frase con la estrategia clave (de dónde sale \
el sector, qué tecnologías son críticas, qué excluir, etc.)"
}}\
"""


# ─────────────────────────────────────────────────────────────────────────────
#  PROMPT — Generación de queries Google
# ─────────────────────────────────────────────────────────────────────────────

_QUERIES_SYSTEM_PROMPT = """\
Eres "Query Strategist", un experto OSINT en formular dorks de Google \
quirúrgicos para descubrir webs de empresas reales (no artículos, no \
directorios, no comparativas).

Tu único trabajo es generar las QUERIES — no analizas semántica, no \
clasificas, no devuelves metadata. Solo queries listas para Serper.

PRINCIPIOS

  1. El objetivo es siempre **encontrar webs que SON el negocio \
     descrito**, no webs que hablen sobre él. Cada query debe optimizar \
     ese filtro.

  2. Diversidad y cobertura. Cada query debe atacar el problema desde \
     un ángulo distinto: footprint técnico, señal comercial, slang del \
     sector, operadores avanzados (intitle/inurl/site/-exclusion/ \
     "frase exacta"/OR), señales de empresa real, long-tail, idioma \
     local, ubicación, etc.

  3. Operadores avanzados. Al menos 6 de las 15 queries deben usar uno \
     o más operadores Google (intitle:, inurl:, "frase exacta", OR, \
     -exclusion, site:). Sin abusar.

  4. Negaciones. Si el prompt o el análisis traen ``must_not``, NO \
     menciones esas tecnologías en las queries. En su lugar, busca \
     alternativas o usa "-shopify" como filtro.

  5. Geografía / idioma. Si hay ``location`` o ``language``, al menos \
     una query debe localizarla (TLD .es / .com.mx, ciudad, slang \
     regional). Si no hay ubicación, NO inventes ninguna.

  6. Cada query debe pegarse tal cual en Google y devolver resultados \
     reales. NO uses operadores que Google ya no soporta (allintitle:, \
     inanchor: a veces, link:). Comillas dobles solo para frases \
     exactas. Evita queries de más de 32 palabras (Google trunca).

  7. NO escribas instrucciones, comentarios ni numeración dentro del \
     array — solo las queries en sí.

FORMATO DE SALIDA — JSON estricto: { "search_queries": [ ... 15 strings ... ] }\
"""

_QUERIES_USER_TEMPLATE = """\
PROMPT DEL USUARIO:
\"\"\"{prompt}\"\"\"

ANÁLISIS PREVIO (puede venir vacío si el otro analista todavía no ha \
terminado — en ese caso tira solo del prompt):

{analysis_block}

Devuelve EXACTAMENTE 15 queries listas para Serper / Google. Cubre \
ángulos distintos y respeta las negaciones del análisis. Usa \
operadores avanzados en al menos 6 de las 15.

FORMATO de respuesta (JSON, sin nada más):
{{
  "search_queries": [
    "query 1",
    "query 2",
    "...",
    "query 15"
  ]
}}\
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

    Lanza en paralelo tres trabajos de IA con cadenas de fallback
    distintas y los ensambla en un único ``SearchIntent``:

      · Análisis estructurado (TASK_PROMPT_ANALYSIS).
      · Generación de 15 queries (TASK_QUERY_GENERATION).
      · (Opcional, solo en precisión) routing de Tech Scanner +
        PageSpeed (TASK_PROMPT_ANALYSIS).

    Uso:
        intent = AIInterpreter().interpret("ecommerce de crema facial sin shopify")
    """

    def __init__(self):
        # Antes guardábamos un AIManager singleton. Ahora cada llamada
        # va por la cadena de tarea correspondiente; no necesitamos
        # mantener referencia local.
        pass

    # ──────────────────────────────────────────────────────────────────
    #  API pública
    # ──────────────────────────────────────────────────────────────────

    def interpret(
        self,
        user_prompt: str,
        *,
        precision_routing: bool = True,
    ) -> SearchIntent:
        """
        Analiza el prompt y devuelve un SearchIntent completo.

        Si ``precision_routing=True`` (por defecto), además consulta a la
        IA las dos decisiones de routing de Fase 2 (Tech Scanner y
        PageSpeed) en paralelo. En modo rápido pasa
        ``precision_routing=False`` para evitar latencia innecesaria.
        """
        if not user_prompt or not user_prompt.strip():
            return _local_analyze(user_prompt or "")

        # Lanzamos analysis + queries en paralelo. El router de Fase 2
        # también va en paralelo si está activo. Total: 2 o 3 hilos.
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            fut_analysis = pool.submit(self._run_analysis, user_prompt)
            fut_queries  = pool.submit(self._run_queries,  user_prompt)
            fut_routing  = (
                pool.submit(self._run_precision_routing, user_prompt)
                if precision_routing else None
            )

            analysis_data, analysis_provider = fut_analysis.result()
            queries_list, queries_provider   = fut_queries.result()
            routing                          = fut_routing.result() if fut_routing else None

        # ── Construir SearchIntent ───────────────────────────────────
        if not analysis_data:
            print(
                "[AIInterpreter] Análisis IA falló — usando análisis "
                "local de emergencia"
            )
            intent = _local_analyze(user_prompt)
            # Si los queries SÍ fueron generados, reemplazamos las
            # queries del local_analyze por las de la IA.
            if queries_list:
                intent.search_queries = queries_list
                intent.provider_used = f"{intent.provider_used}+{queries_provider}"
        else:
            intent = _build_intent(
                analysis_data,
                user_prompt,
                provider=analysis_provider,
                queries_override=queries_list,
                queries_provider=queries_provider,
            )

        # ── Routing de Fase 2 (precisión) ────────────────────────────
        if routing is not None:
            self._apply_routing_to_intent(intent, routing)

        return intent

    # ──────────────────────────────────────────────────────────────────
    #  Sub-trabajos (cada uno en su propio thread)
    # ──────────────────────────────────────────────────────────────────

    def _run_analysis(self, user_prompt: str) -> tuple:
        """Llama a la cadena TASK_PROMPT_ANALYSIS para extraer parámetros."""
        msg = _ANALYSIS_USER_TEMPLATE.format(prompt=user_prompt[:2000])
        try:
            resp = complete_for_task(
                TASK_PROMPT_ANALYSIS,
                prompt=msg,
                system_prompt=_ANALYSIS_SYSTEM_PROMPT,
                json_mode=True,
            )
        except Exception as exc:  # pragma: no cover — defensivo
            print(f"[AIInterpreter] error en analysis: {exc}")
            return None, "error"

        if not resp.success or not resp.text.strip():
            return None, getattr(resp, "provider", "none")

        try:
            data = _parse_json_response(resp.text)
            return data, getattr(resp, "provider", "unknown")
        except Exception as e:
            print(
                f"[AIInterpreter] analysis: JSON inválido de "
                f"{getattr(resp, 'provider', '?')}: {e}"
            )
            return None, getattr(resp, "provider", "error")

    def _run_queries(self, user_prompt: str) -> tuple:
        """Llama a la cadena TASK_QUERY_GENERATION para producir 15 queries."""
        # En esta versión no esperamos al analysis: pasamos
        # analysis_block vacío y dejamos que el query strategist tire
        # del prompt directo. Esto permite ejecutar ambos en paralelo
        # sin dependencias.
        msg = _QUERIES_USER_TEMPLATE.format(
            prompt=user_prompt[:2000],
            analysis_block="(en paralelo — no disponible aún)",
        )
        try:
            resp = complete_for_task(
                TASK_QUERY_GENERATION,
                prompt=msg,
                system_prompt=_QUERIES_SYSTEM_PROMPT,
                json_mode=True,
            )
        except Exception as exc:  # pragma: no cover — defensivo
            print(f"[AIInterpreter] error en queries: {exc}")
            return [], "error"

        if not resp.success or not resp.text.strip():
            return [], getattr(resp, "provider", "none")

        try:
            data = _parse_json_response(resp.text)
        except Exception as e:
            print(
                f"[AIInterpreter] queries: JSON inválido de "
                f"{getattr(resp, 'provider', '?')}: {e}"
            )
            return [], getattr(resp, "provider", "error")

        raw = data.get("search_queries") or data.get("queries") or []
        if not isinstance(raw, list):
            return [], getattr(resp, "provider", "unknown")
        cleaned = _clean_queries(raw)
        return cleaned, getattr(resp, "provider", "unknown")

    def _run_precision_routing(self, user_prompt: str) -> Optional[Dict[str, Any]]:
        """Ejecuta el routing de Fase 2 (Tech Scanner + PageSpeed)."""
        try:
            from src.services.precision_routers import decide_routing_parallel
            return decide_routing_parallel(user_prompt)
        except Exception as e:  # pragma: no cover — defensivo
            print(f"[AIInterpreter] precision_routing falló: {e}")
            return None

    # ──────────────────────────────────────────────────────────────────
    #  Helpers
    # ──────────────────────────────────────────────────────────────────

    def _apply_routing_to_intent(self, intent: "SearchIntent",
                                  routing: Dict[str, Any]) -> None:
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

        # Si el router de tech no devolvió target_techs pero el analyst
        # principal sí trajo must_have, los reusamos.
        if intent.use_scanner and not intent.target_techs and intent.must_have:
            intent.target_techs = list(intent.must_have)

        print(
            f"[AIInterpreter] routing → tech_scanner={intent.use_scanner} "
            f"({tech.get('provider')}, {intent.scanner_confidence}), "
            f"pagespeed={intent.use_pagespeed} "
            f"({pse.get('provider')}, {intent.pagespeed_confidence})"
        )


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


_SKIP_QUERY_PREFIXES = (
    "query ", "exactamente", "ninguna query", "no incluyas", "cada query",
    "si el prompt", "usa operadores", "lista de", "no uses", "mezcla",
    "incluye", "deben ser 15", "ejemplo:", "example:",
)


def _clean_queries(raw: List[Any]) -> List[str]:
    """
    Filtra una lista cruda de queries devuelta por la IA:
      · solo strings,
      · ≥9 caracteres,
      · sin prefijos que delaten que el modelo coló una instrucción.
    """
    out: List[str] = []
    for q in raw:
        if not isinstance(q, str):
            continue
        s = q.strip().strip("`'\"")
        if len(s) <= 8:
            continue
        if any(s.lower().startswith(p) for p in _SKIP_QUERY_PREFIXES):
            continue
        if s in out:
            continue
        out.append(s)
    return out


def _build_intent(
    data: Dict[str, Any],
    original_prompt: str,
    *,
    provider: str,
    queries_override: Optional[List[str]] = None,
    queries_provider: str = "",
) -> SearchIntent:
    """
    Construye SearchIntent desde el dict del analyst (TASK_PROMPT_ANALYSIS).
    Si ``queries_override`` no es None, esas son las queries usadas (vienen
    de la llamada paralela a TASK_QUERY_GENERATION).
    """
    location = data.get("location") or {}
    if not isinstance(location, dict):
        location = {}

    # Queries: prioridad a las del Query Strategist; si no hay, vemos si
    # el Analyst nos las dio en su JSON (compatibilidad hacia atrás).
    if queries_override is not None:
        queries = queries_override
    else:
        queries = _clean_queries(data.get("search_queries", []) or [])

    prompt_depurado = data.get("prompt_depurado", "")
    notes = str(data.get("analysis_notes", ""))
    if prompt_depurado:
        notes = (
            f"Prompt depurado: {prompt_depurado} | {notes}"
            if notes else f"Prompt depurado: {prompt_depurado}"
        )

    # provider_used refleja AMBAS llamadas si los dos providers se usaron.
    combined_provider = provider
    if queries_provider and queries_provider != provider:
        combined_provider = f"{provider}+{queries_provider}"

    print(
        f"[AIInterpreter] analysis={provider}, "
        f"queries={queries_provider or 'local/none'} "
        f"→ {len(queries)} queries para: '{original_prompt[:60]}'"
    )

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
        provider_used        = combined_provider,
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
