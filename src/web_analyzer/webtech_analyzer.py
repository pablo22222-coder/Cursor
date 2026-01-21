"""
Analizador de tecnologías web usando WebTech.
Detecta CMS, frameworks, e-commerce platforms, etc.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import subprocess
import json
import re


@dataclass
class TechnologyProfile:
    """Perfil tecnológico de una web."""
    domain: str
    url: str
    
    # Tecnologías detectadas por categoría
    cms: List[str] = field(default_factory=list)  # WordPress, Joomla, Drupal
    ecommerce_platform: List[str] = field(default_factory=list)  # Shopify, WooCommerce, Magento
    frameworks: List[str] = field(default_factory=list)  # React, Vue, Angular
    analytics: List[str] = field(default_factory=list)  # Google Analytics, Hotjar
    marketing: List[str] = field(default_factory=list)  # Mailchimp, HubSpot
    payment: List[str] = field(default_factory=list)  # Stripe, PayPal
    hosting: List[str] = field(default_factory=list)  # AWS, Cloudflare
    javascript_libs: List[str] = field(default_factory=list)
    
    # Todas las tecnologías detectadas (raw)
    all_technologies: List[Dict[str, Any]] = field(default_factory=list)
    
    # Indicadores de tipo de web
    is_ecommerce: bool = False
    is_saas: bool = False
    is_cms_based: bool = False
    is_custom_built: bool = False
    
    # Estado del análisis
    analysis_success: bool = False
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "url": self.url,
            "cms": self.cms,
            "ecommerce_platform": self.ecommerce_platform,
            "frameworks": self.frameworks,
            "analytics": self.analytics,
            "marketing": self.marketing,
            "payment": self.payment,
            "hosting": self.hosting,
            "javascript_libs": self.javascript_libs,
            "is_ecommerce": self.is_ecommerce,
            "is_saas": self.is_saas,
            "is_cms_based": self.is_cms_based,
            "is_custom_built": self.is_custom_built,
            "analysis_success": self.analysis_success,
            "error_message": self.error_message
        }


class WebTechAnalyzer:
    """Analiza tecnologías de sitios web usando webtech."""
    
    # Categorización de tecnologías conocidas
    ECOMMERCE_PLATFORMS = {
        "shopify", "woocommerce", "magento", "prestashop", "bigcommerce",
        "opencart", "oscommerce", "zen cart", "wix stores", "squarespace commerce",
        "ecwid", "volusion", "3dcart", "nopcommerce", "vtex", "salesforce commerce"
    }
    
    CMS_PLATFORMS = {
        "wordpress", "joomla", "drupal", "wix", "squarespace", "webflow",
        "ghost", "contentful", "strapi", "sanity", "prismic", "typo3"
    }
    
    SAAS_INDICATORS = {
        "stripe", "chargebee", "recurly", "paddle", "fastspring",
        "auth0", "okta", "firebase", "supabase", "intercom", "crisp"
    }
    
    ANALYTICS_TOOLS = {
        "google analytics", "google tag manager", "hotjar", "mixpanel",
        "amplitude", "heap", "fullstory", "mouseflow", "crazy egg", "matomo"
    }
    
    MARKETING_TOOLS = {
        "mailchimp", "klaviyo", "hubspot", "sendinblue", "convertkit",
        "drip", "activecampaign", "marketo", "pardot", "omnisend"
    }
    
    PAYMENT_PROCESSORS = {
        "stripe", "paypal", "square", "braintree", "adyen", "klarna",
        "afterpay", "affirm", "sezzle", "redsys", "bizum"
    }
    
    FRAMEWORKS = {
        "react", "vue.js", "angular", "next.js", "nuxt.js", "gatsby",
        "svelte", "ember.js", "backbone.js", "jquery", "bootstrap"
    }
    
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
    
    def analyze(self, url: str) -> TechnologyProfile:
        """
        Analiza las tecnologías de una URL.
        
        Args:
            url: URL completa del sitio a analizar
            
        Returns:
            TechnologyProfile con todas las tecnologías detectadas
        """
        # Asegurar que la URL tiene protocolo
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        
        domain = self._extract_domain(url)
        profile = TechnologyProfile(domain=domain, url=url)
        
        try:
            # Ejecutar webtech como comando
            result = subprocess.run(
                ["webtech", "-u", url, "--json"],
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            
            if result.returncode == 0 and result.stdout:
                tech_data = self._parse_webtech_output(result.stdout)
                self._categorize_technologies(profile, tech_data)
                profile.analysis_success = True
            else:
                # Intentar con método alternativo usando requests
                profile = self._analyze_with_requests(url, profile)
                
        except subprocess.TimeoutExpired:
            profile.error_message = "Timeout al analizar la web"
        except FileNotFoundError:
            # webtech no instalado, usar método alternativo
            profile = self._analyze_with_requests(url, profile)
        except Exception as e:
            profile.error_message = str(e)
        
        return profile
    
    def _parse_webtech_output(self, output: str) -> List[Dict[str, Any]]:
        """Parsea la salida JSON de webtech."""
        try:
            # webtech puede devolver múltiples objetos JSON
            lines = output.strip().split('\n')
            for line in lines:
                if line.strip().startswith('{'):
                    data = json.loads(line)
                    return data.get("tech", [])
            return []
        except json.JSONDecodeError:
            return []
    
    def _categorize_technologies(self, profile: TechnologyProfile, technologies: List[Dict[str, Any]]):
        """Categoriza las tecnologías detectadas."""
        profile.all_technologies = technologies
        
        for tech in technologies:
            name = tech.get("name", "").lower()
            
            # Categorizar
            if name in self.ECOMMERCE_PLATFORMS or any(e in name for e in self.ECOMMERCE_PLATFORMS):
                profile.ecommerce_platform.append(tech.get("name", ""))
                profile.is_ecommerce = True
                
            if name in self.CMS_PLATFORMS or any(c in name for c in self.CMS_PLATFORMS):
                profile.cms.append(tech.get("name", ""))
                profile.is_cms_based = True
                
            if name in self.SAAS_INDICATORS or any(s in name for s in self.SAAS_INDICATORS):
                profile.is_saas = True
                
            if name in self.ANALYTICS_TOOLS or any(a in name for a in self.ANALYTICS_TOOLS):
                profile.analytics.append(tech.get("name", ""))
                
            if name in self.MARKETING_TOOLS or any(m in name for m in self.MARKETING_TOOLS):
                profile.marketing.append(tech.get("name", ""))
                
            if name in self.PAYMENT_PROCESSORS or any(p in name for p in self.PAYMENT_PROCESSORS):
                profile.payment.append(tech.get("name", ""))
                profile.is_ecommerce = True  # Si tiene procesador de pago, probablemente es ecommerce
                
            if name in self.FRAMEWORKS or any(f in name for f in self.FRAMEWORKS):
                profile.frameworks.append(tech.get("name", ""))
        
        # Si no tiene CMS ni ecommerce platform conocido, puede ser custom
        if not profile.is_cms_based and not profile.is_ecommerce:
            profile.is_custom_built = True
    
    def _analyze_with_requests(self, url: str, profile: TechnologyProfile) -> TechnologyProfile:
        """Método alternativo de análisis usando requests y heurísticas."""
        import requests
        
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            response = requests.get(url, headers=headers, timeout=self.timeout, allow_redirects=True)
            html = response.text.lower()
            resp_headers = {k.lower(): v for k, v in response.headers.items()}
            
            # Detectar tecnologías por patrones en HTML y headers
            
            # E-commerce platforms
            if "shopify" in html or "cdn.shopify" in html:
                profile.ecommerce_platform.append("Shopify")
                profile.is_ecommerce = True
            if "woocommerce" in html or "wc-" in html:
                profile.ecommerce_platform.append("WooCommerce")
                profile.is_ecommerce = True
            if "magento" in html or "mage" in html:
                profile.ecommerce_platform.append("Magento")
                profile.is_ecommerce = True
            if "prestashop" in html:
                profile.ecommerce_platform.append("PrestaShop")
                profile.is_ecommerce = True
                
            # CMS
            if "wp-content" in html or "wordpress" in html:
                profile.cms.append("WordPress")
                profile.is_cms_based = True
            if "joomla" in html:
                profile.cms.append("Joomla")
                profile.is_cms_based = True
            if "drupal" in html:
                profile.cms.append("Drupal")
                profile.is_cms_based = True
                
            # Frameworks
            if "react" in html or "_next" in html or "__next" in html:
                profile.frameworks.append("React/Next.js")
            if "vue" in html or "__nuxt" in html:
                profile.frameworks.append("Vue.js")
            if "ng-" in html or "angular" in html:
                profile.frameworks.append("Angular")
                
            # Analytics
            if "google-analytics" in html or "gtag" in html or "ga(" in html:
                profile.analytics.append("Google Analytics")
            if "hotjar" in html:
                profile.analytics.append("Hotjar")
                
            # Payment (indica ecommerce)
            if "stripe" in html:
                profile.payment.append("Stripe")
                profile.is_ecommerce = True
            if "paypal" in html:
                profile.payment.append("PayPal")
                profile.is_ecommerce = True
                
            # Indicadores de ecommerce por contenido
            ecommerce_keywords = ["add to cart", "añadir al carrito", "buy now", "comprar", 
                                  "checkout", "shopping cart", "carrito de compra", "precio", "€", "$"]
            if any(kw in html for kw in ecommerce_keywords):
                profile.is_ecommerce = True
            
            profile.analysis_success = True
            
        except Exception as e:
            profile.error_message = f"Error en análisis alternativo: {str(e)}"
        
        return profile
    
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
    
    def analyze_batch(self, urls: List[str]) -> List[TechnologyProfile]:
        """
        Analiza múltiples URLs.
        
        Args:
            urls: Lista de URLs a analizar
            
        Returns:
            Lista de TechnologyProfile
        """
        results = []
        for url in urls:
            profile = self.analyze(url)
            results.append(profile)
        return results
    
    def matches_criteria(self, profile: TechnologyProfile, 
                        required_type: str = None,
                        required_techs: List[str] = None,
                        excluded_techs: List[str] = None) -> bool:
        """
        Verifica si un perfil tecnológico cumple con los criterios especificados.
        
        Args:
            profile: Perfil a verificar
            required_type: Tipo requerido (ecommerce, saas, cms)
            required_techs: Tecnologías que debe tener
            excluded_techs: Tecnologías que no debe tener
            
        Returns:
            True si cumple los criterios
        """
        # Verificar tipo
        if required_type:
            if required_type.lower() == "ecommerce" and not profile.is_ecommerce:
                return False
            if required_type.lower() == "saas" and not profile.is_saas:
                return False
            if required_type.lower() == "cms" and not profile.is_cms_based:
                return False
        
        # Verificar tecnologías requeridas
        if required_techs:
            all_techs = (profile.cms + profile.ecommerce_platform + 
                        profile.frameworks + profile.analytics + 
                        profile.marketing + profile.payment)
            all_techs_lower = [t.lower() for t in all_techs]
            
            for req in required_techs:
                if not any(req.lower() in t for t in all_techs_lower):
                    return False
        
        # Verificar tecnologías excluidas
        if excluded_techs:
            all_techs = (profile.cms + profile.ecommerce_platform + 
                        profile.frameworks + profile.analytics + 
                        profile.marketing + profile.payment)
            all_techs_lower = [t.lower() for t in all_techs]
            
            for excl in excluded_techs:
                if any(excl.lower() in t for t in all_techs_lower):
                    return False
        
        return True
