"""
Parser semántico de prompts usando Gemini.
Devuelve ÚNICAMENTE un JSON estructurado con campos específicos.
"""
import json
import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import google.generativeai as genai

from config.settings import get_settings


@dataclass
class ParsedPrompt:
    """Estructura del prompt parseado."""
    prompt_original: str
    prompt_view: Optional[str]
    language: Dict[str, Any]
    intent: Dict[str, Any]
    type: Dict[str, Any]
    type_alternatives: List[Dict[str, Any]]
    service: List[str]
    niche: List[str]
    product_or_service: List[str]
    business_model: List[str]
    audience: Dict[str, Any]
    scale_hint: Dict[str, Any]
    location: Dict[str, Any]
    quality: List[Dict[str, Any]]
    must_have: List[str]
    must_not: List[str]
    technical_requirements: List[str]
    notes: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt_original": self.prompt_original,
            "prompt_view": self.prompt_view,
            "language": self.language,
            "intent": self.intent,
            "type": self.type,
            "type_alternatives": self.type_alternatives,
            "service": self.service,
            "niche": self.niche,
            "product_or_service": self.product_or_service,
            "business_model": self.business_model,
            "audience": self.audience,
            "scale_hint": self.scale_hint,
            "location": self.location,
            "quality": self.quality,
            "must_have": self.must_have,
            "must_not": self.must_not,
            "technical_requirements": self.technical_requirements,
            "notes": self.notes
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ParsedPrompt':
        return cls(
            prompt_original=data.get("prompt_original", ""),
            prompt_view=data.get("prompt_view"),
            language=data.get("language", {"label": "es", "confidence": 0.5}),
            intent=data.get("intent", {"label": "PROSPECT", "confidence": 0.5}),
            type=data.get("type", {"label": "otro", "confidence": 0.5}),
            type_alternatives=data.get("type_alternatives", []),
            service=data.get("service", []),
            niche=data.get("niche", []),
            product_or_service=data.get("product_or_service", []),
            business_model=data.get("business_model", []),
            audience=data.get("audience", {"label": "B2C", "confidence": 0.5}),
            scale_hint=data.get("scale_hint", {"label": "unknown", "confidence": 0.5}),
            location=data.get("location", {"country": None, "region": None, "city": None, "confidence": 0.0}),
            quality=data.get("quality", []),
            must_have=data.get("must_have", []),
            must_not=data.get("must_not", []),
            technical_requirements=data.get("technical_requirements", []),
            notes=data.get("notes", [])
        )


