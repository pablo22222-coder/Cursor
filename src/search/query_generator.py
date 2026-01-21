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
        Genera queries TRANSACCIONALES optimizadas.
        
        CLAVE: Generar queries que un COMPRADOR/CLIENTE usaría,
        no queries que un investigador usaría.
        
        Args:
            intent: La intención analizada del prompt
            
        Returns:
            Lista de queries de búsqueda transaccionales
        """
        queries = []
        
        # Obtener término principal del prompt limpio
        main_term = self._extract_main_term(intent)
        
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
        
        # Añadir queries transaccionales directas basadas en el prompt
        queries.extend(self._generate_transactional_queries(intent, main_term))
        
        # Eliminar duplicados manteniendo orden
        seen = set()
        unique = []
        for q in queries:
            q_lower = q.lower()
            if q_lower not in seen:
                seen.add(q_lower)
                unique.append(q)
        
        return unique[:10]
    
    def _extract_main_term(self, intent: PromptIntent) -> str:
        """Extrae el término principal del prompt."""
        # Usar producto/servicio si existe
        if intent.product_service:
            return intent.product_service
        # Usar nicho si existe
        if intent.niche:
            return intent.niche
        # Usar el prompt limpio
        return intent.cleaned_prompt
    
    def _generate_transactional_queries(self, intent: PromptIntent, main_term: str) -> List[str]:
        """
        Genera queries puramente transaccionales.
        
        Estas queries son las que un comprador real usaría.
        """
        queries = []
        
        if not main_term:
            return queries
        
        # Queries transaccionales universales
        queries.append(f"comprar {main_term}")
        queries.append(f"{main_term} tienda")
        queries.append(f"{main_term} precio")
        queries.append(f"{main_term} online")
        
        # Queries en plataformas de ecommerce (garantiza tiendas reales)
        queries.append(f"site:myshopify.com {main_term}")
        
        return queries
    
    def _generate_ecommerce_queries(self, intent: PromptIntent) -> List[str]:
        """
        Genera queries para encontrar tiendas online REALES.
        
        Estrategia: Usar términos que un COMPRADOR usaría, no un investigador.
        EXCLUIR: artículos, guías, definiciones, cursos
        """
        queries = []
        
        niche = intent.niche or ""
        product = intent.product_service or ""
        main_term = product or niche or "productos"
        
        # 1. QUERIES TRANSACCIONALES DIRECTAS (intención de compra)
        queries.append(f"comprar {main_term}")
        queries.append(f"{main_term} envío gratis")
        queries.append(f"{main_term} ofertas descuentos")
        
        # 2. QUERIES QUE ENCUENTRAN LISTADOS DE TIENDAS
        queries.append(f"mejores tiendas {main_term} españa")
        queries.append(f"tiendas online {main_term} 2024")
        
        # 3. QUERIES EN PLATAFORMAS DE ECOMMERCE (100% tiendas reales)
        queries.append(f"site:myshopify.com {main_term}")
        queries.append(f"site:tiendanube.com {main_term}")
        
        # 4. QUERIES CON INDICADORES DE TIENDA
        queries.append(f'"{main_term}" "añadir al carrito"')
        queries.append(f'"{main_term}" "envío" "precio"')
        
        return queries
    
    def _generate_saas_queries(self, intent: PromptIntent) -> List[str]:
        """
        Genera queries para encontrar productos SaaS REALES.
        
        Estrategia: Buscar páginas de pricing, signup, features.
        EXCLUIR: artículos, comparativas genéricas
        """
        queries = []
        
        niche = intent.niche or ""
        product = intent.product_service or ""
        main_term = product or niche or "software"
        
        # Queries que encuentran SaaS reales
        queries.append(f"{main_term} software precio planes")
        queries.append(f"{main_term} herramienta gratis prueba")
        queries.append(f"{main_term} app registrarse")
        queries.append(f'"{main_term}" "pricing" "free trial"')
        queries.append(f'"{main_term}" "sign up" "plans"')
        queries.append(f"mejor software {main_term} empresas")
        
        return queries
    
    def _generate_agency_queries(self, intent: PromptIntent) -> List[str]:
        """
        Genera queries para encontrar agencias REALES.
        
        Estrategia: Buscar páginas de servicios, portfolio, contacto.
        EXCLUIR: artículos sobre cómo ser agencia
        """
        queries = []
        
        niche = intent.niche or ""
        product = intent.product_service or niche
        
        # Queries que encuentran agencias reales
        queries.append(f"agencia {product} contratar")
        queries.append(f"agencia {product} presupuesto servicios")
        queries.append(f"mejores agencias {product} españa 2024")
        queries.append(f'agencia {product} "portfolio" "clientes"')
        queries.append(f'agencia {product} "contacto" "servicios"')
        queries.append(f"top 10 agencias {product} madrid")
        queries.append(f"ranking agencias {product} barcelona")
        
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
        
        Estrategia: Asumir intención transaccional y buscar webs reales.
        """
        queries = []
        prompt = intent.cleaned_prompt or intent.original_prompt.strip()
        niche = intent.niche or ""
        product = intent.product_service or ""
        
        # Término principal
        term = product or niche or prompt
        
        # Queries transaccionales genéricas
        queries.append(f"comprar {term}")
        queries.append(f"{term} tienda online")
        queries.append(f"{term} precio")
        queries.append(f"mejores {term} españa 2024")
        queries.append(f"{term} empresas servicios")
        queries.append(f'"{term}" "contacto"')
        
        # Búsqueda en plataformas
        queries.append(f"site:myshopify.com {term}")
        
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
