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
Eres un experto en ventas B2B y prospección comercial con 15 años de experiencia \
en identificar el perfil de cliente ideal (ICP) para cualquier producto o servicio.

Tu tarea es analizar la descripción de un producto o servicio que te va a dar un \
vendedor y generar UN ÚNICO prompt de búsqueda que describa la web ideal que \
podría estar interesada en comprarlo o contratarlo.

REGLAS CRÍTICAS:
1. El prompt debe describir la WEB DEL COMPRADOR, no el producto del vendedor.
2. Piensa: ¿qué tipo de empresa o web NECESITA este producto? ¿Cuál es su sector, \
   tamaño, tecnología actual, problema que tiene?
3. El prompt debe ser específico y accionable para encontrar esas webs en Google.
4. NO menciones el producto del vendedor en el prompt resultante.
5. El prompt debe estar en lenguaje natural, como si un comercial experto buscara \
   leads en Google.
6. Incluye detalles sobre el tipo de web: ¿es ecommerce? ¿agencia? ¿SaaS? ¿empresa \
   de servicios? ¿tiene tecnología X? ¿está en una región concreta?
7. Si el producto excluye cierto tipo de webs (ej: "no para Shopify"), añade \
   "sin [tecnología]" al prompt.
8. El prompt debe tener entre 10 y 25 palabras, conciso y preciso.

EJEMPLOS:
  Producto: "Plugin de Shopify para recuperar carritos abandonados, 29€/mes"
  → Prompt: "ecommerce con shopify que venda productos físicos en España"

  Producto: "Software CRM para agencias de marketing digital, 99€/mes/usuario"
  → Prompt: "agencia de marketing digital sin CRM propio en España o Latinoamérica"

  Producto: "Servicio de diseño gráfico para marcas de moda de lujo"
  → Prompt: "marca de moda premium o lujo con identidad visual desactualizada"

  Producto: "API de verificación de emails para plataformas de email marketing"
  → Prompt: "plataforma SaaS de email marketing o herramienta de marketing automation"

  Producto: "Formación en ventas para equipos comerciales de empresas B2B"
  → Prompt: "empresa B2B con equipo comercial propio en sector tecnología o servicios"

RESPONDE ÚNICAMENTE con el prompt resultante, sin comillas, sin explicaciones, \
sin prefijos como 'Prompt:'. Solo el texto del prompt listo para usar.\
"""

_USER_TEMPLATE = """\
Descripción del producto/servicio del vendedor:
{product_description}

Genera el prompt de prospección que describa la web ideal que podría comprarlo.\
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
