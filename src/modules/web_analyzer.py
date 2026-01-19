"""
Web Analyzer Module - WebTech & PageSpeed Insights Integration
Analyzes websites to detect technologies, business type, and performance metrics
"""
import asyncio
import subprocess
import json
import re
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
import httpx
from loguru import logger

from ..config.settings import settings, BUSINESS_TYPE_SIGNATURES


@dataclass
class TechnologyInfo:
    """Information about a detected technology"""
    name: str
    category: str
    version: Optional[str] = None
    confidence: float = 1.0


@dataclass
class PageSpeedMetrics:
    """PageSpeed Insights metrics"""
    performance_score: float = 0.0
    seo_score: float = 0.0
    accessibility_score: float = 0.0
    best_practices_score: float = 0.0
    first_contentful_paint: float = 0.0  # seconds
    largest_contentful_paint: float = 0.0  # seconds
    total_blocking_time: float = 0.0  # milliseconds
    cumulative_layout_shift: float = 0.0
    speed_index: float = 0.0
    is_mobile_friendly: bool = False
    has_https: bool = False


@dataclass  
class WebAnalysis:
    """Complete analysis of a website"""
    url: str
    domain: str
    technologies: List[TechnologyInfo] = field(default_factory=list)
    detected_business_type: Optional[str] = None
    business_type_confidence: float = 0.0
    detected_cms: Optional[str] = None
    detected_ecommerce_platform: Optional[str] = None
    has_payment_processor: bool = False
    has_analytics: bool = False
    has_marketing_tools: bool = False
    pagespeed_metrics: Optional[PageSpeedMetrics] = None
    analysis_errors: List[str] = field(default_factory=list)
    raw_webtech_data: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "domain": self.domain,
            "technologies": [
                {"name": t.name, "category": t.category, "version": t.version}
                for t in self.technologies
            ],
            "detected_business_type": self.detected_business_type,
            "business_type_confidence": self.business_type_confidence,
            "detected_cms": self.detected_cms,
            "detected_ecommerce_platform": self.detected_ecommerce_platform,
            "has_payment_processor": self.has_payment_processor,
            "has_analytics": self.has_analytics,
            "has_marketing_tools": self.has_marketing_tools,
            "pagespeed_metrics": {
                "performance_score": self.pagespeed_metrics.performance_score,
                "seo_score": self.pagespeed_metrics.seo_score,
                "accessibility_score": self.pagespeed_metrics.accessibility_score,
                "best_practices_score": self.pagespeed_metrics.best_practices_score,
                "is_mobile_friendly": self.pagespeed_metrics.is_mobile_friendly,
                "has_https": self.pagespeed_metrics.has_https,
            } if self.pagespeed_metrics else None,
            "analysis_errors": self.analysis_errors
        }