class SemanticParser:
    """
    Parser semántico que usa Gemini para analizar prompts.
    Devuelve un JSON estructurado con campos específicos.
    """
    
    # Tecnologías detectables por Wappalyzergo - organizadas por categoría
    DETECTABLE_TECHNOLOGIES = {
        "crm": [
            "hubspot", "salesforce", "zoho", "pipedrive", "freshsales",
            "copper", "monday", "close", "insightly", "nimble", "zendesk sell",
            "microsoft dynamics", "sugarcrm", "vtiger", "odoo"
        ],
        "email_marketing": [
            "mailchimp", "klaviyo", "activecampaign", "convertkit", "sendinblue",
            "brevo", "getresponse", "drip", "constant contact", "aweber",
            "omnisend", "moosend", "mailerlite", "campaign monitor", "sendgrid"
        ],
        "live_chat": [
            "intercom", "drift", "crisp", "zendesk", "tidio", "tawk",
            "livechat", "freshchat", "olark", "chatra", "userlike",
            "smartsupp", "customerly", "helpcrunch", "gorgias", "zopim"
        ],
        "analytics": [
            "google analytics", "ga4", "google tag manager", "gtm", "hotjar", "mixpanel",
            "amplitude", "heap", "fullstory", "mouseflow", "crazy egg",
            "clarity", "smartlook", "matomo", "plausible", "fathom", "segment"
        ],
        "ecommerce_platform": [
            "shopify", "woocommerce", "magento", "prestashop", "bigcommerce",
            "opencart", "vtex", "salesforce commerce", "sap commerce",
            "wix stores", "squarespace commerce", "ecwid", "volusion",
            "3dcart", "nopcommerce", "cs-cart"
        ],
        "payment": [
            "stripe", "paypal", "square", "braintree", "adyen", "klarna",
            "afterpay", "affirm", "redsys", "bizum", "mollie", "worldpay",
            "checkout.com", "razorpay", "mercado pago"
        ],
        "cms": [
            "wordpress", "joomla", "drupal", "wix", "squarespace", "webflow",
            "ghost", "contentful", "strapi", "sanity", "prismic", "typo3",
            "sitecore", "kentico", "umbraco", "hubspot cms"
        ],
        "frameworks": [
            "react", "vue", "angular", "next.js", "nuxt", "gatsby",
            "svelte", "ember", "backbone", "jquery", "bootstrap", "tailwind"
        ],
        "hosting": [
            "aws", "google cloud", "azure", "cloudflare", "vercel", "netlify",
            "heroku", "digitalocean", "linode", "godaddy", "bluehost", "siteground"
        ],
        "marketing_automation": [
            "marketo", "pardot", "eloqua", "autopilot", "drip", "infusionsoft",
            "keap", "sharpspring", "act-on"
        ],
        "ab_testing": [
            "optimizely", "vwo", "ab tasty", "google optimize", "unbounce"
        ],
        "popup_tools": [
            "optinmonster", "sumo", "privy", "sleeknote", "wisepops", "popupsmart"
        ],
        "reviews": [
            "trustpilot", "yotpo", "judge.me", "stamped", "reviews.io", "bazaarvoice"
        ]
    }
    
    # Aliases y variaciones de nombres de tecnología
    TECHNOLOGY_ALIASES = {
        "google analytics": ["ga", "analytics", "google-analytics"],
        "google tag manager": ["gtm", "tag manager"],
        "hubspot": ["hub spot", "hub-spot"],
        "mailchimp": ["mail chimp", "mail-chimp"],
        "woocommerce": ["woo commerce", "woo-commerce"],
        "shopify": ["shop-ify"],
        "wordpress": ["word press", "word-press", "wp"],
        "crm": ["gestión de clientes", "customer relationship"],
        "email marketing": ["email", "correo", "newsletter", "mailing"],
        "live chat": ["chat", "chat en vivo", "chat online", "livechat"],
        "analytics": ["analíticas", "análisis", "tracking", "rastreo"],
    }
    
    SYSTEM_PROMPT = '''Eres un parser semántico de prompts. Tu tarea es analizar el texto de entrada y devolver ÚNICAMENTE un JSON válido con la estructura exacta especificada.

REGLAS ESTRICTAS:
1. NO inventes datos que no estén implícitos en el prompt
2. Si un campo no puede inferirse con seguridad, usa null, [] o confidence baja
3. El resultado debe ser SOLO JSON válido, sin texto adicional, sin markdown, sin explicaciones
4. NO apliques normalización agresiva
5. Detecta correctamente negaciones ("sin", "no", "excluir") y colócalas en must_not
6. Diferencia claramente tipo de negocio, servicio y nicho
7. must_have y must_not son filtros duros

ESTRUCTURA JSON OBLIGATORIA (respeta EXACTAMENTE estos campos):

{
  "prompt_original": "texto exacto recibido",
  "prompt_view": "versión mínima sin perder significado o null si no es posible",
  "language": {
    "label": "es | en | multilang",
    "confidence": 0.0-1.0
  },
  "intent": {
    "label": "PROSPECT | RESEARCH | ANALYZE | EXTRACT_CONTACTS | COMPARE | MONITOR",
    "confidence": 0.0-1.0
  },
  "type": {
    "label": "agencia | ecommerce | saas | blog | marketplace | directorio | otro",
    "confidence": 0.0-1.0
  },
  "type_alternatives": [
    {"label": "string", "confidence": 0.0-1.0}
  ],
  "service": ["servicios específicos mencionados"],
  "niche": ["nichos o industrias mencionados"],
  "product_or_service": ["producto_fisico | producto_digital | software | consultoria | servicio"],
  "business_model": ["B2B | B2C | suscripcion | dropshipping | leadgen | otro"],
  "audience": {
    "label": "B2B | B2C | freelancers | pymes | empresas",
    "confidence": 0.0-1.0
  },
  "scale_hint": {
    "label": "small | medium | enterprise | unknown",
    "confidence": 0.0-1.0
  },
  "location": {
    "country": "país o null",
    "region": "región o null",
    "city": "ciudad o null",
    "confidence": 0.0-1.0
  },
  "quality": [
    {"label": "good_seo | mal_seo | low_traffic | high_traffic", "confidence": 0.0-1.0}
  ],
  "must_have": ["requisitos obligatorios - herramientas, características que DEBE tener"],
  "must_not": ["exclusiones - herramientas, características que NO debe tener"],
  "technical_requirements": ["requisitos técnicos específicos"],
  "notes": ["observaciones adicionales relevantes"]
}

GUÍA DE INTERPRETACIÓN:

intent:
- PROSPECT: buscar webs para contactar/vender (default si busca negocios)
- RESEARCH: investigar mercado/competencia
- ANALYZE: analizar características técnicas
- EXTRACT_CONTACTS: obtener datos de contacto
- COMPARE: comparar opciones
- MONITOR: seguimiento continuo

type:
- agencia: empresas de servicios profesionales
- ecommerce: tiendas online que venden productos
- saas: software como servicio
- blog: sitios de contenido/noticias
- marketplace: plataformas que conectan compradores/vendedores
- directorio: listados de empresas/servicios
- otro: no encaja en las anteriores

product_or_service:
- producto_fisico: vende bienes tangibles
- producto_digital: vende bienes digitales (ebooks, cursos)
- software: vende/ofrece software
- consultoria: servicios de asesoría
- servicio: servicios generales

TECNOLOGÍAS DETECTABLES (para must_have y must_not):
- CRM: hubspot, salesforce, zoho, pipedrive, freshsales, microsoft dynamics
- Email Marketing: mailchimp, klaviyo, activecampaign, sendinblue/brevo, getresponse
- Live Chat: intercom, drift, crisp, zendesk, tidio, tawk.to, livechat
- Analytics: google analytics, hotjar, mixpanel, amplitude, clarity, matomo
- Ecommerce: shopify, woocommerce, magento, prestashop, bigcommerce
- Payment: stripe, paypal, klarna, afterpay, redsys, bizum
- CMS: wordpress, joomla, drupal, wix, squarespace, webflow
- Marketing: optimizely, vwo, unbounce, optinmonster, sumo

IMPORTANTE para must_have/must_not:
- Si el usuario menciona "sin X" o "no X" → must_not: ["X"]
- Si el usuario menciona "con X" o "que tenga X" → must_have: ["X"]
- Si el usuario menciona una CATEGORÍA (ej: "sin CRM", "con chat") → must_not/must_have debe incluir la CATEGORÍA
- Si el usuario menciona una HERRAMIENTA específica (ej: "sin hubspot") → must_not/must_have debe incluir la herramienta

EJEMPLOS:

Prompt: "agencias de marketing digital en Madrid"
→ type: agencia, service: ["marketing digital"], location.city: "Madrid"

Prompt: "ecommerce de ropa sin shopify"
→ type: ecommerce, niche: ["moda", "ropa"], must_not: ["shopify"]

Prompt: "tiendas online sin CRM"
→ type: ecommerce, must_not: ["crm"]

Prompt: "webs con hubspot pero sin intercom"
→ must_have: ["hubspot"], must_not: ["intercom"]

Prompt: "ecommerce que no tenga chat"
→ type: ecommerce, must_not: ["chat", "live_chat"]

Prompt: "saas de gestión de proyectos para pymes"
→ type: saas, service: ["gestión de proyectos"], audience: pymes, scale_hint: small/medium

Prompt: "tiendas online con hubspot y buen seo"
→ type: ecommerce, must_have: ["hubspot"], quality: [{"label": "good_seo"}]

Responde SOLO con el JSON, nada más.'''

    def __init__(self):
        self.settings = get_settings()
        self.gemini_available = False
        self.model = None
        self.last_error = None
        
        # Intentar configurar Gemini solo si hay API key
        if self.settings.is_gemini_configured():
            try:
                genai.configure(api_key=self.settings.gemini_api_key)
                self.model = genai.GenerativeModel(self.settings.gemini_model)
                self.gemini_available = True
            except Exception as e:
                self.last_error = str(e)
                self.gemini_available = False
    
    def parse(self, prompt: str) -> ParsedPrompt:
        """
        Parsea un prompt y devuelve un JSON estructurado.
        
        Args:
            prompt: El prompt del usuario
            
        Returns:
            ParsedPrompt con toda la información extraída
        """
        # Si Gemini no está disponible, usar análisis local directamente
        if not self.gemini_available or not self.model:
            return self._local_parse_with_warning(prompt, "GEMINI_API_KEY no configurada")
        
        try:
            # Construir el prompt para Gemini
            full_prompt = f"{self.SYSTEM_PROMPT}\n\nPROMPT A ANALIZAR:\n{prompt}"
            
            response = self.model.generate_content(full_prompt)
            json_data = self._parse_response(response.text, prompt)
            
            # Marcar que fue procesado con Gemini
            if "notes" not in json_data:
                json_data["notes"] = []
            json_data["notes"].append("Análisis realizado con Gemini AI")
            
            return ParsedPrompt.from_dict(json_data)
            
        except Exception as e:
            error_msg = str(e)
            return self._handle_gemini_error(prompt, error_msg)
    
    def _handle_gemini_error(self, prompt: str, error_msg: str) -> ParsedPrompt:
        """Maneja errores de Gemini y decide qué hacer."""
        
        # Analizar el tipo de error
        warning_msg = ""
        
        if "403" in error_msg or "leaked" in error_msg.lower():
            warning_msg = "⚠️ API Key de Gemini bloqueada o inválida. Usando modo de análisis local."
        elif "429" in error_msg or "quota" in error_msg.lower():
            warning_msg = "⚠️ Límite de uso de Gemini excedido. Usando modo de análisis local."
        elif "401" in error_msg or "unauthorized" in error_msg.lower():
            warning_msg = "⚠️ API Key de Gemini no autorizada. Usando modo de análisis local."
        elif "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
            warning_msg = "⚠️ Gemini no responde (timeout). Usando modo de análisis local."
        elif "connection" in error_msg.lower() or "network" in error_msg.lower():
            warning_msg = "⚠️ Error de conexión con Gemini. Usando modo de análisis local."
        else:
            warning_msg = f"⚠️ Error con Gemini API: {error_msg[:100]}. Usando modo de análisis local."
        
        print(warning_msg)
        return self._local_parse_with_warning(prompt, warning_msg)
    
    def _local_parse_with_warning(self, prompt: str, warning: str) -> ParsedPrompt:
        """Ejecuta análisis local y añade advertencia."""
        result = self._local_parse(prompt)
        
        # Limpiar notas duplicadas y añadir advertencia
        result_dict = result.to_dict()
        result_dict["notes"] = [warning, "Análisis realizado con parser local (funcionalidad reducida)"]
        
        return ParsedPrompt.from_dict(result_dict)
    
    def _parse_response(self, response_text: str, original_prompt: str) -> Dict[str, Any]:
        """Parsea la respuesta de Gemini y valida la estructura."""
        # Limpiar el texto
        cleaned = response_text.strip()
        
        # Remover marcadores de código markdown si existen
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\n?', '', cleaned)
            cleaned = re.sub(r'\n?```$', '', cleaned)
        
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            # Intentar extraer JSON del texto
            json_match = re.search(r'\{[\s\S]*\}', cleaned)
            if json_match:
                try:
                    data = json.loads(json_match.group())
                except:
                    return self._get_empty_structure(original_prompt)
            else:
                return self._get_empty_structure(original_prompt)
        
        # Asegurar que prompt_original está correcto
        data["prompt_original"] = original_prompt
        
        # Validar y completar estructura
        data = self._validate_structure(data)
        
        return data
    
    def _validate_structure(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Valida y completa la estructura del JSON."""
        
        # Campos obligatorios con valores por defecto
        defaults = {
            "prompt_view": None,
            "language": {"label": "es", "confidence": 0.5},
            "intent": {"label": "PROSPECT", "confidence": 0.5},
            "type": {"label": "otro", "confidence": 0.5},
            "type_alternatives": [],
            "service": [],
            "niche": [],
            "product_or_service": [],
            "business_model": [],
            "audience": {"label": "B2C", "confidence": 0.5},
            "scale_hint": {"label": "unknown", "confidence": 0.5},
            "location": {"country": None, "region": None, "city": None, "confidence": 0.0},
            "quality": [],
            "must_have": [],
            "must_not": [],
            "technical_requirements": [],
            "notes": []
        }
        
        # Completar campos faltantes
        for key, default_value in defaults.items():
            if key not in data or data[key] is None:
                data[key] = default_value
        
        # Validar que los campos con confidence tengan la estructura correcta
        for field in ["language", "intent", "type", "audience", "scale_hint"]:
            if not isinstance(data.get(field), dict):
                data[field] = defaults[field]
            else:
                if "label" not in data[field]:
                    data[field]["label"] = defaults[field]["label"]
                if "confidence" not in data[field]:
                    data[field]["confidence"] = 0.5
        
        # Validar location
        if not isinstance(data.get("location"), dict):
            data["location"] = defaults["location"]
        else:
            for key in ["country", "region", "city", "confidence"]:
                if key not in data["location"]:
                    data["location"][key] = None if key != "confidence" else 0.0
        
        # Asegurar que los arrays son arrays
        for field in ["type_alternatives", "service", "niche", "product_or_service", 
                      "business_model", "quality", "must_have", "must_not", 
                      "technical_requirements", "notes"]:
            if not isinstance(data.get(field), list):
                data[field] = []
        
        return data
    
    def _get_empty_structure(self, prompt: str) -> Dict[str, Any]:
        """Retorna una estructura vacía con el prompt original."""
        return {
            "prompt_original": prompt,
            "prompt_view": None,
            "language": {"label": "es", "confidence": 0.5},
            "intent": {"label": "PROSPECT", "confidence": 0.5},
            "type": {"label": "otro", "confidence": 0.3},
            "type_alternatives": [],
            "service": [],
            "niche": [],
            "product_or_service": [],
            "business_model": [],
            "audience": {"label": "B2C", "confidence": 0.3},
            "scale_hint": {"label": "unknown", "confidence": 0.3},
            "location": {"country": None, "region": None, "city": None, "confidence": 0.0},
            "quality": [],
            "must_have": [],
            "must_not": [],
            "technical_requirements": [],
            "notes": ["Análisis realizado con fallback local"]
        }
    
    def _local_parse(self, prompt: str) -> ParsedPrompt:
        """
        Análisis local como fallback cuando Gemini no está disponible.
        """
        prompt_lower = prompt.lower()
        
        result = self._get_empty_structure(prompt)
        
        # Detectar idioma
        english_words = ["the", "and", "for", "with", "that", "agency", "store", "shop"]
        spanish_words = ["de", "para", "con", "que", "agencia", "tienda", "sin"]
        
        en_count = sum(1 for w in english_words if f" {w} " in f" {prompt_lower} ")
        es_count = sum(1 for w in spanish_words if f" {w} " in f" {prompt_lower} ")
        
        if en_count > es_count:
            result["language"] = {"label": "en", "confidence": 0.7}
        else:
            result["language"] = {"label": "es", "confidence": 0.7}
        
        # Detectar tipo de negocio
        type_patterns = {
            "ecommerce": ["ecommerce", "e-commerce", "tienda online", "tiendas online", "tienda de", 
                         "tiendas de", "shop", "store", "venta de", "vender", "comercio electrónico"],
            "agencia": ["agencia", "agency", "consultora", "consultoría", "estudio de"],
            "saas": ["saas", "software", "plataforma", "herramienta", "app de", "tool"],
            "blog": ["blog", "revista", "magazine", "portal de noticias"],
            "marketplace": ["marketplace", "mercado de"],
            "directorio": ["directorio", "listado de", "buscador de"]
        }
        
        detected_type = None
        for type_name, patterns in type_patterns.items():
            for pattern in patterns:
                if pattern in prompt_lower:
                    detected_type = type_name
                    result["type"] = {"label": type_name, "confidence": 0.8}
                    break
            if detected_type:
                break
        
        # Detectar servicios/nicho (con limpieza de palabras clave)
        service_patterns = [
            (r"(?:agencia|empresa|consultora)\s+de\s+([^,\.]+?)(?:\s+(?:en|sin|con|para)\s|$)", "service"),
            (r"(?:tienda|ecommerce|shop|tiendas)\s+(?:online\s+)?de\s+(\w+(?:\s+\w+)?)", "niche"),
            (r"(?:saas|software|plataforma|herramienta)\s+(?:de|para)\s+([^,\.]+?)(?:\s+(?:en|sin|con|para)\s|$)", "service"),
        ]
        
        # Palabras a excluir del nicho/servicio extraído
        stop_words = ["sin", "con", "en", "para", "que", "el", "la", "los", "las", "y", "o", "b2b", "b2c"]
        location_words = ["madrid", "barcelona", "españa", "spain", "mexico", "méxico", "usa", "eeuu"]
        tool_words = ["shopify", "wordpress", "hubspot", "mailchimp", "stripe", "woocommerce", "crm", "chat"]
        
        for pattern, field in service_patterns:
            match = re.search(pattern, prompt_lower)
            if match:
                extracted = match.group(1).strip()
                # Limpiar: remover palabras stop, ubicaciones y herramientas del final
                words = extracted.split()
                clean_words = []
                for word in words:
                    word_lower = word.lower()
                    if (word_lower not in stop_words and 
                        word_lower not in location_words and 
                        word_lower not in tool_words and
                        len(word) > 1):
                        clean_words.append(word)
                    elif word_lower in stop_words:
                        break  # Parar al encontrar una palabra stop
                
                if clean_words:
                    clean_extracted = " ".join(clean_words)
                    if len(clean_extracted) > 2 and clean_extracted not in result[field]:
                        result[field].append(clean_extracted)
        
        # Detectar ubicación
        location_patterns = {
            "madrid": {"city": "Madrid", "country": "España"},
            "barcelona": {"city": "Barcelona", "country": "España"},
            "españa": {"country": "España"},
            "spain": {"country": "España"},
            "méxico": {"country": "México"},
            "mexico": {"country": "México"},
            "usa": {"country": "USA"},
            "estados unidos": {"country": "USA"},
        }
        
        for loc_key, loc_data in location_patterns.items():
            if loc_key in prompt_lower:
                result["location"] = {
                    "country": loc_data.get("country"),
                    "region": loc_data.get("region"),
                    "city": loc_data.get("city"),
                    "confidence": 0.9
                }
                break
        
        # Detectar must_not (negaciones) - mejorado para tecnologías
        negation_patterns = [
            r"sin\s+(\w+(?:\s+\w+)?)",
            r"que no tenga\s+(\w+(?:\s+\w+)?)",
            r"excluir\s+(\w+(?:\s+\w+)?)",
            r"no\s+usar\s+(\w+(?:\s+\w+)?)",
            r"no\s+incluir\s+(\w+(?:\s+\w+)?)",
            r"que no use\s+(\w+(?:\s+\w+)?)",
            r"sin ningún\s+(\w+(?:\s+\w+)?)",
            r"sin ninguna\s+(\w+(?:\s+\w+)?)",
        ]
        
        # Palabras que no son herramientas/exclusiones válidas
        invalid_exclusions = ["en", "de", "para", "con", "el", "la", "los", "las", "que", "y", "o", "un", "una"]
        
        # Categorías de tecnología reconocidas
        technology_categories = {
            "crm": ["crm", "gestión de clientes", "customer relationship"],
            "chat": ["chat", "livechat", "live chat", "chat en vivo", "chat online"],
            "email_marketing": ["email marketing", "email", "mailing", "newsletter", "correo"],
            "analytics": ["analytics", "analíticas", "tracking", "rastreo"],
            "payment": ["pago", "payment", "pasarela de pago"],
        }
        
        # Todas las tecnologías conocidas en una lista plana
        all_known_techs = []
        for category_techs in self.DETECTABLE_TECHNOLOGIES.values():
            all_known_techs.extend(category_techs)
        
        for pattern in negation_patterns:
            matches = re.findall(pattern, prompt_lower)
            for match in matches:
                match_clean = match.strip().lower()
                if not match_clean or len(match_clean) < 2 or match_clean in invalid_exclusions:
                    continue
                
                # Verificar si es una categoría
                normalized = match_clean
                for cat_name, aliases in technology_categories.items():
                    if match_clean in aliases or match_clean == cat_name:
                        normalized = cat_name
                        break
                
                # Verificar si es una tecnología conocida
                for tech in all_known_techs:
                    if tech in match_clean or match_clean in tech:
                        normalized = tech
                        break
                
                if normalized not in result["must_not"]:
                    result["must_not"].append(normalized)
        
        # Detectar must_have - mejorado para tecnologías
        required_patterns = [
            r"que tenga\s+(\w+(?:\s+\w+)?)",
            r"con\s+(\w+(?:\s+\w+)?)",
            r"usando\s+(\w+(?:\s+\w+)?)",
            r"que use\s+(\w+(?:\s+\w+)?)",
            r"con el\s+(\w+(?:\s+\w+)?)",
            r"que incluya\s+(\w+(?:\s+\w+)?)",
        ]
        
        for pattern in required_patterns:
            matches = re.findall(pattern, prompt_lower)
            for match in matches:
                match_clean = match.strip().lower()
                if not match_clean or len(match_clean) < 2 or match_clean in invalid_exclusions:
                    continue
                
                # Verificar si es una categoría de tecnología
                is_technology = False
                normalized = match_clean
                
                for cat_name, aliases in technology_categories.items():
                    if match_clean in aliases or match_clean == cat_name:
                        normalized = cat_name
                        is_technology = True
                        break
                
                # Verificar si es una tecnología conocida
                for tech in all_known_techs:
                    if tech in match_clean or match_clean in tech:
                        normalized = tech
                        is_technology = True
                        break
                
                if is_technology and normalized not in result["must_have"]:
                    result["must_have"].append(normalized)
        
        # Detectar audiencia
        if any(w in prompt_lower for w in ["b2b", "empresas", "corporativo", "business"]):
            result["audience"] = {"label": "B2B", "confidence": 0.8}
        elif any(w in prompt_lower for w in ["pymes", "pequeñas empresas", "pyme"]):
            result["audience"] = {"label": "pymes", "confidence": 0.8}
        elif any(w in prompt_lower for w in ["freelance", "autónomo", "freelancer"]):
            result["audience"] = {"label": "freelancers", "confidence": 0.8}
        
        # Detectar escala
        if any(w in prompt_lower for w in ["grande", "enterprise", "corporación"]):
            result["scale_hint"] = {"label": "enterprise", "confidence": 0.7}
        elif any(w in prompt_lower for w in ["pequeña", "pequeño", "pyme", "startup"]):
            result["scale_hint"] = {"label": "small", "confidence": 0.7}
        elif any(w in prompt_lower for w in ["mediana", "mediano"]):
            result["scale_hint"] = {"label": "medium", "confidence": 0.7}
        
        # Detectar calidad
        if any(w in prompt_lower for w in ["buen seo", "bien posicionado", "good seo"]):
            result["quality"].append({"label": "good_seo", "confidence": 0.8})
        if any(w in prompt_lower for w in ["mal seo", "mal posicionado", "bad seo"]):
            result["quality"].append({"label": "mal_seo", "confidence": 0.8})
        
        # Intent por defecto
        result["intent"] = {"label": "PROSPECT", "confidence": 0.7}
        
        result["notes"].append("Análisis realizado con parser local (fallback)")
        
        return ParsedPrompt.from_dict(result)
    
    def parse_to_json(self, prompt: str) -> str:
        """
        Parsea un prompt y devuelve directamente el JSON como string.
        
        Args:
            prompt: El prompt del usuario
            
        Returns:
            JSON string con la estructura completa
        """
        parsed = self.parse(prompt)
        return json.dumps(parsed.to_dict(), ensure_ascii=False, indent=2)


def parse_prompt(prompt: str) -> ParsedPrompt:
    """Función de conveniencia para parsear un prompt."""
    parser = SemanticParser()
    return parser.parse(prompt)


def parse_prompt_to_json(prompt: str) -> str:
    """Función de conveniencia para parsear un prompt y obtener JSON."""
    parser = SemanticParser()
    return parser.parse_to_json(prompt)


def get_technology_requirements(parsed: ParsedPrompt) -> dict:
    """
    Extrae los requisitos de tecnología del prompt parseado.
    
    Returns:
        Dict con 'must_have' y 'must_not' normalizados
    """
    # Categorías conocidas
    categories = ["crm", "chat", "live_chat", "email_marketing", "email", 
                  "analytics", "ecommerce", "payment", "cms", "hosting"]
    
    def normalize_tech(tech: str) -> tuple:
        """Normaliza nombre de tecnología y determina si es categoría."""
        tech_lower = tech.lower().strip()
        
        # Verificar si es una categoría
        if tech_lower in categories:
            return tech_lower, "category"
        
        # Aliases de categorías
        category_aliases = {
            "chat": ["chat en vivo", "livechat", "chat online"],
            "crm": ["gestión de clientes"],
            "email_marketing": ["email", "mailing", "newsletter"],
            "analytics": ["analíticas", "tracking", "rastreo"],
            "payment": ["pago", "pasarela de pago"],
        }
        
        for cat, aliases in category_aliases.items():
            if tech_lower in aliases:
                return cat, "category"
        
        # Es una tecnología específica
        return tech_lower, "technology"
    
    result = {
        "must_have": [],
        "must_not": [],
        "must_have_categories": [],
        "must_not_categories": [],
    }
    
    for tech in parsed.must_have:
        normalized, tech_type = normalize_tech(tech)
        if tech_type == "category":
            if normalized not in result["must_have_categories"]:
                result["must_have_categories"].append(normalized)
        else:
            if normalized not in result["must_have"]:
                result["must_have"].append(normalized)
    
    for tech in parsed.must_not:
        normalized, tech_type = normalize_tech(tech)
        if tech_type == "category":
            if normalized not in result["must_not_categories"]:
                result["must_not_categories"].append(normalized)
        else:
            if normalized not in result["must_not"]:
                result["must_not"].append(normalized)
    
    return result
