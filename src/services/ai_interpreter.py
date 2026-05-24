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
(OSINT + Lead Generation) especializado en transformar descripciones \
libres del usuario en una ficha técnica estructurada y machine-readable.

Tu único trabajo es DECODIFICAR el prompt y devolver SUS PARÁMETROS en \
un JSON con un schema fijo. NO generas queries de Google, NO escribes \
copys, NO razonas por escrito fuera del JSON — solo extraes datos.

═══════════════════════════════════════════════════════════════════════
PRINCIPIOS
═══════════════════════════════════════════════════════════════════════

  1. WEB-TARGET vs WEB-AUDIENCE (no te confundas):
     · WEB-TARGET (modo prompt): el usuario pide "encuéntrame webs que
       SON X" → describes esas webs.
     · WEB-AUDIENCE (modo producto): el usuario describe a su comprador
       ideal (otro módulo ya lo tradujo a "describe la web compradora")
       → describes esas webs igual.
     En AMBOS casos tu output describe el TIPO DE WEB a encontrar.

  2. Conservador con lo que no está. Si un parámetro NO está claro en
     el prompt, devuélvelo como null o lista vacía. NO inventes
     ubicaciones, tecnologías, tamaños o idiomas. Solo extrae lo que
     el usuario ha dicho explícitamente o lo que es trivialmente
     deducible (ej.: "tienda online de bicicletas en Barcelona" → city
     = "Barcelona", country = "ES").

  3. Negaciones y requisitos tecnológicos:
     · "sin Shopify", "que no use X", "no shopify" → en ``must_not``.
     · "con Klaviyo", "que use Y", "usando Stripe" → en ``must_have``.
     · Usa nombres CANÓNICOS para que casen con Wappalyzer/BD pública:
       Shopify, WooCommerce, Magento, PrestaShop, BigCommerce,
       WordPress, Drupal, Joomla, Wix, Webflow, Squarespace, Ghost,
       Klaviyo, Mailchimp, ActiveCampaign, Brevo, ConvertKit, HubSpot,
       Salesforce, Pipedrive, Zoho, Stripe, PayPal, Redsys, Intercom,
       Drift, Tidio, Crisp, Zendesk, Google Analytics, Hotjar,
       Facebook Pixel, Google Tag Manager, TikTok Pixel, reCAPTCHA,
       React, Vue, Angular, Next.js, Nuxt.
     · Para categorías GENÉRICAS (no marca concreta) usa minúsculas:
       crm | cms | analytics | email_marketing | live_chat | payment |
       ecommerce | seo.

  4. Indicadores HTML (validation_indicators / exclusion_indicators):
     · Cadenas CONCRETAS que un parser pueda buscar en el HTML.
     · Validation: textos UI / clases CSS / patrones de URL /
       terminología del sector / señales de empresa real ("añadir al
       carrito", "pedir presupuesto", "/precio", "/contacto",
       "founded in", "nuestro equipo", "free trial", "checkout",
       "case studies").
     · Exclusion: señales de contenido informativo / directorio /
       comparativa / wiki ("qué es", "guía completa", "wikipedia",
       "comparativa", "top 10", "vs", "definición", "ranking").

  5. ``business_type`` (enum cerrado, elige UNO):
       ecommerce       — tienda online que VENDE productos físicos/digitales
       saas            — software como servicio con login y pricing recurring
       agencia         — servicios profesionales prestados por equipo (mkt, diseño, dev…)
       consultoria     — asesoría / consultoría experta (legal, fiscal, estrategia…)
       marketplace     — múltiples vendedores en una sola plataforma
       directorio      — listado/catálogo de terceros (Páginas Amarillas estilo)
       blog            — sitio editorial / media / revista
       app             — aplicación móvil con landing
       plataforma      — herramienta o servicio web no-SaaS típico
       servicio_local  — negocio físico con presencia local (clínica, peluquería, restaurante…)
       corporativa     — sitio institucional de empresa grande/mediana
       portfolio       — portfolio individual o de freelance
       otro            — solo si ninguno encaja claramente

  6. ``language`` ∈ { "es", "en", "ambos" }.
     ``target_audience`` ∈ { "B2B", "B2C", "ambos", null }.
     Si el usuario no lo especifica explícitamente y se puede deducir
     con confianza alta del sector, lo deduces (ej. "tienda online de
     juguetes" → B2C; "software CRM para agencias" → B2B). Si no se
     puede deducir con confianza, usa null.

  7. ``search_strategy`` (nueva): UNA frase que resuma el ángulo de
     ataque que un buscador OSINT seguiría para encontrar estas webs.
     Esta frase la usará después el generador de queries.
     Ejemplos:
       · "footprint técnico de Shopify + slang ecommerce de
         bicicletas + geo Barcelona/España, excluir blogs y rankings"
       · "señales de empresa B2B con CRM no propio + sector marketing
         digital + geografía hispana, excluir directorios"

  8. ``sector_keywords`` (nueva): 3-8 términos REALES del argot del
     sector que solo usaría un profesional del nicho, no un
     articulista. Sirven para que las queries usen vocabulario nativo.
     Ejemplos:
       · Bicicletas ebike: ["e-bike", "ciclismo urbano", "MTB",
         "kit conversión", "asistencia eléctrica"]
       · Clínica dental: ["ortodoncia invisible", "implantes
         all-on-4", "endodoncia", "estética dental", "Invisalign"]

  9. ``prompt_depurado``: si el prompt está limpio, idéntico al
     original; si tiene ambigüedades, una versión clara SIN cambiar
     la intención.

═══════════════════════════════════════════════════════════════════════
EJEMPLOS — entrada → salida JSON exacta
═══════════════════════════════════════════════════════════════════════

EJEMPLO 1
Entrada: "tienda online de bicicletas eléctricas en Barcelona con Shopify, sin wix"
Salida:
{
  "prompt_depurado": "tienda online de bicicletas eléctricas en Barcelona, plataforma Shopify, no Wix",
  "business_type": "ecommerce",
  "product_category": "bicicletas eléctricas",
  "service_type": null,
  "niche": "movilidad urbana eléctrica",
  "location": {"country": "ES", "region": "Cataluña", "city": "Barcelona"},
  "target_audience": "B2C",
  "language": "es",
  "must_have": ["Shopify"],
  "must_not": ["Wix"],
  "validation_indicators": ["añadir al carrito", "checkout", "envío", "stock", "tienda online", "powered by Shopify"],
  "exclusion_indicators": ["qué es una ebike", "guía completa", "comparativa", "mejores e-bikes", "ranking"],
  "confidence": 0.92,
  "analysis_notes": "Ecommerce con plataforma específica y ubicación concreta — caso típico de footprint Shopify",
  "search_strategy": "footprint de Shopify + slang ebike + geo Barcelona/España, excluir blogs/rankings",
  "sector_keywords": ["e-bike", "bicicleta urbana", "asistencia eléctrica", "ciclismo eléctrico", "MTB eléctrica"]
}

EJEMPLO 2
Entrada: "agencias de marketing digital en Latinoamérica que necesiten un CRM propio"
Salida:
{
  "prompt_depurado": "agencias de marketing digital en Latinoamérica sin CRM propio",
  "business_type": "agencia",
  "product_category": null,
  "service_type": "marketing digital",
  "niche": "marketing digital",
  "location": {"country": null, "region": "Latinoamérica", "city": null},
  "target_audience": "B2B",
  "language": "es",
  "must_have": [],
  "must_not": ["crm"],
  "validation_indicators": ["nuestros servicios", "case studies", "casos de éxito", "agencia de marketing", "presupuesto", "auditoría gratuita", "equipo"],
  "exclusion_indicators": ["qué es marketing digital", "guía", "wikipedia", "comparativa de agencias", "top agencias"],
  "confidence": 0.85,
  "analysis_notes": "Sector agencia con negación de tecnología (categoría CRM); geografía regional sin país concreto",
  "search_strategy": "señales de agencia B2B + sector marketing digital + geo LATAM (.mx, .co, .ar) + sin huella de CRM, excluir contenido informativo",
  "sector_keywords": ["agencia marketing digital", "performance marketing", "media buying", "SEO/SEM", "estrategia digital", "growth marketing"]
}

EJEMPLO 3
Entrada: "clínicas dentales en Madrid con web propia que tengan reservas online"
Salida:
{
  "prompt_depurado": "clínicas dentales en Madrid con web propia y sistema de reservas online",
  "business_type": "servicio_local",
  "product_category": null,
  "service_type": "odontología",
  "niche": "clínica dental",
  "location": {"country": "ES", "region": "Madrid", "city": "Madrid"},
  "target_audience": "B2C",
  "language": "es",
  "must_have": [],
  "must_not": [],
  "validation_indicators": ["pedir cita", "reservar cita", "/contacto", "tratamientos", "implantes", "ortodoncia", "clínica dental", "doctor", "doctora"],
  "exclusion_indicators": ["qué es", "wikipedia", "directorio de clínicas", "doctoralia", "mejores clínicas", "ranking", "comparativa"],
  "confidence": 0.9,
  "analysis_notes": "Negocio local con widget de reservas; geo Madrid; descartar directorios verticales como Doctoralia",
  "search_strategy": "negocios locales con presencia web propia + widget de reservas + geo Madrid, excluir directorios verticales (Doctoralia, Top doctors) y rankings",
  "sector_keywords": ["clínica dental", "odontología", "ortodoncia invisible", "implantes dentales", "estética dental", "Invisalign", "endodoncia"]
}

═══════════════════════════════════════════════════════════════════════
FORMATO DE SALIDA
═══════════════════════════════════════════════════════════════════════
JSON ESTRICTO, sin comentarios, sin texto antes ni después, sin bloques \
markdown. Empieza con `{` y termina con `}`.\
"""

_ANALYSIS_USER_TEMPLATE = """\
PROMPT DEL USUARIO:
\"\"\"{prompt}\"\"\"

Devuelve EXACTAMENTE este objeto JSON con los datos extraídos del \
prompt. Si un campo no tiene información, devuelve null o lista vacía \
(NO lo inventes).

{{
  "prompt_depurado":   "string · versión clara y unívoca del prompt",
  "business_type":     "ecommerce | saas | agencia | consultoria | marketplace | directorio | blog | app | plataforma | servicio_local | corporativa | portfolio | otro",
  "product_category":  "string o null",
  "service_type":      "string o null",
  "niche":             "string o null",
  "location": {{
    "country":         "código ISO-3166-1 alfa-2 o null",
    "region":          "string o null",
    "city":            "string o null"
  }},
  "target_audience":   "B2B | B2C | ambos | null",
  "language":          "es | en | ambos",
  "must_have":         ["lista de strings · tecnologías/atributos OBLIGATORIOS, nombres canónicos"],
  "must_not":          ["lista de strings · tecnologías/atributos PROHIBIDOS, nombres canónicos"],
  "validation_indicators": [
    "cadenas HTML CONCRETAS que CONFIRMAN que una web encaja (textos UI, clases CSS, terminología del sector)"
  ],
  "exclusion_indicators":  [
    "cadenas HTML CONCRETAS que DESCARTAN una web (informativos, directorios, comparativas, rankings)"
  ],
  "confidence":        0.0,
  "analysis_notes":    "una frase con la estrategia clave (sector, tecnologías críticas, qué excluir)",
  "search_strategy":   "UNA frase con el ángulo de ataque OSINT que seguiría el generador de queries",
  "sector_keywords":   ["3 a 8 términos REALES del argot del sector — vocabulario que solo usa un profesional del nicho"]
}}\
"""


# ─────────────────────────────────────────────────────────────────────────────
#  PROMPT — Generación de queries Google
# ─────────────────────────────────────────────────────────────────────────────

_QUERIES_SYSTEM_PROMPT = """\
Eres "Query Strategist", un experto OSINT y lead-gen que diseña dorks de \
Google quirúrgicos para descubrir webs de empresas reales (NO artículos, \
NO directorios, NO comparativas, NO rankings, NO contenido informativo).

Tu único trabajo es generar las QUERIES — no analizas semántica, no \
clasificas, no devuelves metadata. Solo queries listas para Serper.

═══════════════════════════════════════════════════════════════════════
PRINCIPIOS
═══════════════════════════════════════════════════════════════════════

  1. INTENCIÓN ÚNICA: encontrar webs que SON el negocio descrito, no
     webs que HABLAN sobre él. Cada query debe optimizar ese filtro.

  2. ESTRUCTURA DE DIVERSIDAD obligatoria (15 queries, NI más NI menos):

     · 4 queries QUIRÚRGICAS (alta especificidad, operadores fuertes,
       atacan un footprint claro o frase exacta del sector).
     · 5 queries de FOOTPRINT TÉCNICO o SECTOR (slang real del nicho,
       generator/powered-by, terminología que solo usa un profesional
       — no un periodista).
     · 4 queries COMERCIALES (señales de empresa real: pricing,
       presupuesto, contacto, equipo, "trabaja con nosotros",
       free trial, request demo).
     · 2 queries AMPLIAS (long-tail / catch-all que pillen lo que las
       específicas no pillaron, sin operadores agresivos).

  3. OPERADORES Google permitidos (usa al menos 7 de 15 con operadores):

       intitle:"…"     · inurl:"…"   · site:tld
       "frase exacta"  · OR          · AND (implícita; evita la palabra)
       -exclusión      · filetype:   · cache: (raramente útil)

     PROHIBIDOS (Google ya no los soporta o son ruido):
       allintitle:, allinurl:, link:, inanchor: en queries amplias.

  4. NEGACIONES (must_not) — críticas:
     · NUNCA menciones positivamente una tecnología que esté en
       must_not. Usa "-shopify" si quieres filtrarlas explícitamente,
       o busca alternativas directamente (p.ej. "woocommerce").

  5. POSITIVOS (must_have) — críticas:
     · Al menos 3 queries deben mencionar/atacar un must_have (p.ej.
       footprint "powered by Shopify" o inurl:/shop o intitle:Klaviyo).

  6. GEO / IDIOMA:
     · Si el análisis trae location o language, al menos 2 queries
       deben localizarla (TLD .es / .com.mx / .com.ar, ciudad, slang
       regional). Si NO hay ubicación, NO inventes ninguna.

  7. EXCLUSIONES INFORMATIVAS — defensivas (al menos 2 queries):
     · Añade exclusiones del tipo:
         -blog -"qué es" -wikipedia -"guía" -"comparativa"
         -"top 10" -ranking -definición -tutorial
     · Especialmente importante si el nicho tiene mucho contenido
       editorial (ej. clínica dental, marketing digital, fintech).

  8. CALIDAD DE LA QUERY:
     · Cada query debe pegarse tal cual en Google y devolver
       resultados de webs reales.
     · Mínimo 3 palabras útiles. Máximo ~20-25 palabras (Google
       trunca >32).
     · NO duplicar queries casi-idénticas (ej. "tienda zapatos" y
       "tiendas de zapatos" cuentan como una sola).
     · NO incluyas instrucciones, comentarios, numeración ni
       prefijos tipo "Query 1:" dentro del array.

═══════════════════════════════════════════════════════════════════════
EJEMPLO TRABAJADO — para que veas el nivel esperado
═══════════════════════════════════════════════════════════════════════

ENTRADA:
  prompt_depurado: "tienda online de bicicletas eléctricas en Barcelona, plataforma Shopify, no Wix"
  business_type: "ecommerce"
  niche: "movilidad urbana eléctrica"
  location: {"country":"ES","region":"Cataluña","city":"Barcelona"}
  must_have: ["Shopify"]
  must_not: ["Wix"]
  search_strategy: "footprint de Shopify + slang ebike + geo Barcelona/España, excluir blogs/rankings"
  sector_keywords: ["e-bike", "bicicleta urbana", "asistencia eléctrica", "ciclismo eléctrico"]

SALIDA (15 queries diversas, sin Wix mencionado en positivo):
  1. intitle:"tienda" "bicicletas eléctricas" Barcelona
  2. "powered by Shopify" "e-bike" site:.es
  3. inurl:"/products/" "bicicleta eléctrica" Barcelona
  4. "ebike" "añadir al carrito" "Barcelona" OR "Cataluña"
  5. "asistencia eléctrica" tienda online bicicletas España
  6. "ciclismo urbano" Shopify Barcelona -blog -wikipedia
  7. "MTB eléctrica" "envío" "stock" Barcelona
  8. bicicletas eléctricas Barcelona "contacto" "showroom"
  9. "comprar e-bike" Barcelona OR Madrid -"qué es" -"guía"
  10. inurl:"/collections/" e-bike "Cataluña"
  11. "checkout" "bicicleta eléctrica" site:.es
  12. tienda bicicletas eléctricas Barcelona -ranking -"top 10" -comparativa
  13. "powered by Shopify" "ebike" OR "e-bike" Cataluña
  14. ebike "envío 24h" OR "envío gratis" Barcelona
  15. tienda online bicicletas eléctricas Barcelona

Fíjate cómo NINGUNA query menciona Wix (must_not), 3+ atacan Shopify
(must_have), 4 llevan -exclusiones contra contenido informativo, hay
slang del sector (e-bike, MTB eléctrica, asistencia eléctrica), y
geo Barcelona/Cataluña aparece en varias.
═══════════════════════════════════════════════════════════════════════

FORMATO DE SALIDA — JSON estricto: { "search_queries": [ ... 15 strings ... ] }\
"""

_QUERIES_USER_TEMPLATE = """\
PROMPT DEL USUARIO (original):
\"\"\"{prompt}\"\"\"

ANÁLISIS ESTRUCTURADO del prompt (úsalo para anclar las queries):
{analysis_block}

Genera EXACTAMENTE 15 queries listas para Serper / Google siguiendo la \
estructura de diversidad (4 quirúrgicas, 5 footprint/sector, 4 \
comerciales, 2 amplias) descrita en el sistema. RESPETA las negaciones \
(must_not) — no las menciones en positivo. USA los nombres canónicos \
de must_have al atacar footprint. INCLUYE geo/idioma si el análisis lo \
trae, NO inventes ubicación si no la trae.

FORMATO de respuesta (JSON, sin nada más, sin markdown):
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

        Flujo:

          1. Lanza el análisis estructurado (TASK_PROMPT_ANALYSIS) y, en
             paralelo, el routing de Fase 2 si está activo (también
             TASK_PROMPT_ANALYSIS pero distintos prompts).
          2. Cuando el análisis termina, lanza la generación de queries
             (TASK_QUERY_GENERATION) con el contexto completo del
             análisis — así las queries son MUCHO más precisas que
             cuando antes corrían a ciegas en paralelo con el análisis.
          3. Post-procesa las queries para garantizar:
               · que respetan must_not (filtra las que mencionen tech
                 prohibida en positivo),
               · que no haya duplicadas casi-idénticas,
               · y deduplica también validation/exclusion_indicators.

        Si ``precision_routing=True`` (por defecto), las dos decisiones
        de Fase 2 (Tech Scanner y PageSpeed) van en paralelo al
        análisis. En modo rápido se desactiva para no añadir latencia.
        """
        if not user_prompt or not user_prompt.strip():
            return _local_analyze(user_prompt or "")

        # ── Paso 1: análisis + routing en paralelo ───────────────────
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            fut_analysis = pool.submit(self._run_analysis, user_prompt)
            fut_routing  = (
                pool.submit(self._run_precision_routing, user_prompt)
                if precision_routing else None
            )

            analysis_data, analysis_provider = fut_analysis.result()
            routing = fut_routing.result() if fut_routing else None

        # ── Paso 2: generación de queries CON contexto del análisis ──
        # Sequential, no parallel, porque la calidad del prompt depende
        # del análisis. Coste: +1 llamada (≈1-2s) de latencia. Beneficio:
        # queries dramáticamente más precisas (slang del sector, geo,
        # must_have/must_not aplicados correctamente).
        queries_list, queries_provider = self._run_queries(
            user_prompt, analysis_data=analysis_data,
        )

        # ── Construir SearchIntent ───────────────────────────────────
        if not analysis_data:
            print(
                "[AIInterpreter] Análisis IA falló — usando análisis "
                "local de emergencia"
            )
            intent = _local_analyze(user_prompt)
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

        # ── Post-procesado de queries e indicadores ──────────────────
        intent.search_queries = _post_process_queries(
            intent.search_queries,
            must_not=intent.must_not,
            sector_keywords=_extract_sector_keywords(analysis_data),
            target_count=15,
        )
        intent.validation_indicators = _dedupe_keep_order(
            intent.validation_indicators
        )
        intent.exclusion_indicators = _dedupe_keep_order(
            intent.exclusion_indicators
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

    def _run_queries(
        self,
        user_prompt: str,
        *,
        analysis_data: Optional[Dict[str, Any]] = None,
    ) -> tuple:
        """
        Llama a la cadena TASK_QUERY_GENERATION para producir 15 queries.

        Si ``analysis_data`` no es None, se serializa como bloque de
        contexto y se pasa al Query Strategist. Esto convierte el
        prompt de "ciego" a "anclado en datos estructurados", lo que
        sube drásticamente la calidad de las queries.
        """
        analysis_block = _format_analysis_block(analysis_data)
        msg = _QUERIES_USER_TEMPLATE.format(
            prompt=user_prompt[:2000],
            analysis_block=analysis_block,
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


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers nuevos: contexto del análisis y post-procesado de queries
# ─────────────────────────────────────────────────────────────────────────────

def _format_analysis_block(analysis_data: Optional[Dict[str, Any]]) -> str:
    """
    Serializa los campos del análisis para que el Query Strategist los
    use como contexto. Si no hay análisis, devuelve un placeholder.
    Formato deliberadamente legible (no JSON puro) para que el modelo
    lo absorba mejor.
    """
    if not analysis_data:
        return "(no disponible — tira solo del prompt del usuario)"

    parts: List[str] = []
    pd = analysis_data.get("prompt_depurado") or ""
    if pd:
        parts.append(f"  prompt_depurado: {pd}")

    bt = analysis_data.get("business_type")
    if bt:
        parts.append(f"  business_type:   {bt}")

    for key in ("product_category", "service_type", "niche"):
        v = analysis_data.get(key)
        if v:
            parts.append(f"  {key:<16} {v}")

    loc = analysis_data.get("location") or {}
    if isinstance(loc, dict) and any(loc.values()):
        country = loc.get("country") or "?"
        region  = loc.get("region")  or "?"
        city    = loc.get("city")    or "?"
        parts.append(f"  location:        country={country} · region={region} · city={city}")

    ta = analysis_data.get("target_audience")
    if ta:
        parts.append(f"  target_audience: {ta}")

    lang = analysis_data.get("language")
    if lang:
        parts.append(f"  language:        {lang}")

    mh = analysis_data.get("must_have") or []
    if isinstance(mh, list) and mh:
        parts.append(f"  must_have:       {mh}")

    mn = analysis_data.get("must_not") or []
    if isinstance(mn, list) and mn:
        parts.append(f"  must_not:        {mn}")

    vi = analysis_data.get("validation_indicators") or []
    if isinstance(vi, list) and vi:
        parts.append(f"  validation_indicators: {vi[:10]}")

    ei = analysis_data.get("exclusion_indicators") or []
    if isinstance(ei, list) and ei:
        parts.append(f"  exclusion_indicators:  {ei[:10]}")

    strat = analysis_data.get("search_strategy") or ""
    if strat:
        parts.append(f"  search_strategy: {strat}")

    sk = analysis_data.get("sector_keywords") or []
    if isinstance(sk, list) and sk:
        parts.append(f"  sector_keywords: {sk}")

    return "\n".join(parts) if parts else "(análisis vacío)"


def _extract_sector_keywords(analysis_data: Optional[Dict[str, Any]]) -> List[str]:
    """Saca la lista sector_keywords si existe, normalizada."""
    if not analysis_data:
        return []
    raw = analysis_data.get("sector_keywords") or []
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if isinstance(x, str) and x.strip()]


def _dedupe_keep_order(items: List[Any]) -> List[Any]:
    """Quita duplicados (case-insensitive) preservando el orden original."""
    out: List[Any] = []
    seen: set = set()
    for it in items or []:
        key = str(it).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


# Stopwords ES + EN que NO discriminan una query de otra. Las quitamos en
# la forma canónica para que "tienda online DE zapatos" y "tienda online
# zapatos" se detecten como la misma query.
_STOPWORDS_FOR_DEDUP = frozenset({
    # Español
    "de", "del", "la", "el", "los", "las", "un", "una", "unos", "unas",
    "y", "o", "u", "que", "en", "con", "para", "por", "al", "a", "lo",
    # Inglés
    "of", "the", "a", "an", "and", "or", "to", "for", "in", "on", "with",
    "from", "by",
})


def _normalize_query(q: str) -> str:
    """
    Reduce una query a su forma canónica para detectar near-duplicados.

    Estrategia:
      · Lowercase.
      · Quita comillas y puntuación.
      · Quita los OPERADORES (intitle:, inurl:, site:, …) — solo la
        intención semántica importa.
      · Quita stopwords cortas (de, la, el, of, the, …).
      · Ordena tokens alfabéticamente y deduplica.

    Resultado: dos queries con el mismo conjunto de tokens significativos
    (ignorando orden, operadores y stopwords) se consideran duplicadas.
    """
    s = q.lower()
    s = re.sub(r"[\"'`]", " ", s)
    s = re.sub(r"\b(intitle|inurl|site|filetype|cache|or|and):", " ", s)
    s = re.sub(r"[^\w\sáéíóúñü-]", " ", s)
    tokens: List[str] = []
    for t in s.split():
        if len(t) <= 2:
            continue
        if t in _STOPWORDS_FOR_DEDUP:
            continue
        tokens.append(t)
    return " ".join(sorted(set(tokens)))


def _query_violates_must_not(q: str, must_not: List[str]) -> bool:
    """
    True si la query menciona en POSITIVO una tecnología de must_not.
    "Positivo" = aparece sin el prefijo "-" (la sintaxis Google para
    EXCLUIR). Si aparece como "-shopify" se considera ok (es un filtro).
    """
    if not must_not:
        return False
    q_lower = " " + q.lower() + " "
    for tech in must_not:
        if not isinstance(tech, str) or not tech.strip():
            continue
        t = tech.strip().lower()
        if not t:
            continue
        # Si aparece como "-tech" o "-tech.com" lo consideramos OK
        # (exclusión Google legítima).
        if f" -{t}" in q_lower or f"-{t}" in q_lower.replace(" ", ""):
            continue
        # Pero si aparece en positivo (sin "-" delante), violación.
        if re.search(rf"(?<![\w\-]){re.escape(t)}(?![\w])", q_lower):
            return True
    return False


def _post_process_queries(
    queries: List[str],
    *,
    must_not: Optional[List[str]] = None,
    sector_keywords: Optional[List[str]] = None,
    target_count: int = 15,
) -> List[str]:
    """
    Post-procesa la lista de queries para garantizar calidad y respeto
    estricto a las reglas:

      1. Quita prefijos de instrucción residuales ('Query 1:', 'Ejemplo:'...).
      2. Filtra queries que mencionen must_not en positivo.
      3. Quita near-duplicados por forma canónica (mismo conjunto de
         tokens ignorando operadores y orden).
      4. Limita a target_count.

    No PADDING: si la IA dio menos de target_count queries válidas,
    devolvemos lo que haya. Mejor pocas y buenas que muchas con ruido.
    """
    if not queries:
        return []

    mn = list(must_not or [])

    seen_canonical: set = set()
    out: List[str] = []

    for q in queries:
        if not isinstance(q, str):
            continue
        s = q.strip().strip("`'\"")
        if len(s) < 4:
            continue
        # Filtro #1: prefijo de instrucción
        low = s.lower()
        if any(low.startswith(p) for p in _SKIP_QUERY_PREFIXES):
            continue
        # Filtro #2: must_not en positivo
        if _query_violates_must_not(s, mn):
            continue
        # Filtro #3: near-duplicado
        canonical = _normalize_query(s)
        if not canonical or canonical in seen_canonical:
            continue
        seen_canonical.add(canonical)
        out.append(s)
        if len(out) >= target_count:
            break

    return out


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

# OJO: las versiones anteriores usaban un lookahead con "y" sin word
# boundary, lo que rompía "Shopify" capturándolo como "Shopif" (la `y`
# final del nombre era confundida con la conjunción española). Ahora
# capturamos UNA palabra (puede llevar guiones internos y opcionalmente
# un TLD .com / .io) y dejamos que el post-procesado normalice.
_TECH_TOKEN = r"[a-zA-Z][a-zA-Z0-9_\-]*(?:\.[a-zA-Z]{2,5})?"

_TECH_NEGATIONS = re.compile(
    r'\b(?:sin|no|without|excluir|evitar|que\s+no\s+use[n]?|que\s+no\s+ten[ga]+)\s+'
    r'(' + _TECH_TOKEN + ')',
    re.IGNORECASE,
)
_TECH_REQUIRED = re.compile(
    r'\b(?:con|with|que\s+use[n]?|que\s+ten[ga]+|usando)\s+'
    r'(' + _TECH_TOKEN + ')',
    re.IGNORECASE,
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