class WebAnalyzer:
    """
    Comprehensive web analyzer using WebTech and PageSpeed Insights
    """
    
    # Technology to business type mapping
    ECOMMERCE_TECHNOLOGIES = {
        "Shopify", "WooCommerce", "Magento", "PrestaShop", "BigCommerce",
        "OpenCart", "Wix Stores", "Squarespace Commerce", "nopCommerce",
        "osCommerce", "Zen Cart", "X-Cart", "Volusion", "3dcart",
        "Ecwid", "Snipcart", "Gumroad", "Sellfy", "ThriveCart"
    }
    
    PAYMENT_PROCESSORS = {
        "Stripe", "PayPal", "Square", "Braintree", "Adyen",
        "Klarna", "Affirm", "Afterpay", "Apple Pay", "Google Pay",
        "Redsys", "Bizum", "Mercado Pago"
    }
    
    CMS_PLATFORMS = {
        "WordPress", "Drupal", "Joomla", "Ghost", "Webflow",
        "Wix", "Squarespace", "Weebly", "HubSpot CMS", "Contentful"
    }
    
    ANALYTICS_TOOLS = {
        "Google Analytics", "Google Tag Manager", "Hotjar", "Mixpanel",
        "Segment", "Amplitude", "Heap", "Matomo", "Plausible"
    }
    
    MARKETING_TOOLS = {
        "Mailchimp", "Klaviyo", "HubSpot", "Intercom", "Drift",
        "Zendesk", "Crisp", "Freshdesk", "ActiveCampaign", "ConvertKit"
    }
    
    SAAS_INDICATORS = {
        "React", "Vue.js", "Angular", "Next.js", "Nuxt.js",
        "Ruby on Rails", "Django", "Laravel", "Express", "Node.js"
    }
    
    def __init__(self):
        self.pagespeed_api_key = settings.api.pagespeed_api_key
        self.pagespeed_endpoint = settings.api.pagespeed_endpoint
        self.webtech_timeout = settings.analysis.webtech_timeout
        self.executor = ThreadPoolExecutor(max_workers=settings.analysis.max_concurrent_analysis)
    
    def _run_webtech(self, url: str) -> Dict[str, Any]:
        """
        Run WebTech analysis on a URL (synchronous, runs in thread pool)
        """
        try:
            # Try using webtech as a library first
            try:
                from webtech import WebTech
                wt = WebTech(options={'json': True})
                result = wt.start_from_url(url, timeout=self.webtech_timeout)
                return result if isinstance(result, dict) else {}
            except ImportError:
                # Fallback to command line
                result = subprocess.run(
                    ["webtech", "-u", url, "--json"],
                    capture_output=True,
                    text=True,
                    timeout=self.webtech_timeout + 5
                )
                if result.stdout:
                    return json.loads(result.stdout)
                return {}
        except subprocess.TimeoutExpired:
            logger.warning(f"WebTech timeout for {url}")
            return {"error": "timeout"}
        except json.JSONDecodeError:
            logger.warning(f"WebTech JSON parse error for {url}")
            return {"error": "parse_error"}
        except Exception as e:
            logger.error(f"WebTech error for {url}: {e}")
            return {"error": str(e)}
    
    async def _analyze_with_webtech(self, url: str) -> Dict[str, Any]:
        """Async wrapper for WebTech analysis"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self._run_webtech, url)
    
    async def _analyze_with_pagespeed(self, url: str) -> Optional[PageSpeedMetrics]:
        """
        Analyze URL with Google PageSpeed Insights API
        """
        if not settings.analysis.enable_pagespeed:
            return None
        
        params = {
            "url": url,
            "key": self.pagespeed_api_key,
            "category": ["performance", "seo", "accessibility", "best-practices"],
            "strategy": "mobile"
        }
        
        try:
            async with httpx.AsyncClient(timeout=settings.analysis.pagespeed_timeout) as client:
                response = await client.get(self.pagespeed_endpoint, params=params)
                response.raise_for_status()
                data = response.json()
                
                # Extract metrics
                lighthouse = data.get("lighthouseResult", {})
                categories = lighthouse.get("categories", {})
                audits = lighthouse.get("audits", {})
                
                metrics = PageSpeedMetrics(
                    performance_score=categories.get("performance", {}).get("score", 0) * 100,
                    seo_score=categories.get("seo", {}).get("score", 0) * 100,
                    accessibility_score=categories.get("accessibility", {}).get("score", 0) * 100,
                    best_practices_score=categories.get("best-practices", {}).get("score", 0) * 100,
                    first_contentful_paint=audits.get("first-contentful-paint", {}).get("numericValue", 0) / 1000,
                    largest_contentful_paint=audits.get("largest-contentful-paint", {}).get("numericValue", 0) / 1000,
                    total_blocking_time=audits.get("total-blocking-time", {}).get("numericValue", 0),
                    cumulative_layout_shift=audits.get("cumulative-layout-shift", {}).get("numericValue", 0),
                    speed_index=audits.get("speed-index", {}).get("numericValue", 0) / 1000,
                    is_mobile_friendly=categories.get("seo", {}).get("score", 0) > 0.8,
                    has_https=url.startswith("https://")
                )
                
                return metrics
                
        except httpx.TimeoutException:
            logger.warning(f"PageSpeed timeout for {url}")
            return None
        except Exception as e:
            logger.error(f"PageSpeed error for {url}: {e}")
            return None
    
    def _parse_technologies(self, webtech_data: Dict[str, Any]) -> List[TechnologyInfo]:
        """Parse WebTech results into TechnologyInfo objects"""
        technologies = []
        
        # Handle different WebTech output formats
        tech_list = webtech_data.get("tech", [])
        if not tech_list:
            tech_list = webtech_data.get("technologies", [])
        
        for tech in tech_list:
            if isinstance(tech, dict):
                name = tech.get("name", "")
                category = tech.get("category", "Unknown")
                version = tech.get("version")
            elif isinstance(tech, str):
                name = tech
                category = "Unknown"
                version = None
            else:
                continue
            
            if name:
                technologies.append(TechnologyInfo(
                    name=name,
                    category=category,
                    version=version
                ))
        
        return technologies
    
    def _detect_business_type(self, technologies: List[TechnologyInfo]) -> tuple[Optional[str], float]:
        """
        Detect business type based on detected technologies
        Returns (business_type, confidence)
        """
        tech_names = {t.name for t in technologies}
        
        # Check for ecommerce (highest priority)
        ecommerce_matches = tech_names & self.ECOMMERCE_TECHNOLOGIES
        if ecommerce_matches:
            # Check if it's likely dropshipping
            dropshipping_indicators = {"AliExpress", "Oberlo", "Spocket", "DSers", "CJ Dropshipping"}
            if tech_names & dropshipping_indicators:
                return "dropshipping", 0.9
            return "ecommerce", 0.95
        
        # Check for payment processors (also indicates ecommerce)
        payment_matches = tech_names & self.PAYMENT_PROCESSORS
        if len(payment_matches) >= 1:
            return "ecommerce", 0.7
        
        # Check for SaaS indicators (frameworks + login patterns)
        saas_matches = tech_names & self.SAAS_INDICATORS
        if len(saas_matches) >= 2:
            # Could be SaaS or agency, need more context
            return "saas", 0.6
        
        # Check for marketing tools (often indicates agency or SaaS)
        marketing_matches = tech_names & self.MARKETING_TOOLS
        if len(marketing_matches) >= 2:
            return "agencia", 0.5
        
        # Check for CMS (could be blog, corporate, or agency)
        cms_matches = tech_names & self.CMS_PLATFORMS
        if cms_matches:
            return "corporativo", 0.4  # Default, low confidence
        
        return None, 0.0
    
    async def analyze(self, url: str, include_pagespeed: bool = True) -> WebAnalysis:
        """
        Perform complete analysis of a website
        
        Args:
            url: The URL to analyze
            include_pagespeed: Whether to include PageSpeed analysis
            
        Returns:
            WebAnalysis object with all detected information
        """
        # Ensure URL has protocol
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        
        # Extract domain
        from urllib.parse import urlparse
        domain = urlparse(url).netloc
        if domain.startswith("www."):
            domain = domain[4:]
        
        logger.info(f"Analyzing: {url}")
        
        analysis = WebAnalysis(url=url, domain=domain)
        
        # Run analyses in parallel
        tasks = [self._analyze_with_webtech(url)]
        if include_pagespeed and settings.analysis.enable_pagespeed:
            tasks.append(self._analyze_with_pagespeed(url))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process WebTech results
        webtech_data = results[0] if not isinstance(results[0], Exception) else {}
        if isinstance(webtech_data, Exception):
            analysis.analysis_errors.append(f"WebTech error: {str(webtech_data)}")
            webtech_data = {}
        elif "error" in webtech_data:
            analysis.analysis_errors.append(f"WebTech: {webtech_data['error']}")
        
        analysis.raw_webtech_data = webtech_data
        analysis.technologies = self._parse_technologies(webtech_data)
        
        # Extract specific information
        tech_names = {t.name for t in analysis.technologies}
        
        # Detect CMS
        cms_found = tech_names & self.CMS_PLATFORMS
        if cms_found:
            analysis.detected_cms = list(cms_found)[0]
        
        # Detect ecommerce platform
        ecom_found = tech_names & self.ECOMMERCE_TECHNOLOGIES
        if ecom_found:
            analysis.detected_ecommerce_platform = list(ecom_found)[0]
        
        # Check for payment processor
        analysis.has_payment_processor = bool(tech_names & self.PAYMENT_PROCESSORS)
        
        # Check for analytics
        analysis.has_analytics = bool(tech_names & self.ANALYTICS_TOOLS)
        
        # Check for marketing tools
        analysis.has_marketing_tools = bool(tech_names & self.MARKETING_TOOLS)
        
        # Detect business type
        btype, confidence = self._detect_business_type(analysis.technologies)
        analysis.detected_business_type = btype
        analysis.business_type_confidence = confidence
        
        # Process PageSpeed results if available
        if len(results) > 1 and not isinstance(results[1], Exception):
            analysis.pagespeed_metrics = results[1]
        elif len(results) > 1 and isinstance(results[1], Exception):
            analysis.analysis_errors.append(f"PageSpeed error: {str(results[1])}")
        
        logger.info(f"Analysis complete for {domain}: "
                   f"type={analysis.detected_business_type}, "
                   f"cms={analysis.detected_cms}, "
                   f"ecom={analysis.detected_ecommerce_platform}")
        
        return analysis
    
    async def analyze_batch(self, urls: List[str], 
                           include_pagespeed: bool = True,
                           max_concurrent: int = 5) -> List[WebAnalysis]:
        """
        Analyze multiple URLs concurrently
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def analyze_with_semaphore(url: str) -> WebAnalysis:
            async with semaphore:
                return await self.analyze(url, include_pagespeed)
        
        tasks = [analyze_with_semaphore(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Convert exceptions to error analyses
        analyses = []
        for url, result in zip(urls, results):
            if isinstance(result, Exception):
                analysis = WebAnalysis(url=url, domain=url)
                analysis.analysis_errors.append(str(result))
                analyses.append(analysis)
            else:
                analyses.append(result)
        
        return analyses
    
    def check_metrics_match(self, analysis: WebAnalysis, 
                           required_metrics: List[str]) -> Dict[str, bool]:
        """
        Check if analysis matches required metrics from prompt
        """
        matches = {}
        
        if not analysis.pagespeed_metrics:
            return {metric: False for metric in required_metrics}
        
        metrics = analysis.pagespeed_metrics
        
        for metric in required_metrics:
            if metric == "velocidad":
                # Consider fast if performance > 50
                matches["velocidad"] = metrics.performance_score > 50
            elif metric == "seo":
                # Consider good SEO if score > 70
                matches["seo"] = metrics.seo_score > 70
            elif metric == "mobile":
                matches["mobile"] = metrics.is_mobile_friendly
            elif metric == "accesibilidad":
                matches["accesibilidad"] = metrics.accessibility_score > 70
            elif metric == "seguridad":
                matches["seguridad"] = metrics.has_https
        
        return matches


# Factory function
def create_web_analyzer() -> WebAnalyzer:
    """Create a WebAnalyzer instance"""
    return WebAnalyzer()
