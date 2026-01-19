"""
Analizador de tecnologías web usando WebTech.

Detecta CMS, plataformas de ecommerce, frameworks, etc.
"""
from typing import Optional, Dict, Any
from ..models.domain import TechStack, BusinessType


class TechAnalyzer:
    """
    Analiza las tecnologías de una web usando WebTech.
    
    WebTech es gratuito y sin límites, usa la misma base de datos
    que Wappalyzer para detectar tecnologías.
    """
    
    # Tecnologías que indican ecommerce
    ECOMMERCE_PLATFORMS = [
        "shopify", "woocommerce", "magento", "prestashop",
        "bigcommerce", "opencart", "wix stores", "squarespace commerce",
        "ecwid", "volusion", "3dcart", "vtex", "salesforce commerce"
    ]
    
    # Tecnologías que indican SaaS
    SAAS_INDICATORS = [
        "stripe", "chargebee", "recurly", "paddle",
        "intercom", "drift", "crisp", "zendesk"
    ]
    
    # Procesadores de pago
    PAYMENT_PROCESSORS = [
        "stripe", "paypal", "square", "braintree", "adyen",
        "klarna", "afterpay", "affirm", "redsys", "bizum"
    ]
    
    # CMS comunes
    CMS_LIST = [
        "wordpress", "drupal", "joomla", "ghost", "webflow",
        "wix", "squarespace", "weebly", "contentful", "strapi"
    ]
    
    # Herramientas de email marketing
    EMAIL_MARKETING = [
        "mailchimp", "klaviyo", "sendgrid", "mailgun",
        "constant contact", "hubspot", "activecampaign"
    ]
    
    # Analytics
    ANALYTICS_TOOLS = [
        "google analytics", "google tag manager", "hotjar",
        "mixpanel", "amplitude", "segment", "heap", "fullstory"
    ]
    
    def __init__(self, timeout: int = 5):
        """
        Inicializa el analizador.
        
        Args:
            timeout: Timeout en segundos para análisis
        """
        self.timeout = timeout
        self._webtech = None
    
    def _get_webtech(self):
        """Obtiene instancia de WebTech (lazy loading)."""
        if self._webtech is None:
            try:
                from webtech import WebTech
                self._webtech = WebTech()
            except ImportError:
                print("WebTech no está instalado. Instalar con: pip install webtech")
                return None
        return self._webtech
    
    def analyze(self, url: str) -> Optional[TechStack]:
        """
        Analiza las tecnologías de una URL.
        
        Args:
            url: URL a analizar
            
        Returns:
            TechStack con las tecnologías detectadas, o None si falla
        """
        try:
            # Asegurar que la URL tiene protocolo
            if not url.startswith(('http://', 'https://')):
                url = f"https://{url}"
            
            # Limpiar URL de parámetros problemáticos
            if '?' in url:
                base_url = url.split('?')[0]
            else:
                base_url = url
            
            # Crear nueva instancia para cada análisis
            from webtech import WebTech
            wt_instance = WebTech()
            
            # Realizar análisis - WebTech devuelve un string formateado
            results = wt_instance.start_from_url(base_url, timeout=self.timeout)
            
            return self._parse_string_results(results)
            
        except Exception as e:
            # Silenciar errores para no llenar la consola
            return None
    
    def _parse_string_results(self, results: str) -> TechStack:
        """
        Parsea los resultados de WebTech que vienen como string formateado.
        
        El formato típico es:
        Target URL: https://example.com
        Detected technologies:
            - Shopify
            - Google Analytics
        """
        import re
        
        tech_stack = TechStack()
        tech_names = []
        
        if not isinstance(results, str):
            results = str(results)
        
        # Buscar la sección "Detected technologies:"
        lines = results.split('\n')
        in_tech_section = False
        
        for line in lines:
            if 'Detected technologies:' in line:
                in_tech_section = True
                continue
            
            if in_tech_section:
                # Las tecnologías vienen con formato "	- Nombre "
                if line.strip().startswith('-'):
                    tech_name = line.strip()[1:].strip()
                    if tech_name:
                        tech_names.append(tech_name.lower())
                elif line.strip() and not line.strip().startswith('-'):
                    # Fin de la sección de tecnologías
                    if 'Detected the following' in line or 'custom headers' in line:
                        in_tech_section = False
        
        # Guardar todas las tecnologías
        tech_stack.all_technologies = {"detected": tech_names}
        
        # Clasificar tecnologías
        for name in tech_names:
            name_lower = name.lower()
            
            # Detectar CMS
            for cms in self.CMS_LIST:
                if cms in name_lower:
                    tech_stack.cms = name
                    break
            
            # Detectar plataforma ecommerce
            for platform in self.ECOMMERCE_PLATFORMS:
                if platform in name_lower:
                    tech_stack.ecommerce_platform = name
                    break
            
            # Detectar procesadores de pago
            for processor in self.PAYMENT_PROCESSORS:
                if processor in name_lower:
                    if name not in tech_stack.payment_processors:
                        tech_stack.payment_processors.append(name)
            
            # Detectar analytics
            for analytics in self.ANALYTICS_TOOLS:
                if analytics in name_lower:
                    if name not in tech_stack.analytics:
                        tech_stack.analytics.append(name)
            
            # Detectar email marketing
            for email_tool in self.EMAIL_MARKETING:
                if email_tool in name_lower:
                    if name not in tech_stack.email_marketing:
                        tech_stack.email_marketing.append(name)
        
        return tech_stack
    
    def _parse_results(self, results) -> TechStack:
        """Parsea los resultados de WebTech a TechStack."""
        tech_stack = TechStack()
        
        # WebTech puede devolver diferentes formatos
        # Intentamos obtener la lista de tecnologías
        techs = []
        
        if isinstance(results, dict):
            techs = results.get("tech", [])
        elif hasattr(results, 'techs'):
            # Si es un objeto WebTech
            techs = results.techs
        elif hasattr(results, '__iter__'):
            techs = list(results)
        
        # Normalizar nombres a minúsculas para comparación
        tech_names = []
        for tech in techs:
            if isinstance(tech, dict):
                name = tech.get("name", "").lower()
            elif hasattr(tech, 'name'):
                name = str(tech.name).lower()
            else:
                name = str(tech).lower()
            if name:
                tech_names.append(name)
        
        # Guardar todas las tecnologías raw
        tech_stack.all_technologies = {"detected": tech_names}
        
        # Clasificar tecnologías
        for name in tech_names:
            # Detectar CMS
            for cms in self.CMS_LIST:
                if cms in name:
                    tech_stack.cms = name
                    break
            
            # Detectar plataforma ecommerce
            for platform in self.ECOMMERCE_PLATFORMS:
                if platform in name:
                    tech_stack.ecommerce_platform = name
                    break
            
            # Detectar procesadores de pago
            for processor in self.PAYMENT_PROCESSORS:
                if processor in name:
                    if processor not in tech_stack.payment_processors:
                        tech_stack.payment_processors.append(name)
            
            # Detectar analytics
            for analytics in self.ANALYTICS_TOOLS:
                if analytics in name:
                    if analytics not in tech_stack.analytics:
                        tech_stack.analytics.append(name)
            
            # Detectar email marketing
            for email_tool in self.EMAIL_MARKETING:
                if email_tool in name:
                    if email_tool not in tech_stack.email_marketing:
                        tech_stack.email_marketing.append(name)
        
        return tech_stack
    
    def detect_business_type(self, tech_stack: TechStack) -> BusinessType:
        """
        Detecta el tipo de negocio basado en las tecnologías.
        
        Args:
            tech_stack: Stack tecnológico analizado
            
        Returns:
            Tipo de negocio detectado
        """
        # Si tiene plataforma de ecommerce, es ecommerce
        if tech_stack.ecommerce_platform:
            return BusinessType.ECOMMERCE
        
        # Si tiene procesadores de pago, probablemente es ecommerce o SaaS
        if tech_stack.payment_processors:
            # Verificar si tiene indicadores de SaaS
            all_techs = " ".join(tech_stack.all_technologies.get("detected", []))
            for indicator in self.SAAS_INDICATORS:
                if indicator in all_techs:
                    return BusinessType.SAAS
            
            # Si tiene pagos pero no parece SaaS, probablemente es ecommerce
            return BusinessType.ECOMMERCE
        
        # Si solo tiene WordPress sin ecommerce, puede ser blog o corporate
        if tech_stack.cms and "wordpress" in tech_stack.cms.lower():
            if not tech_stack.ecommerce_platform:
                return BusinessType.BLOG  # Podría ser corporate también
        
        return BusinessType.UNKNOWN
    
    def get_detection_reasons(self, tech_stack: TechStack, business_type: BusinessType) -> list:
        """
        Obtiene las razones por las que se detectó un tipo de negocio.
        
        Args:
            tech_stack: Stack tecnológico
            business_type: Tipo detectado
            
        Returns:
            Lista de razones
        """
        reasons = []
        
        if tech_stack.ecommerce_platform:
            reasons.append(f"Usa plataforma de ecommerce: {tech_stack.ecommerce_platform}")
        
        if tech_stack.payment_processors:
            reasons.append(f"Tiene procesadores de pago: {', '.join(tech_stack.payment_processors)}")
        
        if tech_stack.cms:
            reasons.append(f"CMS detectado: {tech_stack.cms}")
        
        if tech_stack.analytics:
            reasons.append(f"Analytics: {', '.join(tech_stack.analytics)}")
        
        if tech_stack.email_marketing:
            reasons.append(f"Email marketing: {', '.join(tech_stack.email_marketing)}")
        
        return reasons
