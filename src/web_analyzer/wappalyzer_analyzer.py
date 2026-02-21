"""
Analizador de tecnologías web usando Wappalyzergo (httpx-based).
Ejecuta el binario wappalyzergo via subprocess y parsea el JSON resultante.

Comando: wappalyzergo -u [URL] -td -json -fr

Wappalyzergo detecta:
- CMS (WordPress, Joomla, Drupal, etc.)
- E-commerce (Shopify, WooCommerce, Magento, etc.)
- CRM (HubSpot, Salesforce, Zoho, etc.)
- Email Marketing (Mailchimp, Klaviyo, etc.)
- Analytics (Google Analytics, Hotjar, etc.)
- Frameworks (React, Vue, Angular, etc.)
- Payment (PayPal, Stripe, etc.)
- Y muchas más tecnologías...
"""
import subprocess
import json
import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set
from urllib.parse import urlparse


@dataclass
class TechnologyInfo:
    """Información de una tecnología detectada."""
    name: str
    categories: List[str] = field(default_factory=list)
    version: Optional[str] = None
    confidence: int = 100
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "categories": self.categories,
            "version": self.version,
            "confidence": self.confidence
        }


@dataclass
class WappalyzerProfile:
    """Perfil tecnológico de una web detectado por Wappalyzer."""
    domain: str
    url: str
    
    # Todas las tecnologías detectadas
    technologies: List[TechnologyInfo] = field(default_factory=list)
    
    # Tecnologías agrupadas por categoría
    cms: List[str] = field(default_factory=list)
    ecommerce: List[str] = field(default_factory=list)
    crm: List[str] = field(default_factory=list)
    email_marketing: List[str] = field(default_factory=list)
    analytics: List[str] = field(default_factory=list)
    marketing_automation: List[str] = field(default_factory=list)
    live_chat: List[str] = field(default_factory=list)
    customer_support: List[str] = field(default_factory=list)
    payment: List[str] = field(default_factory=list)
    frameworks: List[str] = field(default_factory=list)
    javascript_libraries: List[str] = field(default_factory=list)
    hosting: List[str] = field(default_factory=list)
    cdn: List[str] = field(default_factory=list)
    security: List[str] = field(default_factory=list)
    
    # Lista plana de todos los nombres de tecnologías (para búsqueda rápida)
    all_technologies_names: List[str] = field(default_factory=list)
    
    # Indicadores booleanos
    has_crm: bool = False
    has_email_marketing: bool = False
    has_live_chat: bool = False
    has_analytics: bool = False
    has_ecommerce: bool = False
    has_cms: bool = False
    has_payment: bool = False
    
    # Estado del análisis
    analysis_success: bool = False
    error_message: Optional[str] = None
    raw_output: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "url": self.url,
            "technologies": [t.to_dict() for t in self.technologies],
            "cms": self.cms,
            "ecommerce": self.ecommerce,
            "crm": self.crm,
            "email_marketing": self.email_marketing,
            "analytics": self.analytics,
            "marketing_automation": self.marketing_automation,
            "live_chat": self.live_chat,
            "customer_support": self.customer_support,
            "payment": self.payment,
            "frameworks": self.frameworks,
            "javascript_libraries": self.javascript_libraries,
            "hosting": self.hosting,
            "cdn": self.cdn,
            "security": self.security,
            "all_technologies_names": self.all_technologies_names,
            "has_crm": self.has_crm,
            "has_email_marketing": self.has_email_marketing,
            "has_live_chat": self.has_live_chat,
            "has_analytics": self.has_analytics,
            "has_ecommerce": self.has_ecommerce,
            "has_cms": self.has_cms,
            "has_payment": self.has_payment,
            "analysis_success": self.analysis_success,
            "error_message": self.error_message
        }
    
    def has_technology(self, tech_name: str) -> bool:
        """Verifica si tiene una tecnología específica (case-insensitive)."""
        tech_lower = tech_name.lower()
        return any(tech_lower in t.lower() for t in self.all_technologies_names)
    
    def has_any_technology(self, tech_names: List[str]) -> bool:
        """Verifica si tiene alguna de las tecnologías especificadas."""
        for tech in tech_names:
            if self.has_technology(tech):
                return True
        return False
    
    def has_technology_category(self, category: str) -> bool:
        """Verifica si tiene tecnologías de una categoría específica."""
        category_lower = category.lower()
        
        category_mapping = {
            "crm": self.has_crm,
            "email": self.has_email_marketing,
            "email marketing": self.has_email_marketing,
            "chat": self.has_live_chat,
            "live chat": self.has_live_chat,
            "livechat": self.has_live_chat,
            "analytics": self.has_analytics,
            "ecommerce": self.has_ecommerce,
            "e-commerce": self.has_ecommerce,
            "cms": self.has_cms,
            "payment": self.has_payment,
            "pago": self.has_payment,
        }
        
        return category_mapping.get(category_lower, False)


