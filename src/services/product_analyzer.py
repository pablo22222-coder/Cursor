"""
ProductAnalyzer — Convierte la descripción de un producto/servicio en un
prompt de prospección que describe la web ideal que podría comprarlo.

Razonamiento que ejecuta la IA (en tres pasos, internos, no se devuelven al
usuario; solo se devuelve el prompt final):

  PASO 1 — Comprender el producto:
      Qué hace, qué problema resuelve, si es B2B/B2C, si es físico/digital/
      SaaS/servicio/formación, dependencias técnicas evidentes, etc.

  PASO 2 — Definir la audiencia que lo compraría:
      Tipo de negocio que lo necesita, sector aproximado, tamaño/modelo de
      negocio y el dolor que el producto le resuelve.

  PASO 3 — Describir la web ideal del comprador:
      Una descripción BUENA pero BÁSICA del tipo de web que encajaría como
      cliente. Lo bastante amplia para que existan muchas webs reales que
      cumplan, lo bastante orientada para que sean compradores plausibles.
      Si la descripción es demasiado precisa, no se encontrarán webs.

Flujo completo en el sistema:
  1. El usuario describe su producto (ej: "Vendo software de facturación SaaS
     para pymes españolas, precio 49€/mes, integración con contabilidad").
  2. ProductAnalyzer hace los tres pasos anteriores con la IA y genera un
     único prompt de prospección, p.ej.:
       "asesoría o gestoría contable que trabaje con pymes en España"
  3. Ese prompt se olvida de la descripción del producto y se usa
     directamente como si el usuario lo hubiera escrito a mano.
  4. AIInterpreter.interpret() toma ese prompt y genera las queries de Serper.

La descripción del producto NUNCA llega al buscador ni al validador.
Solo el prompt generado viaja por el resto del pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.services.ai_manager import get_ai_manager


# ─────────────────────────────────────────────────────────────────────────────
#  PROMPT EXPERTO
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
Eres un experto en ventas B2B y prospección comercial con 15 años de experiencia \
identificando el perfil de cliente ideal (ICP) para cualquier producto o servicio.

Tu tarea, dada la descripción de un producto/servicio que vende un vendedor, es \
generar UN ÚNICO prompt de búsqueda que describa la WEB IDEAL que podría comprarlo.

PIENSA INTERNAMENTE EN TRES PASOS (no muestres este razonamiento, solo el resultado):

PASO 1 — Comprende el producto:
  ¿Qué hace exactamente? ¿Qué problema resuelve? ¿Es B2B o B2C? ¿Es físico, \
  digital, software, formación, servicio profesional...? ¿Hay dependencias \
  técnicas evidentes (p.ej. plugin para Shopify ⇒ tienda Shopify)?

PASO 2 — Define la audiencia que lo compraría:
  ¿Qué tipo de negocio o web NECESITA este producto? Sector, tamaño aproximado, \
  modelo de negocio, qué dolor sufre que este producto le resuelve. \
  Si el producto está claramente atado a una región/idioma, tenlo en cuenta; \
  si no, NO inventes una localización.

PASO 3 — Describe la web ideal del comprador:
  Convierte esa audiencia en una descripción SENCILLA y GENÉRICA de la web del \
  comprador, lo bastante amplia para que existan muchas webs reales que encajen \
  pero lo bastante orientada para que sean compradores plausibles.

REGLAS DEL PROMPT FINAL:
1. Describe la WEB DEL COMPRADOR, NO el producto del vendedor. Nunca nombres el \
   producto, marca, precio ni tecnología propia del vendedor.
2. Tiene que ser una descripción BUENA pero BÁSICA: el objetivo es que existan \
   muchas webs reales que cumplan el perfil. Si la descripción es demasiado \
   precisa o restrictiva, no encontraremos nada.
3. Prefiere una categoría sectorial amplia ("agencia de marketing digital", \
   "tienda online de moda", "clínica dental", "asesoría fiscal de pymes") antes \
   que un nicho ultra-estrecho. NO uses combinaciones de varios filtros muy \
   específicos a la vez (sector + tamaño + tecnología + región + sub-nicho); \
   eso colapsa el universo de búsqueda.
4. Solo añade un filtro extra (tecnología actual, región, modelo) si es \
   IMPRESCINDIBLE para que el comprador tenga sentido (p.ej. plugin Shopify \
   ⇒ "tienda online con Shopify"). Si no es imprescindible, déjalo fuera.
5. Si el producto excluye cierto tipo de webs (p.ej. "no para Shopify"), puedes \
   añadir "sin [tecnología]" pero solo cuando sea claramente un excluyente.
6. Lenguaje natural, en español, como lo escribiría un comercial buscando leads.
7. Longitud objetivo: entre 8 y 20 palabras. Cortito y limpio.

EJEMPLOS:
  Producto: "Plugin de Shopify para recuperar carritos abandonados, 29€/mes"
  → Prompt: "tienda online con Shopify que venda productos físicos al consumidor"

  Producto: "Software CRM para agencias de marketing digital, 99€/mes/usuario"
  → Prompt: "agencia de marketing digital con equipo comercial propio"

  Producto: "Servicio de diseño gráfico para marcas de moda de lujo"
  → Prompt: "marca de moda premium o lujo con tienda online"

  Producto: "API de verificación de emails para plataformas de email marketing"
  → Prompt: "plataforma de email marketing o herramienta de marketing automation"

  Producto: "Formación en ventas para equipos comerciales de empresas B2B"
  → Prompt: "empresa B2B de tecnología o servicios con equipo comercial propio"

  Producto: "App de reservas online para restaurantes"
  → Prompt: "restaurante con web propia que acepte reservas"

RESPONDE ÚNICAMENTE con el prompt resultante, sin comillas, sin explicaciones, \
sin prefijos como 'Prompt:' ni el razonamiento de los tres pasos. \
Solo el texto del prompt listo para usar.\
"""

