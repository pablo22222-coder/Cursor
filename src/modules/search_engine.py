"""
Search Engine Module - Serper API Integration
Performs intelligent web searches to find domains matching specifications
"""
import asyncio
import re
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass, field
from urllib.parse import urlparse
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
from loguru import logger

from ..config.settings import settings, BUSINESS_TYPE_SIGNATURES
from .prompt_parser import ParsedPrompt


@dataclass
class SearchResult:
    """Represents a single search result"""
    url: str
    domain: str
    title: str
    snippet: str
    position: int
    query_used: str
    relevance_indicators: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "domain": self.domain,
            "title": self.title,
            "snippet": self.snippet,
            "position": self.position,
            "query_used": self.query_used,
            "relevance_indicators": self.relevance_indicators
        }


class SearchEngine:
    """
    Intelligent search engine using Serper API
    Finds domains that ARE what the prompt describes, not domains that talk ABOUT it
    """
    
    # Domains to always exclude (they talk ABOUT things, not ARE things)
    EXCLUDED_DOMAINS = {
        # Educational/Informational
        "wikipedia.org", "es.wikipedia.org", "en.wikipedia.org",
        "wikihow.com", "quora.com", "reddit.com",
        
        # Platforms that help create, not ARE
        "shopify.com", "wix.com", "squarespace.com", "wordpress.com",
        "webflow.com", "godaddy.com", "hostinger.com", "bluehost.com",
        
        # Course/Tutorial platforms
        "udemy.com", "coursera.org", "domestika.org", "platzi.com",
        "youtube.com", "youtu.be",
        
        # News/Blog aggregators
        "medium.com", "blogger.com", "tumblr.com",
        
        # Job boards
        "linkedin.com", "indeed.com", "infojobs.net", "glassdoor.com",
        
        # Social media
        "facebook.com", "twitter.com", "instagram.com", "tiktok.com",
        
        # General marketplaces (when searching for specific stores)
        "amazon.com", "amazon.es", "ebay.com", "ebay.es",
        "aliexpress.com", "alibaba.com",
        
        # Definition sites
        "significados.com", "definicion.de", "rae.es",
        
        # Review sites
        "trustpilot.com", "yelp.com", "tripadvisor.com",
        
        # Forums
        "forocoches.com", "mediavida.com"
    }
    
    # Additional domains to exclude for specific business types
    BUSINESS_TYPE_EXCLUSIONS = {
        "ecommerce": {
            "shopify.com", "bigcommerce.com", "woocommerce.com",
            "prestashop.com", "magento.com", "ecwid.com"
        },
        "saas": {
            "g2.com", "capterra.com", "getapp.com", "softwareadvice.com"
        },
        "agencia": {
            "clutch.co", "sortlist.com", "agenciasdigitales.com"
        }
    }
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.api.serper_api_key
        self.endpoint = settings.api.serper_endpoint
        self.max_results = settings.search.max_results_per_query
        
        if not self.api_key:
            logger.warning("Serper API key not provided. Set SERPER_API_KEY environment variable.")
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _search_serper(self, query: str, num_results: int = 10, 
                             country: str = "es", language: str = "es") -> Dict[str, Any]:
        """
        Execute a single search query against Serper API
        """
        if not self.api_key:
            raise ValueError("Serper API key is required")
        
        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json"
        }
        
        payload = {
            "q": query,
            "num": num_results,
            "gl": country,
            "hl": language
        }
        
        logger.debug(f"Searching Serper: {query}")
        
        async with httpx.AsyncClient(timeout=settings.search.timeout_seconds) as client:
            response = await client.post(self.endpoint, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()
    
    def _extract_domain(self, url: str) -> str:
        """Extract clean domain from URL"""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            # Remove www. prefix
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except Exception:
            return url
    
    def _is_excluded_domain(self, domain: str, business_type: Optional[str] = None) -> bool:
        """Check if domain should be excluded"""
        # Check global exclusions
        for excluded in self.EXCLUDED_DOMAINS:
            if domain == excluded or domain.endswith(f".{excluded}"):
                return True
        
        # Check business-type specific exclusions
        if business_type and business_type in self.BUSINESS_TYPE_EXCLUSIONS:
            for excluded in self.BUSINESS_TYPE_EXCLUSIONS[business_type]:
                if domain == excluded or domain.endswith(f".{excluded}"):
                    return True
        
        return False
    
    def _check_relevance_indicators(self, title: str, snippet: str, 
                                    parsed_prompt: ParsedPrompt) -> List[str]:
        """
        Check for relevance indicators in title and snippet
        Returns list of matching indicators
        """
        indicators = []
        text = f"{title} {snippet}".lower()
        
        # Check for business type keywords
        if parsed_prompt.business_type:
            sig = BUSINESS_TYPE_SIGNATURES.get(parsed_prompt.business_type, {})
            keywords = sig.get("keywords", [])
            for kw in keywords:
                if kw.lower() in text:
                    indicators.append(f"business_keyword:{kw}")
        
        # Check for product keywords
        for kw in parsed_prompt.product_keywords:
            if kw.lower() in text:
                indicators.append(f"product_keyword:{kw}")
        
        # Check for custom keywords
        for kw in parsed_prompt.custom_keywords:
            if kw.lower() in text:
                indicators.append(f"custom_keyword:{kw}")
        
        # Check for anti-patterns (negative indicators)
        anti_patterns = ["que es", "definicion", "como crear", "tutorial", "curso", "guia"]
        for pattern in anti_patterns:
            if pattern in text:
                indicators.append(f"negative:{pattern}")
        
        # Check for positive commercial indicators
        commercial_indicators = [
            "comprar", "precio", "envio", "carrito", "checkout",
            "servicios", "contacto", "portfolio", "clientes",
            "planes", "pricing", "demo", "prueba gratis"
        ]
        for indicator in commercial_indicators:
            if indicator in text:
                indicators.append(f"commercial:{indicator}")
        
        return indicators
    
    def _is_likely_educational(self, title: str, snippet: str) -> bool:
        """Check if result is likely educational/informational rather than actual business"""
        text = f"{title} {snippet}".lower()
        
        educational_patterns = [
            r"qu[eé]\s+es",
            r"definici[oó]n",
            r"c[oó]mo\s+crear",
            r"c[oó]mo\s+hacer",
            r"tutorial",
            r"gu[ií]a\s+(?:completa|definitiva|para)",
            r"aprende\s+a",
            r"curso\s+de",
            r"\d+\s+(?:tips|consejos|pasos)",
            r"ejemplos?\s+de",
            r"mejores?\s+(?:herramientas|plataformas)",
            r"tipos?\s+de",
            r"ventajas?\s+(?:y|de)",
            r"qu[eé]\s+significa"
        ]
        
        for pattern in educational_patterns:
            if re.search(pattern, text):
                return True
        
        return False
    
    async def search(self, parsed_prompt: ParsedPrompt) -> List[SearchResult]:
        """
        Execute search based on parsed prompt
        Returns deduplicated list of relevant search results
        """
        if not self.api_key:
            logger.error("Cannot search without Serper API key")
            return []
        
        all_results: List[SearchResult] = []
        seen_domains: Set[str] = set()
        
        # Execute searches for each generated query
        for query in parsed_prompt.search_queries:
            try:
                # Search in different regions for diversity
                for country, lang in [("es", "es"), ("us", "en")]:
                    raw_results = await self._search_serper(
                        query=query,
                        num_results=self.max_results,
                        country=country,
                        language=lang
                    )
                    
                    # Process organic results
                    organic = raw_results.get("organic", [])
                    
                    for idx, item in enumerate(organic):
                        url = item.get("link", "")
                        domain = self._extract_domain(url)
                        
                        # Skip if already seen or excluded
                        if domain in seen_domains:
                            continue
                        
                        if self._is_excluded_domain(domain, parsed_prompt.business_type):
                            logger.debug(f"Excluded domain: {domain}")
                            continue
                        
                        title = item.get("title", "")
                        snippet = item.get("snippet", "")
                        
                        # Skip likely educational content when looking for business type
                        if parsed_prompt.is_looking_for_type:
                            if self._is_likely_educational(title, snippet):
                                logger.debug(f"Skipping educational result: {title}")
                                continue
                        
                        # Check relevance indicators
                        indicators = self._check_relevance_indicators(
                            title, snippet, parsed_prompt
                        )
                        
                        # Create result
                        result = SearchResult(
                            url=url,
                            domain=domain,
                            title=title,
                            snippet=snippet,
                            position=idx + 1,
                            query_used=query,
                            relevance_indicators=indicators
                        )
                        
                        all_results.append(result)
                        seen_domains.add(domain)
                        
                        # Stop if we have enough unique results
                        if len(all_results) >= settings.search.max_total_results:
                            break
                    
                    if len(all_results) >= settings.search.max_total_results:
                        break
                    
                    # Small delay between requests
                    await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Search error for query '{query}': {e}")
                continue
            
            if len(all_results) >= settings.search.max_total_results:
                break
        
        # Sort by relevance (more positive indicators = better)
        all_results.sort(
            key=lambda r: (
                len([i for i in r.relevance_indicators if not i.startswith("negative:")]) -
                len([i for i in r.relevance_indicators if i.startswith("negative:")]),
                -r.position  # Lower position is better
            ),
            reverse=True
        )
        
        logger.info(f"Search complete. Found {len(all_results)} unique domains")
        return all_results
    
    async def quick_search(self, query: str, num_results: int = 10) -> List[SearchResult]:
        """
        Quick search with a single query (for simple cases)
        """
        if not self.api_key:
            return []
        
        results = []
        seen_domains: Set[str] = set()
        
        try:
            raw_results = await self._search_serper(query, num_results)
            
            for idx, item in enumerate(raw_results.get("organic", [])):
                url = item.get("link", "")
                domain = self._extract_domain(url)
                
                if domain in seen_domains or self._is_excluded_domain(domain):
                    continue
                
                results.append(SearchResult(
                    url=url,
                    domain=domain,
                    title=item.get("title", ""),
                    snippet=item.get("snippet", ""),
                    position=idx + 1,
                    query_used=query
                ))
                seen_domains.add(domain)
        
        except Exception as e:
            logger.error(f"Quick search error: {e}")
        
        return results


# Factory function for creating search engine
def create_search_engine(api_key: Optional[str] = None) -> SearchEngine:
    """Create a SearchEngine instance"""
    return SearchEngine(api_key=api_key)
