"""
Analizador de rendimiento usando Google PageSpeed Insights API.
Evalúa métricas de rendimiento, SEO, accesibilidad y best practices.
"""
import requests
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from config.settings import get_settings


@dataclass
class PerformanceMetrics:
    """Métricas de rendimiento de una web."""
    domain: str
    url: str
    
    # Scores principales (0-100)
    performance_score: Optional[float] = None
    seo_score: Optional[float] = None
    accessibility_score: Optional[float] = None
    best_practices_score: Optional[float] = None
    
    # Core Web Vitals
    lcp: Optional[float] = None  # Largest Contentful Paint (segundos)
    fid: Optional[float] = None  # First Input Delay (milisegundos)
    cls: Optional[float] = None  # Cumulative Layout Shift
    fcp: Optional[float] = None  # First Contentful Paint (segundos)
    ttfb: Optional[float] = None  # Time to First Byte (milisegundos)
    
    # Métricas adicionales
    speed_index: Optional[float] = None
    time_to_interactive: Optional[float] = None
    total_blocking_time: Optional[float] = None
    
    # Clasificaciones
    is_mobile_friendly: bool = False
    performance_category: str = "unknown"  # fast, average, slow
    
    # Estado del análisis
    analysis_success: bool = False
    error_message: Optional[str] = None
    
    # Datos raw para análisis detallado
    raw_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "url": self.url,
            "performance_score": self.performance_score,
            "seo_score": self.seo_score,
            "accessibility_score": self.accessibility_score,
            "best_practices_score": self.best_practices_score,
            "lcp": self.lcp,
            "fid": self.fid,
            "cls": self.cls,
            "fcp": self.fcp,
            "ttfb": self.ttfb,
            "speed_index": self.speed_index,
            "time_to_interactive": self.time_to_interactive,
            "total_blocking_time": self.total_blocking_time,
            "is_mobile_friendly": self.is_mobile_friendly,
            "performance_category": self.performance_category,
            "analysis_success": self.analysis_success,
            "error_message": self.error_message
        }
    
    def meets_criteria(self, criteria: Dict[str, Any]) -> bool:
        """
        Verifica si las métricas cumplen con los criterios especificados.
        
        Args:
            criteria: Diccionario con criterios. Ejemplos:
                - {"performance": "fast"} o {"performance": "slow"}
                - {"min_performance_score": 50}
                - {"max_lcp": 2.5}
                - {"is_mobile_friendly": True}
        """
        if not self.analysis_success:
            return False
        
        # Verificar categoría de rendimiento
        if "performance" in criteria:
            if criteria["performance"] == "fast" and self.performance_category != "fast":
                return False
            if criteria["performance"] == "slow" and self.performance_category != "slow":
                return False
            if criteria["performance"] == "average" and self.performance_category != "average":
                return False
        
        # Verificar scores mínimos
        if "min_performance_score" in criteria:
            if self.performance_score is None or self.performance_score < criteria["min_performance_score"]:
                return False
        
        if "min_seo_score" in criteria:
            if self.seo_score is None or self.seo_score < criteria["min_seo_score"]:
                return False
        
        # Verificar scores máximos (para buscar webs lentas/malas)
        if "max_performance_score" in criteria:
            if self.performance_score is None or self.performance_score > criteria["max_performance_score"]:
                return False
        
        # Verificar LCP
        if "max_lcp" in criteria:
            if self.lcp is None or self.lcp > criteria["max_lcp"]:
                return False
        
        if "min_lcp" in criteria:
            if self.lcp is None or self.lcp < criteria["min_lcp"]:
                return False
        
        # Verificar mobile friendly
        if "is_mobile_friendly" in criteria:
            if self.is_mobile_friendly != criteria["is_mobile_friendly"]:
                return False
        
        return True