_USER_TEMPLATE = """\
Descripción del producto/servicio del vendedor:
{product_description}

Sigue internamente los tres pasos (entender el producto → definir la audiencia → \
describir la web ideal del comprador) y devuelve SOLO el prompt final, lo \
bastante genérico para que existan muchas webs reales que cumplan el perfil.\
"""


# ─────────────────────────────────────────────────────────────────────────────
#  DATACLASS DE RESULTADO
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ProductAnalysis:
    """Resultado del análisis de producto."""
    product_description: str     # Descripción original del usuario (se descarta después)
    prospect_prompt: str         # Prompt generado para el buscador
    provider_used: str = "local"
    confidence: float = 0.8


# ─────────────────────────────────────────────────────────────────────────────
#  ANALIZADOR PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

class ProductAnalyzer:
    """
    Convierte la descripción de un producto en un prompt de prospección.

    Uso:
        analysis = ProductAnalyzer().analyze("Vendo software de facturación...")
        # analysis.prospect_prompt → "gestoría o asesoría contable sin software..."
        # Pasar analysis.prospect_prompt a AIInterpreter.interpret()
    """

    def __init__(self):
        self._ai = get_ai_manager()

    def analyze(self, product_description: str) -> ProductAnalysis:
        """
        Analiza el producto y devuelve un ProductAnalysis con el prospect_prompt.
        Si la IA falla, usa una heurística local de emergencia.
        """
        if not product_description or not product_description.strip():
            raise ValueError("La descripción del producto no puede estar vacía.")

        user_msg = _USER_TEMPLATE.format(product_description=product_description.strip())

        response = self._ai.complete(
            prompt=user_msg,
            system_prompt=_SYSTEM_PROMPT,
        )

        if response.success and response.text.strip():
            prospect_prompt = _clean_prompt(response.text)
            print(
                f"[ProductAnalyzer] '{product_description[:50]}...' → "
                f"'{prospect_prompt}' (via {response.provider})"
            )
            return ProductAnalysis(
                product_description=product_description,
                prospect_prompt=prospect_prompt,
                provider_used=response.provider,
                confidence=0.9,
            )

        # Fallback local
        print("[ProductAnalyzer] IA no disponible — usando análisis local")
        fallback = _local_analyze(product_description)
        return ProductAnalysis(
            product_description=product_description,
            prospect_prompt=fallback,
            provider_used="local",
            confidence=0.4,
        )


# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _clean_prompt(text: str) -> str:
    """Limpia el texto devuelto por la IA: elimina comillas, prefijos, markdown.

    Si la IA devolvió varias líneas (p.ej. expuso por error sus tres pasos de
    razonamiento), nos quedamos con la última línea no vacía, que es donde el
    system prompt indica que esté el prompt final.
    """
    import re
    text = (text or "").strip()
    # Quitar fences markdown completos al inicio/fin
    text = re.sub(r'^```[a-zA-Z0-9]*\s*', '', text)
    text = re.sub(r'\s*```$', '', text).strip()
    # Si hay varias líneas, quedarnos con la última no vacía
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if lines:
        text = lines[-1]
    # Eliminar prefijos como "Prompt:", "→", "-", "Resultado:"
    text = re.sub(
        r'^(?:prompt\s*[:→\-]?\s*|resultado\s*[:→\-]?\s*|→\s*|-\s*|\*\s*)',
        '', text, flags=re.IGNORECASE
    ).strip()
    # Eliminar comillas envolventes
    text = re.sub(r'^["\'](.+)["\']$', r'\1', text).strip()
    # Limitar longitud
    if len(text) > 200:
        text = text[:200].rsplit(' ', 1)[0]
    return text


def _local_analyze(description: str) -> str:
    """
    Heurística de emergencia cuando la IA no está disponible.
    Intenta construir un prompt básico a partir de palabras clave.
    """
    import re
    desc = description.lower()

    # Detectar sector objetivo
    sectors = {
        "ecommerce":  ["tienda", "ecommerce", "venta online", "shopify", "woocommerce"],
        "agencia":    ["agencia", "marketing", "publicidad", "diseño", "creative"],
        "saas":       ["saas", "software", "plataforma", "herramienta", "app"],
        "pyme":       ["pyme", "empresa", "negocio", "autónomo"],
        "restaurante":["restaurante", "bar", "hostelería", "comida"],
        "clinica":    ["clínica", "médico", "salud", "dental", "fisio"],
    }

    detected_sector = "empresa"
    for sector, keywords in sectors.items():
        if any(kw in desc for kw in keywords):
            detected_sector = sector
            break

    # Detectar localización
    location = ""
    loc_patterns = re.findall(r'\b(españa|spain|madrid|barcelona|mexico|latam|latinoamérica)\b', desc)
    if loc_patterns:
        location = f" en {loc_patterns[0]}"

    return f"{detected_sector} que necesite solución como la descrita{location}"


# ─────────────────────────────────────────────────────────────────────────────
#  Función de conveniencia
# ─────────────────────────────────────────────────────────────────────────────

def analyze_product(product_description: str) -> ProductAnalysis:
    """Función de conveniencia."""
    return ProductAnalyzer().analyze(product_description)
