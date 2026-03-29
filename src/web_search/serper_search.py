"""
Módulo de búsqueda web usando Serper API.
Implementa estrategias inteligentes de búsqueda para encontrar webs específicas.
"""
import requests
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Set
from urllib.parse import urlparse
import time

from config.settings import get_settings
# SerperSearch accepts any object with .search_queries and .business_type attrs.
# This covers both the legacy PromptAnalysis and the new SearchIntent.


@dataclass
class SearchResult:
    """Resultado individual de búsqueda."""
    url: str
    domain: str
    title: str
    snippet: str
    position: int
    query_used: str
    
    # Metadatos adicionales
    sitelinks: List[Dict[str, str]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "domain": self.domain,
            "title": self.title,
            "snippet": self.snippet,
            "position": self.position,
            "query_used": self.query_used,
            "sitelinks": self.sitelinks
        }


class SerperSearch:
    """Cliente para búsquedas en Serper API con estrategias inteligentes."""
    
    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.serper_base_url
        self.headers = {
            "X-API-KEY": self.settings.serper_api_key,
            "Content-Type": "application/json"
        }
        
        # Dominios a excluir (generalmente son informativos, no negocios reales)
        self.excluded_domains = {
            "wikipedia.org", "wikihow.com", "quora.com", "reddit.com",
            "medium.com", "linkedin.com", "facebook.com", "twitter.com",
            "youtube.com", "instagram.com", "tiktok.com", "pinterest.com",
            "amazon.com", "ebay.com",  # Marketplaces genéricos
            "shopify.com", "wix.com", "wordpress.com", "squarespace.com",  # Plataformas, no tiendas
            "hubspot.com", "semrush.com", "ahrefs.com", "moz.com",  # Tools de marketing
            "forbes.com", "entrepreneur.com", "inc.com",  # Revistas de negocios
            "coursera.org", "udemy.com",  # Educación
        }
    
    def search(self, analysis: Any, max_results: int = 50) -> List[SearchResult]:
        """
        Ejecuta búsquedas basadas en el análisis del prompt.
        
        Args:
            analysis: Análisis del prompt con queries generadas
            max_results: Número máximo de resultados únicos a retornar
            
        Returns:
            Lista de SearchResult únicos (sin duplicados de dominio)
        """
        all_results: List[SearchResult] = []
        seen_domains: Set[str] = set()
        
        # Ejecutar cada query
        for query in analysis.search_queries:
            if len(seen_domains) >= max_results:
                break
                
            results = self._execute_search(query)
            
            for result in results:
                if result.domain not in seen_domains and result.domain not in self.excluded_domains:
                    # Verificar que no sea un dominio excluido por subdominio
                    is_excluded = any(excl in result.domain for excl in self.excluded_domains)
                    if not is_excluded:
                        seen_domains.add(result.domain)
                        all_results.append(result)
                        
                        if len(seen_domains) >= max_results:
                            break
            
            # Pequeña pausa entre búsquedas para no saturar la API
            time.sleep(0.3)
        
        return all_results
    
    def search_with_operators(self, analysis: Any, max_results: int = 50) -> List[SearchResult]:
        """
        Búsqueda avanzada usando operadores de Google para mejores resultados.
        """
        all_results: List[SearchResult] = []
        seen_domains: Set[str] = set()
        
        # Generar queries con operadores basadas en el tipo de negocio
        operator_queries = self._generate_operator_queries(analysis)
        
        for query in operator_queries:
            if len(seen_domains) >= max_results:
                break
                
            results = self._execute_search(query)
            
            for result in results:
                if result.domain not in seen_domains and result.domain not in self.excluded_domains:
                    is_excluded = any(excl in result.domain for excl in self.excluded_domains)
                    if not is_excluded:
                        seen_domains.add(result.domain)
                        all_results.append(result)
            
            time.sleep(0.3)
        
        return all_results
    
    def _generate_operator_queries(self, analysis: Any) -> List[str]:
        """Genera queries con operadores de búsqueda avanzados."""
        queries = []
        base_terms = []
        
        # Construir términos base según el tipo de negocio
        if analysis.business_type == "ecommerce":
            base_terms = [
                "tienda online",
                "comprar online",
                "shop",
                "añadir al carrito",
                "envío gratis"
            ]
            if analysis.product_category:
                queries.append(f'intitle:"tienda" "{analysis.product_category}"')
                queries.append(f'"comprar {analysis.product_category}" "precio"')
                queries.append(f'"{analysis.product_category}" "añadir al carrito"')
            if analysis.niche:
                queries.append(f'"{analysis.niche}" tienda online')
                queries.append(f'shop "{analysis.niche}"')
                
        elif analysis.business_type == "saas":
            base_terms = [
                "pricing",
                "free trial",
                "sign up",
                "software",
                "platform"
            ]
            if analysis.service_type:
                queries.append(f'"{analysis.service_type}" software pricing')
                queries.append(f'"{analysis.service_type}" tool "free trial"')
                queries.append(f'"{analysis.service_type}" platform "sign up"')
                
        elif analysis.business_type == "agencia":
            base_terms = [
                "nuestros servicios",
                "portfolio",
                "casos de éxito",
                "contactar",
                "presupuesto"
            ]
            if analysis.service_type:
                queries.append(f'agencia "{analysis.service_type}" "nuestros servicios"')
                queries.append(f'"{analysis.service_type}" agency portfolio')
                queries.append(f'"{analysis.service_type}" "casos de éxito"')
        
        # Queries con exclusiones para evitar contenido informativo
        exclusions = '-"qué es" -"definición" -"guía" -"cómo crear" -wikipedia -"artículo"'
        
        for term in base_terms[:3]:
            if analysis.product_category:
                queries.append(f'{analysis.product_category} {term} {exclusions}')
            elif analysis.service_type:
                queries.append(f'{analysis.service_type} {term} {exclusions}')
            else:
                queries.append(f'{analysis.business_type} {term} {exclusions}')
        
        return queries
    
    def _execute_search(self, query: str, num_results: int = 20) -> List[SearchResult]:
        """Ejecuta una búsqueda individual en Serper."""
        payload = {
            "q": query,
            "num": num_results
        }
        
        try:
            response = requests.post(
                self.base_url,
                headers=self.headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            
            results = []
            organic = data.get("organic", [])
            
            for idx, item in enumerate(organic):
                url = item.get("link", "")
                if not url:
                    continue
                    
                domain = self._extract_domain(url)
                
                result = SearchResult(
                    url=url,
                    domain=domain,
                    title=item.get("title", ""),
                    snippet=item.get("snippet", ""),
                    position=idx + 1,
                    query_used=query,
                    sitelinks=item.get("sitelinks", [])
                )
                results.append(result)
            
            return results
            
        except requests.RequestException as e:
            print(f"Error en búsqueda Serper para '{query}': {e}")
            return []
    
    def _extract_domain(self, url: str) -> str:
        """Extrae el dominio de una URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            # Remover www. si existe
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except:
            return url
    
    def search_by_location(self, analysis: Any, locations: List[str], 
                          max_results_per_location: int = 10) -> List[SearchResult]:
        """
        Búsqueda segmentada por ubicación geográfica.
        Útil para encontrar negocios locales.
        """
        all_results = []
        seen_domains: Set[str] = set()
        
        for location in locations:
            for query in analysis.search_queries[:3]:  # Solo las 3 primeras queries por ubicación
                localized_query = f"{query} {location}"
                results = self._execute_search(localized_query, num_results=10)
                
                for result in results:
                    if result.domain not in seen_domains and result.domain not in self.excluded_domains:
                        seen_domains.add(result.domain)
                        all_results.append(result)
                        
                        if len(all_results) >= max_results_per_location * len(locations):
                            return all_results
                
                time.sleep(0.2)
        
        return all_results
    
    def expand_search(self, analysis: Any, existing_domains: Set[str], 
                     additional_queries: List[str]) -> List[SearchResult]:
        """
        Expande la búsqueda con queries adicionales, excluyendo dominios ya encontrados.
        """
        new_results = []
        
        for query in additional_queries:
            results = self._execute_search(query)
            
            for result in results:
                if result.domain not in existing_domains and result.domain not in self.excluded_domains:
                    existing_domains.add(result.domain)
                    new_results.append(result)
            
            time.sleep(0.3)
        
        return new_results