class WappalyzerAnalyzer:
    """
    Analiza tecnologías de sitios web usando Wappalyzergo.
    
    Ejecuta el binario wappalyzergo via subprocess y parsea el resultado JSON.
    """
    
    # Mapeo de categorías de Wappalyzer a nuestras categorías
    CATEGORY_MAPPING = {
        # CMS
        "cms": "cms",
        "blogs": "cms",
        
        # Ecommerce
        "ecommerce": "ecommerce",
        "cart abandance": "ecommerce",
        "payment processors": "payment",
        "buy now pay later": "payment",
        
        # CRM
        "crm": "crm",
        "marketing automation": "marketing_automation",
        
        # Email Marketing
        "email": "email_marketing",
        "newsletters": "email_marketing",
        
        # Analytics
        "analytics": "analytics",
        "tag managers": "analytics",
        "a/b testing": "analytics",
        "heatmaps": "analytics",
        "session recording": "analytics",
        
        # Live Chat / Support
        "live chat": "live_chat",
        "chatbots": "live_chat",
        "customer support": "customer_support",
        "helpdesk": "customer_support",
        
        # Frameworks
        "javascript frameworks": "frameworks",
        "web frameworks": "frameworks",
        "mobile frameworks": "frameworks",
        
        # JS Libraries
        "javascript libraries": "javascript_libraries",
        "javascript graphics": "javascript_libraries",
        "ui frameworks": "javascript_libraries",
        
        # Hosting / CDN
        "paas": "hosting",
        "iaas": "hosting",
        "hosting": "hosting",
        "cdn": "cdn",
        
        # Security
        "security": "security",
        "ssl/tls certificate authorities": "security",
        "access management": "security",
    }
    
    # Tecnologías conocidas por categoría (para detección adicional por nombre)
    KNOWN_TECHNOLOGIES = {
        "crm": [
            "hubspot", "salesforce", "zoho", "pipedrive", "freshsales",
            "copper", "monday", "close", "insightly", "nimble", "zendesk sell",
            "microsoft dynamics", "sugar crm", "vtiger"
        ],
        "email_marketing": [
            "mailchimp", "klaviyo", "activecampaign", "convertkit", "sendinblue",
            "brevo", "getresponse", "drip", "constant contact", "aweber",
            "omnisend", "moosend", "mailerlite", "campaign monitor"
        ],
        "live_chat": [
            "intercom", "drift", "crisp", "zendesk", "tidio", "tawk",
            "livechat", "freshchat", "olark", "chatra", "userlike",
            "smartsupp", "customerly", "helpcrunch", "gorgias"
        ],
        "analytics": [
            "google analytics", "google tag manager", "hotjar", "mixpanel",
            "amplitude", "heap", "fullstory", "mouseflow", "crazy egg",
            "clarity", "smartlook", "matomo", "plausible", "fathom"
        ],
        "ecommerce": [
            "shopify", "woocommerce", "magento", "prestashop", "bigcommerce",
            "opencart", "vtex", "salesforce commerce", "sap commerce",
            "wix stores", "squarespace commerce", "ecwid", "volusion"
        ],
        "payment": [
            "stripe", "paypal", "square", "braintree", "adyen", "klarna",
            "afterpay", "affirm", "redsys", "bizum", "mollie", "worldpay"
        ]
    }
    
    def __init__(self, timeout: int = 30, wappalyzer_path: str = "wappalyzergo"):
        """
        Args:
            timeout: Timeout en segundos para la ejecución del binario
            wappalyzer_path: Ruta al binario wappalyzergo (default: busca en PATH)
        """
        self.timeout = timeout
        self.wappalyzer_path = wappalyzer_path
    
    def analyze(self, url: str) -> WappalyzerProfile:
        """
        Analiza las tecnologías de una URL usando wappalyzergo.
        
        Comando: wappalyzergo -u [URL] -td -json -fr
        - -u: URL a analizar
        - -td: Tech detect
        - -json: Salida en formato JSON
        - -fr: Follow redirects
        
        Args:
            url: URL a analizar
            
        Returns:
            WappalyzerProfile con todas las tecnologías detectadas
        """
        # Normalizar URL
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        
        domain = self._extract_domain(url)
        profile = WappalyzerProfile(domain=domain, url=url)
        
        try:
            # Ejecutar wappalyzergo via subprocess con nuevos flags
            # Comando: wappalyzergo -u [URL] -td -json -fr
            result = subprocess.run(
                [self.wappalyzer_path, "-u", url, "-td", "-json", "-fr"],
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            
            profile.raw_output = result.stdout
            
            if result.returncode == 0 and result.stdout:
                self._parse_wappalyzer_output(result.stdout, profile)
                profile.analysis_success = True
            else:
                # Si wappalyzergo falla, intentar análisis básico por HTML
                profile.error_message = result.stderr or "No output from wappalyzergo"
                profile = self._fallback_analysis(url, profile)
                
        except subprocess.TimeoutExpired:
            profile.error_message = f"Timeout ({self.timeout}s) al analizar {domain}"
            profile = self._fallback_analysis(url, profile)
        except FileNotFoundError:
            profile.error_message = "wappalyzergo no encontrado. Usando análisis alternativo."
            profile = self._fallback_analysis(url, profile)
        except Exception as e:
            profile.error_message = f"Error: {str(e)}"
            profile = self._fallback_analysis(url, profile)
        
        return profile
    
    def _parse_wappalyzer_output(self, output: str, profile: WappalyzerProfile):
        """
        Parsea la salida JSON de wappalyzergo.
        
        Nuevo formato esperado (httpx-based):
        {"url":"https://example.com","tech":["Varnish","HSTS","PayPal"], ...}
        
        La clave "tech" contiene un array de strings con los nombres de las tecnologías.
        """
        try:
            # El output puede tener múltiples líneas JSON, tomamos la primera válida
            lines = output.strip().split('\n')
            data = None
            
            for line in lines:
                line = line.strip()
                if line and line.startswith('{'):
                    try:
                        data = json.loads(line)
                        break
                    except json.JSONDecodeError:
                        continue
            
            if not data:
                # Intentar parsear todo el output como JSON
                data = json.loads(output.strip())
            
            # Nuevo formato: {"url":"...","tech":["Varnish","HSTS","PayPal"], ...}
            technologies = []
            
            if isinstance(data, dict):
                # Formato nuevo: tecnologías en la clave "tech" como array de strings
                if "tech" in data:
                    tech_list = data["tech"]
                    if isinstance(tech_list, list):
                        technologies = tech_list
                # Formato antiguo: mantener compatibilidad
                elif "technologies" in data:
                    technologies = data["technologies"]
                elif "apps" in data:
                    technologies = data["apps"]
            elif isinstance(data, list):
                technologies = data
            
            # Procesar cada tecnología
            for tech in technologies:
                if isinstance(tech, str):
                    # Nuevo formato: tech es un string directo (ej: "PayPal", "Varnish")
                    tech_name = tech.strip()
                    if tech_name:
                        profile.all_technologies_names.append(tech_name)
                        
                        # Crear TechnologyInfo y categorizar por nombre conocido
                        tech_info = TechnologyInfo(name=tech_name)
                        profile.technologies.append(tech_info)
                        
                        # Categorizar usando el mapeo de tecnologías conocidas
                        self._categorize_technology_by_name(tech_name, profile)
                        
                elif isinstance(tech, dict):
                    # Formato antiguo: tech es un diccionario
                    name = tech.get("name", tech.get("app", ""))
                    categories = tech.get("categories", [])
                    version = tech.get("version")
                    confidence = tech.get("confidence", 100)
                    
                    if name:
                        tech_info = TechnologyInfo(
                            name=name,
                            categories=categories if isinstance(categories, list) else [categories],
                            version=version,
                            confidence=confidence if isinstance(confidence, int) else 100
                        )
                        profile.technologies.append(tech_info)
                        profile.all_technologies_names.append(name)
                        
                        # Categorizar
                        self._categorize_technology(tech_info, profile)
            
            # Actualizar flags booleanos
            self._update_boolean_flags(profile)
            
        except json.JSONDecodeError as e:
            profile.error_message = f"Error parseando JSON: {e}"
    
    def _categorize_technology(self, tech: TechnologyInfo, profile: WappalyzerProfile):
        """Categoriza una tecnología en las listas correspondientes."""
        tech_name_lower = tech.name.lower()
        
        # Categorizar por categorías de Wappalyzer
        for category in tech.categories:
            cat_lower = category.lower() if isinstance(category, str) else ""
            mapped_category = self.CATEGORY_MAPPING.get(cat_lower)
            
            if mapped_category:
                target_list = getattr(profile, mapped_category, None)
                if target_list is not None and tech.name not in target_list:
                    target_list.append(tech.name)
        
        # Categorizar por nombre conocido
        self._categorize_technology_by_name(tech.name, profile)
    
    def _categorize_technology_by_name(self, tech_name: str, profile: WappalyzerProfile):
        """
        Categoriza una tecnología basándose solo en su nombre.
        Usado para el nuevo formato donde solo tenemos el nombre de la tecnología.
        """
        tech_name_lower = tech_name.lower()
        
        # Mapeo extendido de nombres de tecnología a categorías
        # Incluye variaciones y nombres exactos
        TECH_NAME_TO_CATEGORY = {
            # Payment
            "paypal": "payment",
            "stripe": "payment",
            "square": "payment",
            "braintree": "payment",
            "adyen": "payment",
            "klarna": "payment",
            "afterpay": "payment",
            "affirm": "payment",
            "redsys": "payment",
            "bizum": "payment",
            "mollie": "payment",
            "worldpay": "payment",
            "checkout.com": "payment",
            "razorpay": "payment",
            "mercadopago": "payment",
            "mercado pago": "payment",
            "apple pay": "payment",
            "google pay": "payment",
            "amazon pay": "payment",
            "shopify payments": "payment",
            "wepay": "payment",
            "2checkout": "payment",
            "authorize.net": "payment",
            "payu": "payment",
            "skrill": "payment",
            
            # CRM
            "hubspot": "crm",
            "salesforce": "crm",
            "zoho": "crm",
            "pipedrive": "crm",
            "freshsales": "crm",
            "copper": "crm",
            "monday": "crm",
            "close": "crm",
            "insightly": "crm",
            "nimble": "crm",
            "zendesk sell": "crm",
            "microsoft dynamics": "crm",
            "sugarcrm": "crm",
            "vtiger": "crm",
            "odoo": "crm",
            "agile crm": "crm",
            "capsule": "crm",
            "keap": "crm",
            "infusionsoft": "crm",
            
            # Email Marketing
            "mailchimp": "email_marketing",
            "klaviyo": "email_marketing",
            "activecampaign": "email_marketing",
            "convertkit": "email_marketing",
            "sendinblue": "email_marketing",
            "brevo": "email_marketing",
            "getresponse": "email_marketing",
            "drip": "email_marketing",
            "constant contact": "email_marketing",
            "aweber": "email_marketing",
            "omnisend": "email_marketing",
            "moosend": "email_marketing",
            "mailerlite": "email_marketing",
            "campaign monitor": "email_marketing",
            "sendgrid": "email_marketing",
            "mailjet": "email_marketing",
            "emma": "email_marketing",
            "dotdigital": "email_marketing",
            
            # Live Chat
            "intercom": "live_chat",
            "drift": "live_chat",
            "crisp": "live_chat",
            "zendesk chat": "live_chat",
            "zendesk": "live_chat",
            "tidio": "live_chat",
            "tawk.to": "live_chat",
            "tawk": "live_chat",
            "livechat": "live_chat",
            "freshchat": "live_chat",
            "olark": "live_chat",
            "chatra": "live_chat",
            "userlike": "live_chat",
            "smartsupp": "live_chat",
            "customerly": "live_chat",
            "helpcrunch": "live_chat",
            "gorgias": "live_chat",
            "zopim": "live_chat",
            "purechat": "live_chat",
            "jivochat": "live_chat",
            "chaport": "live_chat",
            "comm100": "live_chat",
            
            # Analytics
            "google analytics": "analytics",
            "google tag manager": "analytics",
            "gtm": "analytics",
            "ga4": "analytics",
            "hotjar": "analytics",
            "mixpanel": "analytics",
            "amplitude": "analytics",
            "heap": "analytics",
            "fullstory": "analytics",
            "mouseflow": "analytics",
            "crazy egg": "analytics",
            "microsoft clarity": "analytics",
            "clarity": "analytics",
            "smartlook": "analytics",
            "matomo": "analytics",
            "plausible": "analytics",
            "fathom": "analytics",
            "segment": "analytics",
            "piwik": "analytics",
            "clicky": "analytics",
            "statcounter": "analytics",
            "woopra": "analytics",
            "kissmetrics": "analytics",
            
            # Ecommerce
            "shopify": "ecommerce",
            "woocommerce": "ecommerce",
            "magento": "ecommerce",
            "prestashop": "ecommerce",
            "bigcommerce": "ecommerce",
            "opencart": "ecommerce",
            "vtex": "ecommerce",
            "salesforce commerce": "ecommerce",
            "sap commerce": "ecommerce",
            "wix stores": "ecommerce",
            "squarespace commerce": "ecommerce",
            "ecwid": "ecommerce",
            "volusion": "ecommerce",
            "3dcart": "ecommerce",
            "nopcommerce": "ecommerce",
            "cs-cart": "ecommerce",
            "oscommerce": "ecommerce",
            "zen cart": "ecommerce",
            "x-cart": "ecommerce",
            
            # CMS
            "wordpress": "cms",
            "joomla": "cms",
            "drupal": "cms",
            "wix": "cms",
            "squarespace": "cms",
            "webflow": "cms",
            "ghost": "cms",
            "contentful": "cms",
            "strapi": "cms",
            "sanity": "cms",
            "prismic": "cms",
            "typo3": "cms",
            "sitecore": "cms",
            "kentico": "cms",
            "umbraco": "cms",
            "hubspot cms": "cms",
            "concrete5": "cms",
            "craft cms": "cms",
            "blogger": "cms",
            "medium": "cms",
            
            # Frameworks
            "react": "frameworks",
            "vue": "frameworks",
            "vue.js": "frameworks",
            "angular": "frameworks",
            "next.js": "frameworks",
            "nuxt": "frameworks",
            "nuxt.js": "frameworks",
            "gatsby": "frameworks",
            "svelte": "frameworks",
            "ember": "frameworks",
            "backbone": "frameworks",
            "jquery": "javascript_libraries",
            "bootstrap": "frameworks",
            "tailwind": "frameworks",
            "tailwindcss": "frameworks",
            "foundation": "frameworks",
            "bulma": "frameworks",
            "materialize": "frameworks",
            
            # CDN
            "cloudflare": "cdn",
            "akamai": "cdn",
            "fastly": "cdn",
            "amazon cloudfront": "cdn",
            "cloudfront": "cdn",
            "keycdn": "cdn",
            "stackpath": "cdn",
            "bunnycdn": "cdn",
            "jsdelivr": "cdn",
            "unpkg": "cdn",
            
            # Hosting
            "aws": "hosting",
            "amazon web services": "hosting",
            "google cloud": "hosting",
            "azure": "hosting",
            "vercel": "hosting",
            "netlify": "hosting",
            "heroku": "hosting",
            "digitalocean": "hosting",
            "linode": "hosting",
            "godaddy": "hosting",
            "bluehost": "hosting",
            "siteground": "hosting",
            "wpengine": "hosting",
            "kinsta": "hosting",
            "flywheel": "hosting",
            
            # Security
            "hsts": "security",
            "cloudflare bot management": "security",
            "recaptcha": "security",
            "hcaptcha": "security",
            "auth0": "security",
            "okta": "security",
            "onelogin": "security",
            "let's encrypt": "security",
            "comodo": "security",
            "digicert": "security",
            
            # Marketing Automation
            "marketo": "marketing_automation",
            "pardot": "marketing_automation",
            "eloqua": "marketing_automation",
            "autopilot": "marketing_automation",
            "sharpspring": "marketing_automation",
            "act-on": "marketing_automation",
            
            # Customer Support
            "freshdesk": "customer_support",
            "helpscout": "customer_support",
            "help scout": "customer_support",
            "kayako": "customer_support",
            "desk.com": "customer_support",
        }
        
        # Buscar coincidencia exacta primero
        if tech_name_lower in TECH_NAME_TO_CATEGORY:
            category = TECH_NAME_TO_CATEGORY[tech_name_lower]
            target_list = getattr(profile, category, None)
            if target_list is not None and tech_name not in target_list:
                target_list.append(tech_name)
            return
        
        # Buscar coincidencia parcial
        for known_tech, category in TECH_NAME_TO_CATEGORY.items():
            if known_tech in tech_name_lower or tech_name_lower in known_tech:
                target_list = getattr(profile, category, None)
                if target_list is not None and tech_name not in target_list:
                    target_list.append(tech_name)
                return
        
        # Buscar en KNOWN_TECHNOLOGIES como fallback
        for category, known_techs in self.KNOWN_TECHNOLOGIES.items():
            if any(known in tech_name_lower for known in known_techs):
                target_list = getattr(profile, category, None)
                if target_list is not None and tech_name not in target_list:
                    target_list.append(tech_name)
                return
    
    def _update_boolean_flags(self, profile: WappalyzerProfile):
        """Actualiza los flags booleanos basándose en las listas."""
        profile.has_crm = len(profile.crm) > 0
        profile.has_email_marketing = len(profile.email_marketing) > 0 or len(profile.marketing_automation) > 0
        profile.has_live_chat = len(profile.live_chat) > 0
        profile.has_analytics = len(profile.analytics) > 0
        profile.has_ecommerce = len(profile.ecommerce) > 0
        profile.has_cms = len(profile.cms) > 0
        profile.has_payment = len(profile.payment) > 0
    
    def _fallback_analysis(self, url: str, profile: WappalyzerProfile) -> WappalyzerProfile:
        """
        Análisis de fallback usando requests cuando wappalyzergo no está disponible.
        Detecta tecnologías comunes por patrones en HTML.
        """
        import requests
        
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            response = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
            html = response.text
            
            # Detectar tecnologías por patrones
            self._detect_by_patterns(html, profile)
            self._update_boolean_flags(profile)
            profile.analysis_success = True
            
        except Exception as e:
            if not profile.error_message:
                profile.error_message = f"Fallback también falló: {e}"
        
        return profile
    
    def _detect_by_patterns(self, html: str, profile: WappalyzerProfile):
        """Detecta tecnologías por patrones en HTML."""
        html_lower = html.lower()
        
        # Patrones de detección
        patterns = {
            # CRM
            ("HubSpot", "crm"): [r"js\.hs-scripts\.com", r"js\.hsforms\.net", r"hubspot"],
            ("Salesforce", "crm"): [r"force\.com", r"salesforce\.com"],
            ("Zoho", "crm"): [r"zoho\.com", r"salesiq\.zoho"],
            ("Pipedrive", "crm"): [r"pipedrive\.com"],
            
            # Email Marketing
            ("Mailchimp", "email_marketing"): [r"mailchimp\.com", r"list-manage\.com", r"chimpstatic"],
            ("Klaviyo", "email_marketing"): [r"klaviyo\.com", r"static\.klaviyo"],
            ("ActiveCampaign", "email_marketing"): [r"activecampaign\.com", r"activehosted\.com"],
            
            # Live Chat
            ("Intercom", "live_chat"): [r"intercom\.io", r"intercomcdn\.com"],
            ("Drift", "live_chat"): [r"drift\.com", r"js\.driftt\.com"],
            ("Crisp", "live_chat"): [r"crisp\.chat", r"client\.crisp"],
            ("Zendesk", "live_chat"): [r"zendesk\.com", r"zopim\.com"],
            ("Tidio", "live_chat"): [r"tidio\.co", r"tidiochat"],
            ("Tawk", "live_chat"): [r"tawk\.to", r"embed\.tawk"],
            
            # Analytics
            ("Google Analytics", "analytics"): [r"google-analytics\.com", r"googletagmanager\.com", r"gtag\("],
            ("Hotjar", "analytics"): [r"hotjar\.com", r"static\.hotjar"],
            ("Clarity", "analytics"): [r"clarity\.ms"],
            
            # Ecommerce
            ("Shopify", "ecommerce"): [r"cdn\.shopify\.com", r"shopify\.com"],
            ("WooCommerce", "ecommerce"): [r"woocommerce", r"wc-"],
            ("Magento", "ecommerce"): [r"magento", r"mage"],
            ("PrestaShop", "ecommerce"): [r"prestashop"],
            
            # Payment
            ("Stripe", "payment"): [r"stripe\.com", r"js\.stripe"],
            ("PayPal", "payment"): [r"paypal\.com", r"paypalobjects"],
            
            # CMS
            ("WordPress", "cms"): [r"wp-content", r"wp-includes"],
            ("Joomla", "cms"): [r"joomla"],
            ("Drupal", "cms"): [r"drupal"],
            
            # Frameworks
            ("React", "frameworks"): [r"react", r"_next", r"__next"],
            ("Vue.js", "frameworks"): [r"vue\.js", r"__nuxt"],
            ("Angular", "frameworks"): [r"ng-", r"angular"],
        }
        
        for (tech_name, category), regex_patterns in patterns.items():
            for pattern in regex_patterns:
                if re.search(pattern, html_lower):
                    profile.all_technologies_names.append(tech_name)
                    target_list = getattr(profile, category, None)
                    if target_list is not None and tech_name not in target_list:
                        target_list.append(tech_name)
                    break
    
    def _extract_domain(self, url: str) -> str:
        """Extrae el dominio de una URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except:
            return url
    
    def check_technology_requirements(self, profile: WappalyzerProfile,
                                      must_have: List[str] = None,
                                      must_not: List[str] = None) -> tuple:
        """
        Verifica si el perfil cumple con los requisitos de tecnología.
        
        Args:
            profile: Perfil a verificar
            must_have: Lista de tecnologías/categorías que debe tener
            must_not: Lista de tecnologías/categorías que NO debe tener
            
        Returns:
            (cumple: bool, razon: str)
        """
        must_have = must_have or []
        must_not = must_not or []
        
        # Verificar must_have
        for required in must_have:
            required_lower = required.lower()
            
            # Verificar por nombre de tecnología
            if profile.has_technology(required):
                continue
            
            # Verificar por categoría
            if profile.has_technology_category(required):
                continue
            
            # No encontrado
            return False, f"No tiene: {required}"
        
        # Verificar must_not
        for excluded in must_not:
            excluded_lower = excluded.lower()
            
            # Verificar por nombre de tecnología
            if profile.has_technology(excluded):
                found_tech = next((t for t in profile.all_technologies_names 
                                   if excluded_lower in t.lower()), excluded)
                return False, f"Tiene {found_tech} (excluido)"
            
            # Verificar por categoría
            if profile.has_technology_category(excluded):
                # Encontrar qué tecnología de esa categoría tiene
                category_techs = {
                    "crm": profile.crm,
                    "email": profile.email_marketing,
                    "email marketing": profile.email_marketing,
                    "chat": profile.live_chat,
                    "live chat": profile.live_chat,
                    "analytics": profile.analytics,
                }.get(excluded_lower, [])
                
                if category_techs:
                    return False, f"Tiene {excluded}: {', '.join(category_techs[:2])}"
        
        return True, ""


# Función de conveniencia
def analyze_url(url: str) -> WappalyzerProfile:
    """Analiza una URL y retorna su perfil tecnológico."""
    analyzer = WappalyzerAnalyzer()
    return analyzer.analyze(url)
