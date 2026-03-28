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
    
    # NUEVO: Herramientas externas detectadas
    crm: List[str] = field(default_factory=list)  # HubSpot, Salesforce, Zoho
    chat_widgets: List[str] = field(default_factory=list)  # Intercom, Drift, Crisp
    email_marketing: List[str] = field(default_factory=list)  # Mailchimp, Klaviyo
    customer_support: List[str] = field(default_factory=list)  # Zendesk, Freshdesk
    automation: List[str] = field(default_factory=list)  # Zapier, Make
    heatmaps: List[str] = field(default_factory=list)  # Hotjar, CrazyEgg
    ab_testing: List[str] = field(default_factory=list)  # Optimizely, VWO
    popup_tools: List[str] = field(default_factory=list)  # OptinMonster, Sumo
    reviews: List[str] = field(default_factory=list)  # Trustpilot, Yotpo
    
    # Todas las tecnologías detectadas (raw)
    all_technologies: List[Dict[str, Any]] = field(default_factory=list)
    
    # Lista plana de TODAS las herramientas detectadas (para filtrado fácil)
    all_tools: List[str] = field(default_factory=list)
    
    # Indicadores de tipo de web
    is_ecommerce: bool = False
    is_saas: bool = False
    is_cms_based: bool = False
    is_custom_built: bool = False
    
    # NUEVO: Indicadores de herramientas
    has_crm: bool = False
    has_chat: bool = False
    has_email_marketing: bool = False
    has_analytics: bool = False
    has_heatmaps: bool = False
    
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
            "crm": self.crm,
            "chat_widgets": self.chat_widgets,
            "email_marketing": self.email_marketing,
            "customer_support": self.customer_support,
            "automation": self.automation,
            "heatmaps": self.heatmaps,
            "ab_testing": self.ab_testing,
            "popup_tools": self.popup_tools,
            "reviews": self.reviews,
            "all_tools": self.all_tools,
            "is_ecommerce": self.is_ecommerce,
            "is_saas": self.is_saas,
            "is_cms_based": self.is_cms_based,
            "is_custom_built": self.is_custom_built,
            "has_crm": self.has_crm,
            "has_chat": self.has_chat,
            "has_email_marketing": self.has_email_marketing,
            "has_analytics": self.has_analytics,
            "has_heatmaps": self.has_heatmaps,
            "analysis_success": self.analysis_success,
            "error_message": self.error_message
        }
    
    def has_tool(self, tool_name: str) -> bool:
        """Verifica si la web tiene una herramienta específica."""
        tool_lower = tool_name.lower()
        return any(tool_lower in t.lower() for t in self.all_tools)
    
    def has_any_tool_of_type(self, tool_type: str) -> bool:
        """Verifica si tiene alguna herramienta de un tipo específico."""
        type_lower = tool_type.lower()
        if type_lower == "crm":
            return self.has_crm
        elif type_lower in ["chat", "livechat", "chat widget"]:
            return self.has_chat
        elif type_lower in ["email", "email marketing"]:
            return self.has_email_marketing
        elif type_lower in ["analytics", "analíticas"]:
            return self.has_analytics
        elif type_lower in ["heatmap", "heatmaps", "mapas de calor"]:
            return self.has_heatmaps
        return False


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
    
    # === NUEVO: Patrones de detección de herramientas externas ===
    
    # CRMs - Customer Relationship Management
    CRM_PATTERNS = {
        "hubspot": [
            r"js\.hs-scripts\.com",
            r"js\.hsforms\.net",
            r"hbspt\.",
            r"hs-banner\.com",
            r"hubspot\.com",
            r"_hsq\s*=",
            r"hs-analytics"
        ],
        "salesforce": [
            r"force\.com",
            r"salesforce\.com",
            r"pardot\.com",
            r"salesforceliveagent",
            r"sfdc\.com"
        ],
        "zoho": [
            r"zoho\.com",
            r"zohocdn\.com",
            r"salesiq\.zoho",
            r"zoho\.eu"
        ],
        "pipedrive": [
            r"pipedrive\.com",
            r"pipedrivewebforms"
        ],
        "freshsales": [
            r"freshsales\.io",
            r"freshworks\.com"
        ],
        "copper": [
            r"copper\.com",
            r"prosperworks\.com"
        ],
        "monday": [
            r"monday\.com"
        ],
        "close": [
            r"close\.com",
            r"close\.io"
        ],
        "insightly": [
            r"insightly\.com"
        ],
        "nimble": [
            r"nimble\.com"
        ]
    }
    
    # Chat Widgets / Live Chat
    CHAT_PATTERNS = {
        "intercom": [
            r"intercom\.io",
            r"intercomcdn\.com",
            r"widget\.intercom\.io",
            r"Intercom\("
        ],
        "drift": [
            r"drift\.com",
            r"js\.driftt\.com",
            r"drift\("
        ],
        "crisp": [
            r"crisp\.chat",
            r"client\.crisp\.chat",
            r"\$crisp"
        ],
        "zendesk_chat": [
            r"zopim\.com",
            r"zendesk\.com/embeddable",
            r"zE\(",
            r"zESettings"
        ],
        "tidio": [
            r"tidio\.co",
            r"tidiochat\.com"
        ],
        "tawk": [
            r"tawk\.to",
            r"embed\.tawk\.to",
            r"Tawk_API"
        ],
        "livechat": [
            r"livechatinc\.com",
            r"livechat\.com",
            r"__lc\s*="
        ],
        "freshchat": [
            r"freshchat\.com",
            r"wchat\.freshchat"
        ],
        "olark": [
            r"olark\.com",
            r"olark\.identify"
        ],
        "chatra": [
            r"chatra\.io",
            r"chatra\.com"
        ],
        "userlike": [
            r"userlike\.com"
        ],
        "smartsupp": [
            r"smartsupp\.com",
            r"smartsuppchat"
        ],
        "customerly": [
            r"customerly\.io"
        ],
        "helpcrunch": [
            r"helpcrunch\.com"
        ]
    }
    
    # Email Marketing
    EMAIL_MARKETING_PATTERNS = {
        "mailchimp": [
            r"mailchimp\.com",
            r"list-manage\.com",
            r"chimpstatic\.com",
            r"mc\.us\d+\.list-manage"
        ],
        "klaviyo": [
            r"klaviyo\.com",
            r"static\.klaviyo\.com",
            r"_learnq\s*="
        ],
        "activecampaign": [
            r"activecampaign\.com",
            r"activehosted\.com",
            r"trackcmp\.net"
        ],
        "convertkit": [
            r"convertkit\.com",
            r"convertkit-mail"
        ],
        "sendinblue": [
            r"sendinblue\.com",
            r"sibforms\.com",
            r"brevo\.com"
        ],
        "getresponse": [
            r"getresponse\.com"
        ],
        "drip": [
            r"getdrip\.com",
            r"dc\.js"
        ],
        "constant_contact": [
            r"constantcontact\.com",
            r"ctctcdn\.com"
        ],
        "aweber": [
            r"aweber\.com"
        ],
        "omnisend": [
            r"omnisend\.com",
            r"omnisrc\.com"
        ],
        "moosend": [
            r"moosend\.com"
        ]
    }
    
    # Customer Support
    SUPPORT_PATTERNS = {
        "zendesk": [
            r"zendesk\.com",
            r"zdassets\.com",
            r"zdusercontent\.com"
        ],
        "freshdesk": [
            r"freshdesk\.com",
            r"freshworks\.com"
        ],
        "helpscout": [
            r"helpscout\.net",
            r"beacon-v2\.helpscout"
        ],
        "kayako": [
            r"kayako\.com"
        ],
        "groove": [
            r"groovehq\.com"
        ]
    }
    
    # Heatmaps & Session Recording
    HEATMAP_PATTERNS = {
        "hotjar": [
            r"hotjar\.com",
            r"static\.hotjar\.com",
            r"hj\s*=\s*hj\s*\|\|",
            r"hjSiteSettings"
        ],
        "crazyegg": [
            r"crazyegg\.com",
            r"cetrk\.com"
        ],
        "fullstory": [
            r"fullstory\.com",
            r"fs\.js"
        ],
        "mouseflow": [
            r"mouseflow\.com"
        ],
        "luckyorange": [
            r"luckyorange\.com"
        ],
        "clarity": [
            r"clarity\.ms",
            r"microsoft clarity"
        ],
        "smartlook": [
            r"smartlook\.com"
        ]
    }
    
    # A/B Testing
    AB_TESTING_PATTERNS = {
        "optimizely": [
            r"optimizely\.com",
            r"cdn\.optimizely"
        ],
        "vwo": [
            r"visualwebsiteoptimizer\.com",
            r"vwo\.com",
            r"dev\.visualwebsiteoptimizer"
        ],
        "google_optimize": [
            r"googleoptimize\.com",
            r"gtm/js\?id=OPT"
        ],
        "ablyft": [
            r"ablyft\.com"
        ],
        "convert": [
            r"convert\.com"
        ]
    }
    
    # Popup & Lead Generation
    POPUP_PATTERNS = {
        "optinmonster": [
            r"optinmonster\.com",
            r"optmstr\.com"
        ],
        "sumo": [
            r"sumo\.com",
            r"sumome\.com"
        ],
        "privy": [
            r"privy\.com"
        ],
        "popupsmart": [
            r"popupsmart\.com"
        ],
        "sleeknote": [
            r"sleeknote\.com"
        ],
        "justuno": [
            r"justuno\.com"
        ],
        "wisepops": [
            r"wisepops\.com"
        ]
    }
    
    # Reviews & Social Proof
    REVIEW_PATTERNS = {
        "trustpilot": [
            r"trustpilot\.com",
            r"widget\.trustpilot"
        ],
        "yotpo": [
            r"yotpo\.com",
            r"staticw2\.yotpo"
        ],
        "bazaarvoice": [
            r"bazaarvoice\.com"
        ],
        "judge_me": [
            r"judge\.me"
        ],
        "stamped": [
            r"stamped\.io"
        ],
        "loox": [
            r"loox\.io"
        ],
        "feefo": [
            r"feefo\.com"
        ],
        "reviews_io": [
            r"reviews\.io"
        ],
        "ekomi": [
            r"ekomi\.com"
        ]
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
            html = response.text
            html_lower = html.lower()
            resp_headers = {k.lower(): v for k, v in response.headers.items()}
            
            # Detectar tecnologías por patrones en HTML y headers
            
            # E-commerce platforms
            if "shopify" in html_lower or "cdn.shopify" in html_lower:
                profile.ecommerce_platform.append("Shopify")
                profile.is_ecommerce = True
            if "woocommerce" in html_lower or "wc-" in html_lower:
                profile.ecommerce_platform.append("WooCommerce")
                profile.is_ecommerce = True
            if "magento" in html_lower or "mage" in html_lower:
                profile.ecommerce_platform.append("Magento")
                profile.is_ecommerce = True
            if "prestashop" in html_lower:
                profile.ecommerce_platform.append("PrestaShop")
                profile.is_ecommerce = True
                
            # CMS
            if "wp-content" in html_lower or "wordpress" in html_lower:
                profile.cms.append("WordPress")
                profile.is_cms_based = True
            if "joomla" in html_lower:
                profile.cms.append("Joomla")
                profile.is_cms_based = True
            if "drupal" in html_lower:
                profile.cms.append("Drupal")
                profile.is_cms_based = True
                
            # Frameworks
            if "react" in html_lower or "_next" in html_lower or "__next" in html_lower:
                profile.frameworks.append("React/Next.js")
            if "vue" in html_lower or "__nuxt" in html_lower:
                profile.frameworks.append("Vue.js")
            if "ng-" in html_lower or "angular" in html_lower:
                profile.frameworks.append("Angular")
                
            # Analytics
            if "google-analytics" in html_lower or "gtag" in html_lower or "ga(" in html_lower:
                profile.analytics.append("Google Analytics")
                profile.has_analytics = True
            if "hotjar" in html_lower:
                profile.analytics.append("Hotjar")
                profile.has_analytics = True
                
            # Payment (indica ecommerce)
            if "stripe" in html_lower:
                profile.payment.append("Stripe")
                profile.is_ecommerce = True
            if "paypal" in html_lower:
                profile.payment.append("PayPal")
                profile.is_ecommerce = True
            
            # === NUEVO: Detectar herramientas externas ===
            self._detect_external_tools(html, profile)
                
            # Indicadores de ecommerce por contenido
            ecommerce_keywords = ["add to cart", "añadir al carrito", "buy now", "comprar", 
                                  "checkout", "shopping cart", "carrito de compra", "precio", "€", "$"]
            if any(kw in html_lower for kw in ecommerce_keywords):
                profile.is_ecommerce = True
            
            # Construir lista de todas las herramientas
            self._build_all_tools_list(profile)
            
            profile.analysis_success = True
            
        except Exception as e:
            profile.error_message = f"Error en análisis alternativo: {str(e)}"
        
        return profile
    
    def _detect_external_tools(self, html: str, profile: TechnologyProfile):
        """Detecta herramientas externas (CRM, chat, email marketing, etc.)."""
        
        # Detectar CRMs
        for tool_name, patterns in self.CRM_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, html, re.IGNORECASE):
                    if tool_name.title() not in profile.crm:
                        profile.crm.append(tool_name.title())
                        profile.has_crm = True
                    break
        
        # Detectar Chat Widgets
        for tool_name, patterns in self.CHAT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, html, re.IGNORECASE):
                    if tool_name.title() not in profile.chat_widgets:
                        profile.chat_widgets.append(tool_name.title())
                        profile.has_chat = True
                    break
        
        # Detectar Email Marketing
        for tool_name, patterns in self.EMAIL_MARKETING_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, html, re.IGNORECASE):
                    if tool_name.title() not in profile.email_marketing:
                        profile.email_marketing.append(tool_name.title())
                        profile.has_email_marketing = True
                    break
        
        # Detectar Customer Support
        for tool_name, patterns in self.SUPPORT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, html, re.IGNORECASE):
                    if tool_name.title() not in profile.customer_support:
                        profile.customer_support.append(tool_name.title())
                    break
        
        # Detectar Heatmaps
        for tool_name, patterns in self.HEATMAP_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, html, re.IGNORECASE):
                    if tool_name.title() not in profile.heatmaps:
                        profile.heatmaps.append(tool_name.title())
                        profile.has_heatmaps = True
                    break
        
        # Detectar A/B Testing
        for tool_name, patterns in self.AB_TESTING_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, html, re.IGNORECASE):
                    if tool_name.title() not in profile.ab_testing:
                        profile.ab_testing.append(tool_name.title())
                    break
        
        # Detectar Popups
        for tool_name, patterns in self.POPUP_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, html, re.IGNORECASE):
                    if tool_name.title() not in profile.popup_tools:
                        profile.popup_tools.append(tool_name.title())
                    break
        
        # Detectar Reviews
        for tool_name, patterns in self.REVIEW_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, html, re.IGNORECASE):
                    if tool_name.title() not in profile.reviews:
                        profile.reviews.append(tool_name.title())
                    break
    
    def _build_all_tools_list(self, profile: TechnologyProfile):
        """Construye una lista plana de todas las herramientas detectadas."""
        all_tools = []
        
        # Añadir todas las categorías
        all_tools.extend(profile.cms)
        all_tools.extend(profile.ecommerce_platform)
        all_tools.extend(profile.frameworks)
        all_tools.extend(profile.analytics)
        all_tools.extend(profile.marketing)
        all_tools.extend(profile.payment)
        all_tools.extend(profile.crm)
        all_tools.extend(profile.chat_widgets)
        all_tools.extend(profile.email_marketing)
        all_tools.extend(profile.customer_support)
        all_tools.extend(profile.heatmaps)
        all_tools.extend(profile.ab_testing)
        all_tools.extend(profile.popup_tools)
        all_tools.extend(profile.reviews)
        
        # Eliminar duplicados manteniendo orden
        seen = set()
        profile.all_tools = []
        for tool in all_tools:
            tool_lower = tool.lower()
            if tool_lower not in seen:
                seen.add(tool_lower)
                profile.all_tools.append(tool)
    
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
