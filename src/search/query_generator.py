"""
Generador de queries de búsqueda inteligentes.

Este módulo genera queries que encuentren webs que SEAN lo que busca
el usuario, no webs que hablen de eso.

ESTRATEGIA CLAVE: Usar términos TRANSACCIONALES que aparecen en webs reales,
no términos informativos que aparecerían en artículos.
"""
from typing import List, Optional
from ..models.domain import PromptIntent, BusinessType


class QueryGenerator:
    """
    Genera queries de búsqueda optimizadas para encontrar webs reales.
    
    La clave es usar términos que aparecen en webs reales de ese tipo,
    no términos que aparecerían en artículos que hablan del tema.
    """
    
    # Plataformas de ecommerce conocidas para búsqueda directa
    ECOMMERCE_PLATFORMS_DOMAINS = [
        "myshopify.com",
        "tiendanube.com", 
        "wixsite.com",
        "squarespace.com"
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
        
        # Eliminar duplicados manteniendo orden
        seen = set()
        unique = []
        for q in queries:
            q_lower = q.lower()
            if q_lower not in seen:
                seen.add(q_lower)
                unique.append(q)
        
        return unique[:8]  # Más queries para mejores resultados
    
    def _generate_ecommerce_queries(self, intent: PromptIntent) -> List[str]:
        """
        Genera queries para encontrar tiendas online REALES.
        
        Estrategia: Usar términos que un COMPRADOR usaría, no un investigador.
        """
        queries = []
        
        niche = intent.niche or ""
        product = intent.product_service or ""
        
        # Término principal (producto o nicho)
        main_term = product or niche or "productos"
        
        # 1. QUERIES TRANSACCIONALES (como buscaría un comprador)
        queries.append(f"comprar {main_term} online")
        queries.append(f"{main_term} tienda online")
        queries.append(f"tienda {main_term} envío españa")
        
        # 2. QUERIES CON SEÑALES DE TIENDA REAL
        queries.append(f"{main_term} añadir carrito")
        queries.append(f"{main_term} precio oferta")
        
        # 3. QUERIES DE DESCUBRIMIENTO
        queries.append(f"mejores tiendas {main_term} online")
        queries.append(f"donde comprar {main_term}")
        
        # 4. QUERIES EN PLATAFORMAS ESPECÍFICAS (garantiza tiendas reales)
        if niche or product:
            queries.append(f"site:myshopify.com {main_term}")
        
        return queries
    
    def _generate_saas_queries(self, intent: PromptIntent) -> List[str]:
        """
        Genera queries para encontrar productos SaaS REALES.
        
        Estrategia: Buscar páginas de pricing, signup, features.
        """
        queries = []
        
        niche = intent.niche or ""
        product = intent.product_service or ""
        main_term = product or niche or "software"
        
        # Queries que encuentran SaaS reales (tienen pricing, trial, etc)
        queries.append(f"{main_term} software pricing")
        queries.append(f"{main_term} herramienta online gratis")
        queries.append(f"mejor {main_term} software 2024")
        queries.append(f"{main_term} app free trial")
        queries.append(f"{main_term} plataforma registrarse")
        queries.append(f"alternativas {main_term} software")
        
        return queries
    
    def _generate_agency_queries(self, intent: PromptIntent) -> List[str]:
        """
        Genera queries para encontrar agencias REALES.
        
        Estrategia: Buscar páginas de servicios, portfolio, contacto.
        """
        queries = []
        
        niche = intent.niche or ""
        product = intent.product_service or niche
        
        # Queries que encuentran agencias reales
        queries.append(f"agencia {product} españa")
        queries.append(f"agencia {product} servicios precios")
        queries.append(f"mejores agencias {product} españa")
        queries.append(f"empresa {product} portfolio clientes")
        queries.append(f"contratar agencia {product}")
        queries.append(f"agencia {product} presupuesto")
        queries.append(f"top agencias {product} madrid barcelona")
        
        return queries
    
    def _generate_dropshipping_queries(self, intent: PromptIntent) -> List[str]:
        """Genera queries para encontrar tiendas dropshipping."""
        queries = []
        
        niche = intent.niche or ""
        product = intent.product_service or ""
        main_term = product or niche or "productos"
        
        # Dropshipping suele ser tiendas con envío desde China/internacional
        queries.append(f"comprar {main_term} envío gratis")
        queries.append(f"tienda {main_term} ofertas")
        queries.append(f"{main_term} barato online")
        queries.append(f"site:myshopify.com {main_term}")
        
        return queries
    
    def _generate_generic_queries(self, intent: PromptIntent) -> List[str]:
        """
        Genera queries cuando no se detecta tipo específico.
        
        Intenta inferir la intención y buscar webs reales.
        """
        queries = []
        prompt = intent.original_prompt.strip()
        niche = intent.niche or ""
        product = intent.product_service or ""
        
        # Si tiene nicho, probablemente busca tiendas o servicios
        if niche or product:
            term = product or niche
            queries.append(f"comprar {term} online")
            queries.append(f"{term} tienda")
            queries.append(f"{term} empresa servicios")
            queries.append(f"mejores {term} españa")
        
        # Queries basadas en el prompt original
        queries.append(f"{prompt} online")
        queries.append(f"mejores {prompt}")
        queries.append(f"{prompt} españa")
        
        return queries
    
    def generate_verification_queries(self, domain: str, intent: PromptIntent) -> List[str]:
        """
        Genera queries para verificar si un dominio específico cumple el prompt.
        """
        queries = []
        queries.append(f"site:{domain}")
        
        if intent.niche:
            queries.append(f"site:{domain} {intent.niche}")
        
        if intent.product_service:
            queries.append(f"site:{domain} {intent.product_service}")
        
        return queries
