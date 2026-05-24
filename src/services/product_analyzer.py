"""
ProductAnalyzer — Convierte la descripción de un producto/servicio en un
prompt de prospección que describe la web ideal que podría comprarlo.

Flujo:
  1. El usuario describe su producto (ej: "Vendo software de facturación SaaS
     para pymes españolas, precio 49€/mes, integración con contabilidad")
  2. La IA analiza el producto y genera un prompt de prospección:
     "agencia de contabilidad o gestoría que gestione facturas de pymes en
      España, sin software de facturación propio"
  3. Ese prompt se olvida de la descripción del producto y se usa
     directamente como si el usuario lo hubiera escrito a mano.
  4. AIInterpreter.interpret() toma ese prompt y genera las queries de Serper.

La descripción del producto NUNCA llega al buscador ni al validador.
Solo el prompt generado viaja por el resto del pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.services.ai_manager import complete_for_task
from src.services.task_chains import TASK_PROMPT_ANALYSIS


# ─────────────────────────────────────────────────────────────────────────────
#  PROMPT EXPERTO
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
Eres un experto en ventas B2B y prospección comercial con 15 años \
identificando el perfil de cliente ideal (ICP) para cualquier producto \
o servicio. Tu cliente es un vendedor que quiere encontrar leads.

Tu tarea: analizar la descripción de un producto/servicio y devolver UN \
ÚNICO prompt de búsqueda que describa la WEB IDEAL que podría comprarlo.

═══════════════════════════════════════════════════════════════════════
RAZONAMIENTO MENTAL (no lo muestres, solo úsalo para construir el prompt)
═══════════════════════════════════════════════════════════════════════

  1. Entender el producto:
       · ¿Qué hace exactamente? ¿Qué problema resuelve?
       · ¿B2B o B2C?
       · ¿Es físico, digital, software, servicio profesional, formación,
         infoproducto?
       · ¿Hay dependencias técnicas evidentes? (plugin Shopify ⇒ tienda
         Shopify; integración con HubSpot ⇒ usuario de HubSpot;
         conector WooCommerce ⇒ ecommerce WordPress.)

  2. Definir la audiencia compradora:
       · ¿Qué tipo de negocio o web NECESITA esto?
       · ¿Sector? ¿Tamaño aproximado? ¿Modelo de negocio?
       · ¿Qué dolor tiene que esto le resuelve?
       · ¿Hay región/idioma implícito (precio en €, mención a España,
         producto en inglés...)?

  3. Convertir la audiencia en una descripción de WEB:
       · Una descripción BUENA pero BÁSICA del tipo de web.
       · Lo bastante amplia para que existan muchas webs reales que
         encajen, lo bastante orientada para que sean compradores
         plausibles.
       · Si la descripción es DEMASIADO precisa, no encontrarás nada.

═══════════════════════════════════════════════════════════════════════
REGLAS DEL PROMPT FINAL
═══════════════════════════════════════════════════════════════════════

  1. DESCRIBE LA WEB DEL COMPRADOR, no el producto del vendedor.
  2. NUNCA nombres el producto, la marca, el precio ni la tecnología
     PROPIA del vendedor. Solo características del COMPRADOR.
  3. Lenguaje natural, en español (salvo que el producto sea
     claramente para mercado anglosajón → entonces inglés).
  4. Longitud: 8 a 20 palabras. Cortito y limpio.
  5. Si hay dependencia técnica IMPRESCINDIBLE del comprador, métela
     (plugin Shopify → "tienda online con Shopify"). Si NO es
     imprescindible, déjalo fuera.
  6. Si el producto EXCLUYE cierto tipo de webs (p.ej. "no para
     plataformas Wix"), añade "sin [tecnología]" SOLO si es un
     excluyente claro.
  7. Region/idioma: solo si el producto lo IMPLICA con claridad
     (precio en €, mención a España/LATAM, idioma del producto, factura
     IVA, etc.). NO inventes geografía.
  8. NO combines más de 2-3 filtros muy específicos a la vez
     (sector + tamaño + tecnología + región + sub-nicho colapsa el
     universo de búsqueda y no encuentras nada).
  9. Audiencia: si está claro B2B o B2C, oriéntalo. Si no, deja
     genérico ("empresa", "negocio", "web").

═══════════════════════════════════════════════════════════════════════
EJEMPLOS (input → output)
═══════════════════════════════════════════════════════════════════════

Producto: "Plugin de Shopify para recuperar carritos abandonados, 29€/mes"
→ "tienda online con Shopify que venda productos físicos al consumidor"

Producto: "Software CRM B2B para agencias de marketing digital, 99€/mes/usuario"
→ "agencia de marketing digital con equipo comercial propio"

Producto: "Servicio de diseño gráfico premium para marcas de moda de lujo"
→ "marca de moda premium o lujo con tienda online"

Producto: "API de verificación de emails para plataformas de email marketing"
→ "plataforma SaaS de email marketing o herramienta de marketing automation"

Producto: "Formación en técnicas de cierre para equipos comerciales B2B"
→ "empresa B2B de tecnología o servicios con equipo comercial propio"

Producto: "App de reservas online y gestión de mesas para restaurantes"
→ "restaurante con web propia que acepte reservas online"

Producto: "Conector que integra WooCommerce con Holded para sincronizar facturas"
→ "tienda online con WooCommerce en España"

Producto: "Servicio de auditoría SEO técnica para sites en WordPress"
→ "empresa o ecommerce con web propia en WordPress"

Producto: "Software de gestión de turnos para clínicas dentales"
→ "clínica dental con web propia"

Producto: "Sistema de fidelización con monedero virtual para tiendas físicas"
→ "tienda local con presencia online (cafetería, panadería, pequeño retail)"

Producto: "Pasarela de pagos optimizada para suscripciones SaaS"
→ "plataforma SaaS con pricing recurrente y checkout propio"

═══════════════════════════════════════════════════════════════════════
SALIDA
═══════════════════════════════════════════════════════════════════════
Responde ÚNICAMENTE con el prompt resultante. SIN comillas, SIN \
explicaciones, SIN prefijos como 'Prompt:' o 'Output:'. Solo el texto \
del prompt listo para usar.\
"""

