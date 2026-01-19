"""
Generador de queries de búsqueda inteligentes.

Este módulo genera queries que encuentren webs que SEAN lo que busca
el usuario, no webs que hablen de eso.
"""
from typing import List, Optional
from ..models.domain import PromptIntent, BusinessType


class QueryGenerator:
    """
    Genera queries de búsqueda optimizadas para encontrar webs reales.
    
    La clave es usar términos que aparecen en webs reales de ese tipo,
    no términos que aparecerían en artículos que hablan del tema.
    """
    
    # Términos que indican que una web ES un ecommerce (no que habla de ecommerce)
    ECOMMERCE_INDICATORS = [
        "comprar", "añadir al carrito", "envío gratis", "tienda",
        "productos", "ofertas", "descuentos", "checkout"
    ]
    
    # Términos que indican que una web ES un SaaS
    SAAS_INDICATORS = [
        "pricing", "plans", "free trial", "sign up", "demo",
        "features", "integrations", "api"
    ]
    
    # Términos que indican que una web ES una agencia
    AGENCY_INDICATORS = [
        "servicios", "portfolio", "proyectos", "clientes",
        "equipo", "contacto", "presupuesto"
    ]
    
    # Exclusiones: términos que indican que es un artículo/definición
    EXCLUSION_TERMS = [
        "-\"qué es\"", "-\"definición\"", "-\"guía\"", "-\"tutorial\"",
        "-\"cómo crear\"", "-wikipedia", "-\"significado\""
    ]
    
    def __init__(self):
        pass
    
    def generate_queries(self, intent: PromptIntent) -> List[str]:
        """
        Genera queries optimizadas basadas en la intención del usuario.
        
        Args:
            intent: La intención analizada del prompt
            
        Returns:
            Lista de queries de búsqueda
        """
        queries = []
        
        if intent.business_type == BusinessType.ECOMMERCE:
            queries.extend(self._generate_ecommerce_queries(intent))
        elif intent.business_type == BusinessType.SAAS:
            queries.extend(self._generate_saas_queries(intent))
        elif intent.business_type == BusinessType.AGENCY:
            queries.extend(self._generate_agency_queries(intent))
        elif intent.business_type == BusinessType.DROPSHIPPING:
            queries.extend(self._generate_dropshipping_queries(intent))
        else:
            queries.extend(self._generate_generic_queries(intent))
        
        # Añadir exclusiones para evitar artículos
        queries = self._add_exclusions(queries)
        
        # Eliminar duplicados
        return list(dict.fromkeys(queries))[:5]
    
    def _generate_ecommerce_queries(self, intent: PromptIntent) -> List[str]:
        """Genera queries para encontrar tiendas online reales."""
        queries = []
        
        niche = intent.niche or ""
        product = intent.product_service or ""
        
        if product:
            # Queries muy específicas para el producto
            queries.append(f"comprar {product} online")
            queries.append(f"tienda {product}")
            queries.append(f"{product} precio envío")
            queries.append(f"shop {product}")
        
        if niche:
            queries.append(f"tienda online {niche}")
            queries.append(f"comprar {niche} españa")
            queries.append(f"mejores tiendas {niche} online")
        
        if not product and not niche:
            # Queries genéricas pero que encuentran tiendas reales
            queries.append("tienda online ropa comprar")
            queries.append("tienda online electrónica españa")
        
        return queries
    
    def _generate_saas_queries(self, intent: PromptIntent) -> List[str]:
        """Genera queries para encontrar productos SaaS reales."""
        queries = []
        
        niche = intent.niche or ""
        product = intent.product_service or ""
        
        if niche or product:
            term = product or niche
            queries.append(f"software {term} pricing")
            queries.append(f"{term} tool online free trial")
            queries.append(f"best {term} software")
            queries.append(f"herramienta {term} online")
        else:
            queries.append("software online pricing plans")
            queries.append("saas tool free trial")
        
        return queries
    
    def _generate_agency_queries(self, intent: PromptIntent) -> List[str]:
        """Genera queries para encontrar agencias reales."""
        queries = []
        
        niche = intent.niche or ""
        
        if niche:
            queries.append(f"agencia {niche} servicios")
            queries.append(f"agencia de {niche} portfolio")
            queries.append(f"empresa {niche} proyectos")
            queries.append(f"mejores agencias {niche} españa")
        else:
            queries.append("agencia marketing digital servicios")
            queries.append("agencia diseño web portfolio")
        
        return queries
    
    def _generate_dropshipping_queries(self, intent: PromptIntent) -> List[str]:
        """Genera queries para encontrar tiendas dropshipping."""
        queries = []
        
        niche = intent.niche or ""
        product = intent.product_service or ""
        
        # Las tiendas dropshipping suelen parecer tiendas normales
        # pero con ciertos indicadores
        if product or niche:
            term = product or niche
            queries.append(f"comprar {term} envío gratis")
            queries.append(f"tienda {term} productos")
            queries.append(f"{term} online store")
        else:
            queries.append("tienda online productos variados")
            queries.append("shop productos importados")
        
        return queries
    
    def _generate_generic_queries(self, intent: PromptIntent) -> List[str]:
        """Genera queries genéricas cuando no se detecta tipo específico."""
        queries = []
        
        # Usar el prompt original con modificaciones
        prompt = intent.original_prompt
        
        # Intentar inferir qué busca basándose en palabras clave
        queries.append(prompt)
        queries.append(f"mejores {prompt}")
        queries.append(f"{prompt} empresas")
        
        return queries
    
    def _add_exclusions(self, queries: List[str]) -> List[str]:
        """Añade términos de exclusión para evitar artículos/definiciones."""
        # Limitamos las exclusiones para no hacer la query demasiado larga
        exclusions = " ".join(self.EXCLUSION_TERMS[:3])
        
        return [f"{q} {exclusions}" for q in queries]
    
    def generate_verification_queries(self, domain: str, intent: PromptIntent) -> List[str]:
        """
        Genera queries para verificar si un dominio específico cumple el prompt.
        
        Args:
            domain: El dominio a verificar
            intent: La intención del usuario
            
        Returns:
            Queries para verificar el dominio
        """
        queries = []
        
        # Buscar información específica del dominio
        queries.append(f"site:{domain}")
        
        if intent.niche:
            queries.append(f"site:{domain} {intent.niche}")
        
        if intent.product_service:
            queries.append(f"site:{domain} {intent.product_service}")
        
        return queries
