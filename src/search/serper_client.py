"""
Cliente para la API de Serper (búsqueda en Google).
"""
import requests
from typing import List, Dict, Any, Optional
from ..models.domain import Domain
from config.settings import settings


class SerperClient:
    """
    Cliente para realizar búsquedas en Google usando la API de Serper.
    
    Serper proporciona acceso a los resultados de búsqueda de Google
    de forma programática.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Inicializa el cliente de Serper.
        
        Args:
            api_key: API key de Serper. Si no se proporciona, usa la configuración.
        """
        self.api_key = api_key or settings.api.SERPER_API_KEY
        self.base_url = settings.api.SERPER_BASE_URL
        self.timeout = settings.search.HTTP_TIMEOUT
    
    def search(
        self, 
        query: str, 
        num_results: int = 10,
        language: str = "es",
        country: str = "es"
    ) -> List[Domain]:
        """
        Realiza una búsqueda en Google usando Serper.
        
        Args:
            query: La query de búsqueda
            num_results: Número de resultados a obtener (máx 100)
            language: Idioma de los resultados
            country: País para los resultados
            
        Returns:
            Lista de Domain con los resultados encontrados
        """
        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json"
        }
        
        payload = {
            "q": query,
            "num": min(num_results, 100),
            "gl": country,
            "hl": language
        }
        
        try:
            response = requests.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            data = response.json()
            return self._parse_results(data, query)
            
        except requests.exceptions.RequestException as e:
            print(f"Error en búsqueda Serper: {e}")
            return []
    
    def _parse_results(self, data: Dict[str, Any], query: str) -> List[Domain]:
        """Parsea los resultados de Serper a objetos Domain."""
        domains = []
        
        organic_results = data.get("organic", [])
        
        for i, result in enumerate(organic_results):
            url = result.get("link", "")
            
            # Extraer dominio base
            domain_str = self._extract_domain(url)
            
            if domain_str:
                domain = Domain(
                    url=url,
                    domain=domain_str,
                    title=result.get("title", ""),
                    description=result.get("snippet", ""),
                    search_position=i + 1,
                    found_by_query=query
                )
                domains.append(domain)
        
        return domains
    
    def _extract_domain(self, url: str) -> str:
        """Extrae el dominio base de una URL."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc
            # Remover www. si existe
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except Exception:
            return ""
    
    def search_multiple(
        self, 
        queries: List[str],
        num_results_per_query: int = 10
    ) -> List[Domain]:
        """
        Realiza múltiples búsquedas y combina los resultados.
        
        Elimina dominios duplicados, priorizando los que aparecen
        en más búsquedas o en posiciones más altas.
        
        Args:
            queries: Lista de queries a buscar
            num_results_per_query: Resultados por cada query
            
        Returns:
            Lista de Domain únicos, ordenados por relevancia
        """
        all_domains: Dict[str, Domain] = {}
        domain_scores: Dict[str, int] = {}
        
        for query in queries:
            results = self.search(query, num_results_per_query)
            
            for domain in results:
                domain_key = domain.domain
                
                if domain_key not in all_domains:
                    all_domains[domain_key] = domain
                    domain_scores[domain_key] = 0
                
                # Puntuar por posición (mejor posición = más puntos)
                position_score = max(0, 11 - domain.search_position)
                domain_scores[domain_key] += position_score
                
                # Bonus por aparecer en múltiples queries
                domain_scores[domain_key] += 5
        
        # Ordenar por puntuación
        sorted_domains = sorted(
            all_domains.values(),
            key=lambda d: domain_scores[d.domain],
            reverse=True
        )
        
        return sorted_domains