class PageSpeedAnalyzer:
    """Cliente para Google PageSpeed Insights API."""
    
    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.pagespeed_api_key
        self.base_url = self.settings.pagespeed_base_url
    
    def analyze(self, url: str, strategy: str = "mobile") -> PerformanceMetrics:
        """
        Analiza el rendimiento de una URL.
        
        Args:
            url: URL a analizar
            strategy: "mobile" o "desktop"
            
        Returns:
            PerformanceMetrics con todas las métricas
        """
        # Asegurar que la URL tiene protocolo
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        
        domain = self._extract_domain(url)
        metrics = PerformanceMetrics(domain=domain, url=url)
        
        params = {
            "url": url,
            "key": self.api_key,
            "strategy": strategy,
            "category": ["performance", "seo", "accessibility", "best-practices"]
        }
        
        try:
            response = requests.get(
                self.base_url,
                params=params,
                timeout=60  # PageSpeed puede tardar
            )
            
            if response.status_code == 200:
                data = response.json()
                self._parse_results(metrics, data)
                metrics.analysis_success = True
            else:
                metrics.error_message = f"Error API: {response.status_code} - {response.text[:200]}"
                
        except requests.Timeout:
            metrics.error_message = "Timeout al analizar la web"
        except requests.RequestException as e:
            metrics.error_message = f"Error de conexión: {str(e)}"
        except Exception as e:
            metrics.error_message = f"Error inesperado: {str(e)}"
        
        return metrics
    
    def _parse_results(self, metrics: PerformanceMetrics, data: Dict[str, Any]):
        """Parsea los resultados de PageSpeed API."""
        metrics.raw_data = data
        
        # Extraer lighthouse results
        lighthouse = data.get("lighthouseResult", {})
        categories = lighthouse.get("categories", {})
        audits = lighthouse.get("audits", {})
        
        # Scores principales (convertir de 0-1 a 0-100)
        if "performance" in categories:
            score = categories["performance"].get("score")
            if score is not None:
                metrics.performance_score = round(score * 100, 1)
        
        if "seo" in categories:
            score = categories["seo"].get("score")
            if score is not None:
                metrics.seo_score = round(score * 100, 1)
        
        if "accessibility" in categories:
            score = categories["accessibility"].get("score")
            if score is not None:
                metrics.accessibility_score = round(score * 100, 1)
        
        if "best-practices" in categories:
            score = categories["best-practices"].get("score")
            if score is not None:
                metrics.best_practices_score = round(score * 100, 1)
        
        # Core Web Vitals
        if "largest-contentful-paint" in audits:
            lcp_ms = audits["largest-contentful-paint"].get("numericValue")
            if lcp_ms is not None:
                metrics.lcp = round(lcp_ms / 1000, 2)  # Convertir a segundos
        
        if "first-contentful-paint" in audits:
            fcp_ms = audits["first-contentful-paint"].get("numericValue")
            if fcp_ms is not None:
                metrics.fcp = round(fcp_ms / 1000, 2)
        
        if "cumulative-layout-shift" in audits:
            metrics.cls = audits["cumulative-layout-shift"].get("numericValue")
            if metrics.cls is not None:
                metrics.cls = round(metrics.cls, 3)
        
        if "total-blocking-time" in audits:
            tbt_ms = audits["total-blocking-time"].get("numericValue")
            if tbt_ms is not None:
                metrics.total_blocking_time = round(tbt_ms, 0)
        
        if "speed-index" in audits:
            si_ms = audits["speed-index"].get("numericValue")
            if si_ms is not None:
                metrics.speed_index = round(si_ms / 1000, 2)
        
        if "interactive" in audits:
            tti_ms = audits["interactive"].get("numericValue")
            if tti_ms is not None:
                metrics.time_to_interactive = round(tti_ms / 1000, 2)
        
        if "server-response-time" in audits:
            ttfb_ms = audits["server-response-time"].get("numericValue")
            if ttfb_ms is not None:
                metrics.ttfb = round(ttfb_ms, 0)
        
        # Clasificar rendimiento
        metrics.performance_category = self._classify_performance(metrics)
        
        # Verificar mobile-friendly (basado en viewport y tap targets)
        metrics.is_mobile_friendly = self._check_mobile_friendly(audits)
    
    def _classify_performance(self, metrics: PerformanceMetrics) -> str:
        """Clasifica el rendimiento como fast, average o slow."""
        if metrics.performance_score is None:
            return "unknown"
        
        if metrics.performance_score >= 90:
            return "fast"
        elif metrics.performance_score >= 50:
            return "average"
        else:
            return "slow"
    
    def _check_mobile_friendly(self, audits: Dict[str, Any]) -> bool:
        """Verifica si la web es mobile-friendly."""
        mobile_indicators = 0
        
        # Verificar viewport
        if "viewport" in audits:
            if audits["viewport"].get("score", 0) == 1:
                mobile_indicators += 1
        
        # Verificar tap targets
        if "tap-targets" in audits:
            if audits["tap-targets"].get("score", 0) >= 0.9:
                mobile_indicators += 1
        
        # Verificar font sizes
        if "font-size" in audits:
            if audits["font-size"].get("score", 0) >= 0.9:
                mobile_indicators += 1
        
        return mobile_indicators >= 2
    
    def _extract_domain(self, url: str) -> str:
        """Extrae el dominio de una URL."""
        from urllib.parse import urlparse
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except:
            return url
    
    def analyze_batch(self, urls: List[str], strategy: str = "mobile") -> List[PerformanceMetrics]:
        """
        Analiza múltiples URLs.
        NOTA: Usar con precaución, cada análisis puede tardar varios segundos.
        """
        results = []
        for url in urls:
            metrics = self.analyze(url, strategy)
            results.append(metrics)
        return results
    
    def quick_check(self, url: str) -> Dict[str, Any]:
        """
        Análisis rápido que solo obtiene los scores principales.
        Útil para filtrado inicial.
        """
        metrics = self.analyze(url)
        return {
            "domain": metrics.domain,
            "performance_score": metrics.performance_score,
            "seo_score": metrics.seo_score,
            "is_mobile_friendly": metrics.is_mobile_friendly,
            "performance_category": metrics.performance_category,
            "success": metrics.analysis_success
        }