_USER_TEMPLATE = """\
Descripción del producto/servicio del vendedor:
\"\"\"{product_description}\"\"\"

Sigue mentalmente los tres pasos (producto → audiencia → web compradora) \
y devuelve SOLO el prompt final (8-20 palabras), lo bastante genérico \
para que existan muchas webs reales que cumplan el perfil.\
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
        # ProductAnalyzer no espera JSON sino texto plano (un prompt).
        # Para mantener el contrato OpenAI-compatible y la cadena de
        # fallback unificada, usamos complete_for_task en cada llamada
        # con json_mode=False.
        pass

    def analyze(self, product_description: str) -> ProductAnalysis:
        """
        Analiza el producto y devuelve un ProductAnalysis con el prospect_prompt.
        Si la IA falla, usa una heurística local de emergencia.
        """
        if not product_description or not product_description.strip():
            raise ValueError("La descripción del producto no puede estar vacía.")

        user_msg = _USER_TEMPLATE.format(product_description=product_description.strip())

        response = complete_for_task(
            TASK_PROMPT_ANALYSIS,
            prompt=user_msg,
            system_prompt=_SYSTEM_PROMPT,
            json_mode=False,   # devuelve UNA línea de texto, no JSON
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
    """Limpia el texto devuelto por la IA: elimina comillas, prefijos, markdown."""
    import re
    text = text.strip()
    # Eliminar bloques markdown
    text = re.sub(r'^```.*?```$', '', text, flags=re.DOTALL).strip()
    # Eliminar prefijos como "Prompt:", "→", "-"
    text = re.sub(r'^(?:prompt\s*[:→\-]?\s*|→\s*|-\s*)', '', text, flags=re.IGNORECASE).strip()
    # Eliminar comillas envolventes
    text = re.sub(r'^["\'](.+)["\']$', r'\1', text).strip()
    # Limitar longitud
    if len(text) > 200:
        text = text[:200].rsplit(' ', 1)[0]
    return text or text


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
