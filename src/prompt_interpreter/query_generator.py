"""
Generador avanzado de queries de búsqueda.
Crea queries inteligentes para encontrar webs que SEAN lo buscado, no que hablen de ello.
"""
from typing import List, Dict, Optional
from dataclasses import dataclass


@dataclass
class QueryTemplate:
    """Template para generar queries."""
    pattern: str
    weight: float = 1.0  # Prioridad del template
    description: str = ""


class QueryGenerator:
    """
    Genera queries de búsqueda optimizadas para encontrar negocios reales.
    
    Estrategias:
    1. Queries transaccionales (intención de compra/contratación)
    2. Queries con indicadores de negocio real
    3. Queries con ubicación geográfica
    4. Queries con exclusiones de contenido informativo
    5. Queries de competidores/alternativas
    """
    
    # Templates por tipo de negocio
    ECOMMERCE_TEMPLATES = [
        # Intención de compra directa
        QueryTemplate("comprar {product} online", 1.0, "Intención de compra"),
        QueryTemplate("tienda {product} online", 1.0, "Búsqueda de tienda"),
        QueryTemplate("tienda online de {product}", 1.0, "Búsqueda de tienda"),
        QueryTemplate("{product} shop online", 0.9, "Inglés"),
        QueryTemplate("venta de {product} online", 0.9, "Venta"),
        QueryTemplate("{product} precio", 0.8, "Con precio"),
        QueryTemplate("{product} ofertas", 0.8, "Ofertas"),
        QueryTemplate("{product} envío gratis", 0.7, "Envío gratis"),
        
        # Con indicadores de ecommerce
        QueryTemplate('"{product}" "añadir al carrito"', 0.9, "Indicador carrito"),
        QueryTemplate('"{product}" "comprar ahora"', 0.9, "Indicador compra"),
        QueryTemplate('"{product}" "envío" "precio"', 0.8, "Indicadores múltiples"),
        
        # Por ubicación
        QueryTemplate("tienda {product} españa", 0.8, "España"),
        QueryTemplate("comprar {product} madrid", 0.7, "Madrid"),
        QueryTemplate("tienda {product} barcelona", 0.7, "Barcelona"),
        QueryTemplate("{product} tienda mexico", 0.6, "México"),
        QueryTemplate("{product} store usa", 0.6, "USA"),
        
        # Exclusiones de contenido informativo
        QueryTemplate('{product} tienda -"qué es" -wikipedia -blog', 0.9, "Con exclusiones"),
        QueryTemplate('{product} comprar -"cómo crear" -tutorial -guía', 0.9, "Sin tutoriales"),
        
        # Nichos específicos
        QueryTemplate("mejores tiendas de {product}", 0.7, "Mejores tiendas"),
        QueryTemplate("{product} tienda especializada", 0.7, "Especializada"),
    ]
    
    SAAS_TEMPLATES = [
        # Búsqueda de herramientas
        QueryTemplate("{service} software", 1.0, "Software"),
        QueryTemplate("{service} herramienta online", 1.0, "Herramienta"),
        QueryTemplate("{service} plataforma", 0.9, "Plataforma"),
        QueryTemplate("{service} tool", 0.9, "Tool inglés"),
        QueryTemplate("{service} app", 0.8, "App"),
        
        # Con indicadores de SaaS
        QueryTemplate('"{service}" "prueba gratis"', 0.9, "Trial"),
        QueryTemplate('"{service}" "free trial"', 0.9, "Free trial"),
        QueryTemplate('"{service}" pricing', 0.9, "Pricing"),
        QueryTemplate('"{service}" "planes" "precio"', 0.8, "Planes"),
        QueryTemplate('"{service}" "registrarse"', 0.8, "Registro"),
        
        # Alternativas y comparativas (encuentran competidores reales)
        QueryTemplate("alternativas a {service}", 0.8, "Alternativas"),
        QueryTemplate("{service} vs", 0.7, "Comparativas"),
        QueryTemplate("mejor {service} software 2024", 0.7, "Mejor software"),
        
        # Por caso de uso
        QueryTemplate("{service} para empresas", 0.8, "B2B"),
        QueryTemplate("{service} para pymes", 0.7, "PYMES"),
        QueryTemplate("{service} para startups", 0.7, "Startups"),
        
        # Exclusiones
        QueryTemplate('{service} software -"qué es" -definición -wikipedia', 0.9, "Con exclusiones"),
    ]
    
    AGENCY_TEMPLATES = [
        # Búsqueda directa
        QueryTemplate("agencia de {service}", 1.0, "Agencia"),
        QueryTemplate("agencia {service}", 1.0, "Agencia simple"),
        QueryTemplate("empresa de {service}", 0.9, "Empresa"),
        QueryTemplate("consultoría {service}", 0.8, "Consultoría"),
        QueryTemplate("{service} agency", 0.8, "Agency inglés"),
        
        # Con indicadores de agencia real
        QueryTemplate('agencia {service} "nuestros servicios"', 0.9, "Con servicios"),
        QueryTemplate('agencia {service} "portfolio"', 0.9, "Con portfolio"),
        QueryTemplate('agencia {service} "casos de éxito"', 0.8, "Casos éxito"),
        QueryTemplate('agencia {service} "clientes"', 0.8, "Con clientes"),
        QueryTemplate('"agencia de {service}" "contacto"', 0.8, "Con contacto"),
        
        # Por ubicación (muy importante para agencias)
        QueryTemplate("agencia {service} madrid", 0.9, "Madrid"),
        QueryTemplate("agencia {service} barcelona", 0.9, "Barcelona"),
        QueryTemplate("agencia {service} valencia", 0.8, "Valencia"),
        QueryTemplate("agencia {service} sevilla", 0.8, "Sevilla"),
        QueryTemplate("agencia {service} méxico df", 0.7, "México"),
        QueryTemplate("agencia {service} buenos aires", 0.7, "Argentina"),
        QueryTemplate("{service} agency london", 0.6, "Londres"),
        QueryTemplate("{service} agency new york", 0.6, "Nueva York"),
        
        # Contratación
        QueryTemplate("contratar agencia {service}", 0.9, "Contratar"),
        QueryTemplate("presupuesto {service}", 0.7, "Presupuesto"),
        
        # Exclusiones
        QueryTemplate('agencia {service} -"cómo montar" -"qué es" -curso', 0.9, "Con exclusiones"),
    ]
    
    GENERIC_TEMPLATES = [
        # Genéricos con indicadores de negocio
        QueryTemplate("{query}", 1.0, "Original"),
        QueryTemplate("{query} españa", 0.9, "España"),
        QueryTemplate("{query} online", 0.8, "Online"),
        QueryTemplate('"{query}" "contacto"', 0.8, "Con contacto"),
        QueryTemplate('"{query}" "servicios"', 0.8, "Con servicios"),
        QueryTemplate("{query} empresa", 0.7, "Empresa"),
        QueryTemplate("{query} profesional", 0.7, "Profesional"),
        
        # Con exclusiones
        QueryTemplate('{query} -wikipedia -"qué es" -definición', 0.9, "Con exclusiones"),
        QueryTemplate('{query} -blog -artículo -guía', 0.8, "Sin blogs"),
    ]
    
    # Modificadores de nicho
    NICHE_MODIFIERS = {
        "luxury": ["lujo", "premium", "exclusivo", "luxury", "high-end"],
        "budget": ["barato", "económico", "low cost", "ofertas", "descuentos"],
        "eco": ["ecológico", "sostenible", "eco-friendly", "orgánico", "natural"],
        "vintage": ["vintage", "retro", "antiguo", "clásico", "second hand"],
        "modern": ["moderno", "contemporáneo", "minimalista", "modern"],
        "professional": ["profesional", "enterprise", "corporativo", "business"],
        "startup": ["startup", "emprendedor", "pyme", "pequeña empresa"],
    }
    
    # Ubicaciones comunes
    LOCATIONS = {
        "es": ["españa", "madrid", "barcelona", "valencia", "sevilla", "málaga", "bilbao"],
        "mx": ["méxico", "cdmx", "guadalajara", "monterrey"],
        "ar": ["argentina", "buenos aires"],
        "co": ["colombia", "bogotá", "medellín"],
        "us": ["usa", "new york", "los angeles", "miami"],
        "uk": ["uk", "london", "manchester"],
    }
    
    def __init__(self):
        pass
    
    def generate_queries(self, 
                        business_type: str,
                        main_term: str,
                        product_category: Optional[str] = None,
                        service_type: Optional[str] = None,
                        niche: Optional[str] = None,
                        locations: Optional[List[str]] = None,
                        max_queries: int = 15) -> List[str]:
        """
        Genera queries optimizadas basadas en el tipo de negocio.
        
        Args:
            business_type: ecommerce, saas, agencia, etc.
            main_term: Término principal del prompt
            product_category: Categoría de producto (para ecommerce)
            service_type: Tipo de servicio (para agencias/saas)
            niche: Nicho específico (luxury, eco, etc.)
            locations: Lista de ubicaciones a incluir
            max_queries: Número máximo de queries a generar
            
        Returns:
            Lista de queries ordenadas por relevancia
        """
        queries = []
        
        # Seleccionar templates según tipo de negocio
        if business_type.lower() in ["ecommerce", "tienda", "shop", "store"]:
            templates = self.ECOMMERCE_TEMPLATES
            fill_term = product_category or main_term
            fill_key = "product"
        elif business_type.lower() in ["saas", "software", "plataforma", "app", "tool"]:
            templates = self.SAAS_TEMPLATES
            fill_term = service_type or main_term
            fill_key = "service"
        elif business_type.lower() in ["agencia", "agency", "consultora", "consultoría"]:
            templates = self.AGENCY_TEMPLATES
            fill_term = service_type or main_term
            fill_key = "service"
        else:
            templates = self.GENERIC_TEMPLATES
            fill_term = main_term
            fill_key = "query"
        
        # Generar queries desde templates
        for template in templates:
            query = template.pattern.replace(f"{{{fill_key}}}", fill_term)
            query = query.replace("{product}", fill_term)
            query = query.replace("{service}", fill_term)
            query = query.replace("{query}", fill_term)
            
            queries.append((query, template.weight))
        
        # Añadir variaciones con nicho
        if niche:
            niche_queries = self._add_niche_variations(queries[:5], niche, fill_term)
            queries.extend(niche_queries)
        
        # Añadir variaciones por ubicación
        if locations:
            location_queries = self._add_location_variations(fill_term, business_type, locations)
            queries.extend(location_queries)
        
        # Ordenar por peso y eliminar duplicados
        queries.sort(key=lambda x: x[1], reverse=True)
        seen = set()
        unique_queries = []
        for query, weight in queries:
            query_normalized = query.lower().strip()
            if query_normalized not in seen:
                seen.add(query_normalized)
                unique_queries.append(query)
        
        return unique_queries[:max_queries]
    
    def _add_niche_variations(self, base_queries: List[tuple], 
                             niche: str, term: str) -> List[tuple]:
        """Añade variaciones basadas en el nicho."""
        variations = []
        niche_lower = niche.lower()
        
        # Buscar modificadores del nicho
        modifiers = []
        for key, mods in self.NICHE_MODIFIERS.items():
            if key in niche_lower or any(m in niche_lower for m in mods):
                modifiers.extend(mods[:2])  # Solo los 2 primeros
        
        if not modifiers:
            modifiers = [niche]
        
        for modifier in modifiers[:2]:
            variations.append((f"{term} {modifier}", 0.85))
            variations.append((f"tienda {term} {modifier}", 0.8))
        
        return variations
    
    def _add_location_variations(self, term: str, business_type: str, 
                                 locations: List[str]) -> List[tuple]:
        """Añade variaciones por ubicación."""
        variations = []
        
        for location in locations[:4]:  # Máximo 4 ubicaciones
            if business_type in ["agencia", "agency"]:
                variations.append((f"agencia {term} {location}", 0.85))
            elif business_type in ["ecommerce", "tienda"]:
                variations.append((f"tienda {term} {location}", 0.75))
            else:
                variations.append((f"{term} {location}", 0.7))
        
        return variations
    
    def generate_exclusion_query(self, base_query: str) -> str:
        """
        Genera una query con exclusiones para evitar contenido informativo.
        """
        exclusions = [
            '-"qué es"',
            '-wikipedia',
            '-"definición"',
            '-"guía de"',
            '-"cómo crear"',
            '-"tutorial"',
            '-blog',
        ]
        
        return f'{base_query} {" ".join(exclusions[:4])}'
    
    def generate_competitor_queries(self, known_competitor: str, 
                                   business_type: str) -> List[str]:
        """
        Genera queries para encontrar competidores de un negocio conocido.
        Útil para expandir búsquedas.
        """
        queries = [
            f"alternativas a {known_competitor}",
            f"sitios como {known_competitor}",
            f"{known_competitor} vs",
            f"competidores de {known_competitor}",
            f"mejor que {known_competitor}",
            f"parecido a {known_competitor}",
        ]
        
        return queries
    
    def get_transactional_queries(self, term: str, business_type: str) -> List[str]:
        """
        Genera queries con intención transaccional fuerte.
        Estas queries tienen mayor probabilidad de encontrar negocios reales.
        """
        if business_type in ["ecommerce", "tienda"]:
            return [
                f"comprar {term}",
                f"precio {term}",
                f"ofertas {term}",
                f"{term} envío 24h",
                f"dónde comprar {term}",
            ]
        elif business_type in ["saas", "software"]:
            return [
                f"{term} pricing",
                f"{term} free trial",
                f"probar {term} gratis",
                f"registrarse {term}",
                f"descargar {term}",
            ]
        elif business_type in ["agencia", "agency"]:
            return [
                f"contratar {term}",
                f"presupuesto {term}",
                f"servicios de {term}",
                f"{term} tarifas",
                f"pedir presupuesto {term}",
            ]
        else:
            return [
                f"contratar {term}",
                f"{term} servicios",
                f"{term} precios",
            ]


# Función de conveniencia
def generate_smart_queries(prompt: str, 
                          business_type: str,
                          product_category: str = None,
                          service_type: str = None,
                          niche: str = None,
                          max_queries: int = 15) -> List[str]:
    """
    Función de conveniencia para generar queries inteligentes.
    
    Ejemplo:
        queries = generate_smart_queries(
            prompt="ecommerce de crema facial",
            business_type="ecommerce",
            product_category="crema facial",
            niche="natural",
            max_queries=10
        )
    """
    generator = QueryGenerator()
    return generator.generate_queries(
        business_type=business_type,
        main_term=prompt,
        product_category=product_category,
        service_type=service_type,
        niche=niche,
        max_queries=max_queries
    )
