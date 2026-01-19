"""
Analizador de métricas usando PageSpeed Insights API.

100% gratis con 25,000 requests/día.
"""
import requests
from typing import Optional
from ..models.domain import PageSpeedMetrics
from config.settings import settings


class PageSpeedAnalyzer:
    """
    Analiza métricas de rendimiento web usando Google PageSpeed Insights.
    
    Métricas disponibles:
    - Performance score
    - SEO score
    - Accessibility score
    - Best practices score
    - Core Web Vitals
    - Mobile friendly
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Inicializa el analizador.
        
        Args:
            api_key: API key de PageSpeed. Si no se proporciona, usa la configuración.
        """
        self.api_key = api_key or settings.api.PAGESPEED_API_KEY
        self.base_url = settings.api.PAGESPEED_BASE_URL
        self.timeout = settings.search.HTTP_TIMEOUT
    
    def analyze(self, url: str, strategy: str = "mobile") -> Optional[PageSpeedMetrics]:
        """
        Analiza las métricas de una URL.
        
        Args:
            url: URL a analizar
            strategy: "mobile" o "desktop"
            
        Returns:
            PageSpeedMetrics con los resultados, o None si falla
        """
        try:
            # Asegurar que la URL tiene protocolo
            if not url.startswith(('http://', 'https://')):
                url = f"https://{url}"
            
            params = {
                "url": url,
                "key": self.api_key,
                "strategy": strategy,
                "category": ["performance", "seo", "accessibility", "best-practices"]
            }
            
            response = requests.get(
                self.base_url,
                params=params,
                timeout=self.timeout + 20  # PageSpeed puede tardar más
            )
            response.raise_for_status()
            
            data = response.json()
            return self._parse_results(data)
            
        except requests.exceptions.RequestException as e:
            print(f"Error en PageSpeed para {url}: {e}")
            return None
        except Exception as e:
            print(f"Error parseando resultados de PageSpeed: {e}")
            return None
    
    def _parse_results(self, data: dict) -> PageSpeedMetrics:
        """Parsea los resultados de PageSpeed a PageSpeedMetrics."""
        metrics = PageSpeedMetrics()
        
        # Obtener categorías de lighthouse
        lighthouse = data.get("lighthouseResult", {})
        categories = lighthouse.get("categories", {})
        audits = lighthouse.get("audits", {})
        
        # Scores principales (convertir de 0-1 a 0-100)
        if "performance" in categories:
            score = categories["performance"].get("score")
            if score is not None:
                metrics.performance_score = int(score * 100)
        
        if "seo" in categories:
            score = categories["seo"].get("score")
            if score is not None:
                metrics.seo_score = int(score * 100)
        
        if "accessibility" in categories:
            score = categories["accessibility"].get("score")
            if score is not None:
                metrics.accessibility_score = int(score * 100)
        
        if "best-practices" in categories:
            score = categories["best-practices"].get("score")
            if score is not None:
                metrics.best_practices_score = int(score * 100)
        
        # Core Web Vitals y métricas de rendimiento
        if "largest-contentful-paint" in audits:
            lcp = audits["largest-contentful-paint"].get("numericValue")
            if lcp is not None:
                metrics.largest_contentful_paint = lcp / 1000  # Convertir a segundos
        
        if "total-blocking-time" in audits:
            # Usamos TBT como proxy para FID en lab data
            tbt = audits["total-blocking-time"].get("numericValue")
            if tbt is not None:
                metrics.first_input_delay = tbt  # En milisegundos
        
        if "cumulative-layout-shift" in audits:
            cls = audits["cumulative-layout-shift"].get("numericValue")
            if cls is not None:
                metrics.cumulative_layout_shift = cls
        
        if "speed-index" in audits:
            si = audits["speed-index"].get("numericValue")
            if si is not None:
                metrics.speed_index = si / 1000  # Convertir a segundos
        
        if "interactive" in audits:
            tti = audits["interactive"].get("numericValue")
            if tti is not None:
                metrics.time_to_interactive = tti / 1000  # Convertir a segundos
        
        # Mobile friendly (basado en viewport y tap targets)
        mobile_friendly = True
        if "viewport" in audits:
            if audits["viewport"].get("score", 1) < 1:
                mobile_friendly = False
        if "tap-targets" in audits:
            if audits["tap-targets"].get("score", 1) < 0.9:
                mobile_friendly = False
        metrics.is_mobile_friendly = mobile_friendly
        
        return metrics
    
    def check_slow_site(self, metrics: PageSpeedMetrics, threshold_seconds: float = 4.0) -> bool:
        """
        Verifica si una web tiene carga lenta.
        
        Args:
            metrics: Métricas de la web
            threshold_seconds: Umbral en segundos para considerar lenta
            
        Returns:
            True si la web es lenta
        """
        if metrics.speed_index and metrics.speed_index > threshold_seconds:
            return True
        if metrics.time_to_interactive and metrics.time_to_interactive > threshold_seconds:
            return True
        if metrics.performance_score and metrics.performance_score < 50:
            return True
        return False
    
    def check_good_seo(self, metrics: PageSpeedMetrics, min_score: int = 80) -> bool:
        """
        Verifica si una web tiene buen SEO.
        
        Args:
            metrics: Métricas de la web
            min_score: Score mínimo para considerar buen SEO
            
        Returns:
            True si tiene buen SEO
        """
        if metrics.seo_score and metrics.seo_score >= min_score:
            return True
        return False
    
    def get_metrics_summary(self, metrics: PageSpeedMetrics) -> dict:
        """
        Obtiene un resumen de las métricas.
        
        Args:
            metrics: Métricas de la web
            
        Returns:
            Diccionario con resumen de métricas
        """
        return {
            "performance": metrics.performance_score,
            "seo": metrics.seo_score,
            "accessibility": metrics.accessibility_score,
            "best_practices": metrics.best_practices_score,
            "mobile_friendly": metrics.is_mobile_friendly,
            "load_time_seconds": metrics.speed_index,
            "core_web_vitals": {
                "lcp": metrics.largest_contentful_paint,
                "fid": metrics.first_input_delay,
                "cls": metrics.cumulative_layout_shift
            }
        }
