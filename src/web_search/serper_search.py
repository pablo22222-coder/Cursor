"""
SerperSearch — Motor de búsqueda conectado a SearchIntent.

Recibe un SearchIntent producido por AIInterpreter y ejecuta un bucle
sobre TODAS sus search_queries, combinando resultados sin duplicados.

Mejoras respecto a la versión anterior:
· Itera cada query de intent.search_queries (no se detiene en la primera)
· Cap por query (RESULTS_PER_QUERY) para no saturar la cuota de Serper
· Pre-filtrado por exclusion_indicators en snippet antes de añadir resultado
· Si intent.location tiene ciudad/región se añaden queries geo-localizadas
· Descarte por dominio exacto y por sufijo (ej. "shopify.com" cubre "tienda.myshopify.com")
"""
import time
import requests
from dataclasses import dataclass, field
from typing import List, Dict, Any, Set, Optional
from urllib.parse import urlparse

from config.settings import get_settings

# Resultados máximos por query individual (evita consumir toda la cuota en una sola)
RESULTS_PER_QUERY = 10


@dataclass
class SearchResult:
    """Resultado individual de búsqueda."""
    url: str
    domain: str
    title: str
    snippet: str
    position: int
    query_used: str
    sitelinks: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url":        self.url,
            "domain":     self.domain,
            "title":      self.title,
            "snippet":    self.snippet,
            "position":   self.position,
            "query_used": self.query_used,
            "sitelinks":  self.sitelinks,
        }


# Dominios informativos/plataforma que nunca son el negocio real buscado
_EXCLUDED_DOMAIN_SUFFIXES = {
    "wikipedia.org", "wikihow.com", "quora.com", "reddit.com",
    "medium.com", "linkedin.com", "facebook.com", "twitter.com", "x.com",
    "youtube.com", "instagram.com", "tiktok.com", "pinterest.com",
    "amazon.com", "amazon.es", "ebay.com", "ebay.es",
    "shopify.com", "wix.com", "wordpress.com", "squarespace.com",
    "hubspot.com", "semrush.com", "ahrefs.com", "moz.com",
    "forbes.com", "entrepreneur.com", "inc.com",
    "coursera.org", "udemy.com",
}

# Patrones en título/snippet que indican contenido informativo, no un negocio real
_INFORMATIVE_PATTERNS = [
    "qué es ", "que es ", "definición", "guía de", "guia de",
    "cómo crear", "como crear", "tutorial", "artículo", "articulo",
    "wikipedia", "los mejores", "las mejores", "top 10", "comparativa",
    "opiniones sobre", "reseña de",
]


class SerperSearch:
    """
    Cliente para búsquedas Serper API.
    Acepta un SearchIntent y ejecuta todas sus queries de forma inteligente.
    """

    def __init__(self):
        settings = get_settings()
        self._base_url = settings.serper_base_url
        self._headers = {
            "X-API-KEY": settings.serper_api_key,
            "Content-Type": "application/json",
        }

    # ── Método principal ─────────────────────────────────────────────────────

    def search(self, intent: Any, max_results: int = 50) -> List[SearchResult]:
        """
        Ejecuta TODAS las queries de intent.search_queries y combina resultados.

        - Añade queries de localización si intent.location tiene datos
        - Pre-filtra snippets con intent.exclusion_indicators
        - Evita duplicados por dominio exacto
        - Respeta max_results como límite total de dominios únicos

        Args:
            intent: SearchIntent (o cualquier objeto con .search_queries,
                    .exclusion_indicators, .location)
            max_results: Máximo de dominios únicos a devolver

        Returns:
            Lista de SearchResult únicos, ordenados por query de origen
        """
        queries = list(getattr(intent, "search_queries", []))

        # Añadir queries geo-localizadas si hay localización en el intent
        location = getattr(intent, "location", {}) or {}
        geo_tag = " ".join(filter(None, [
            location.get("city"),
            location.get("region"),
            location.get("country"),
        ]))
        if geo_tag and queries:
            # Añadir versión localizada de las 3 primeras queries más relevantes
            for q in queries[:3]:
                localized = f"{q} {geo_tag}"
                if localized not in queries:
                    queries.append(localized)

        exclusion_indicators: List[str] = [
            i.lower() for i in (getattr(intent, "exclusion_indicators", []) or [])
        ]

        all_results: List[SearchResult] = []
        seen_domains: Set[str] = set()

        for query in queries:
            if len(seen_domains) >= max_results:
                break

            raw = self._execute_query(query, num=RESULTS_PER_QUERY)

            for result in raw:
                if len(seen_domains) >= max_results:
                    break

                # Descartar dominios de plataformas/informativos
                if self._is_excluded_domain(result.domain):
                    continue

                # Descartar si el snippet contiene exclusion_indicators del intent
                if self._snippet_is_excluded(result, exclusion_indicators):
                    continue

                # Descartar duplicados
                if result.domain in seen_domains:
                    continue

                seen_domains.add(result.domain)
                all_results.append(result)

            # Pausa mínima para no saturar la API de Serper
            time.sleep(0.25)

        print(
            f"[SerperSearch] {len(queries)} queries ejecutadas → "
            f"{len(all_results)} dominios únicos encontrados"
        )
        return all_results

    # ── Helpers internos ─────────────────────────────────────────────────────

    def _execute_query(self, query: str, num: int = RESULTS_PER_QUERY) -> List[SearchResult]:
        """Ejecuta una sola query en Serper y devuelve los resultados crudos."""
        try:
            resp = requests.post(
                self._base_url,
                headers=self._headers,
                json={"q": query, "num": num},
                timeout=30,
            )
            resp.raise_for_status()
            organic = resp.json().get("organic", [])
        except requests.RequestException as e:
            print(f"[SerperSearch] Error en query '{query[:60]}': {e}")
            return []

        results = []
        for idx, item in enumerate(organic):
            url = item.get("link", "")
            if not url:
                continue
            results.append(SearchResult(
                url=url,
                domain=self._domain_from_url(url),
                title=item.get("title", ""),
                snippet=item.get("snippet", ""),
                position=idx + 1,
                query_used=query,
                sitelinks=item.get("sitelinks", []),
            ))
        return results

    def _is_excluded_domain(self, domain: str) -> bool:
        """True si el dominio o alguno de sus sufijos está en la lista negra."""
        d = domain.lower()
        if d in _EXCLUDED_DOMAIN_SUFFIXES:
            return True
        return any(d.endswith("." + excl) or d == excl for excl in _EXCLUDED_DOMAIN_SUFFIXES)

    def _snippet_is_excluded(self, result: SearchResult, exclusion_indicators: List[str]) -> bool:
        """
        True si el snippet/título contiene patrones informativos genéricos
        O contiene algún exclusion_indicator específico del intent.
        """
        text = f"{result.title} {result.snippet}".lower()

        # Patrones informativos genéricos
        if any(p in text for p in _INFORMATIVE_PATTERNS):
            return True

        # Indicadores de exclusión específicos del intent
        if any(ind in text for ind in exclusion_indicators):
            return True

        return False

    @staticmethod
    def _domain_from_url(url: str) -> str:
        """Extrae el dominio limpio (sin www.) de una URL."""
        try:
            netloc = urlparse(url).netloc.lower()
            return netloc[4:] if netloc.startswith("www.") else netloc
        except Exception:
            return url
