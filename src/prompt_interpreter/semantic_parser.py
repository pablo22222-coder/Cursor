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

EJEMPLOS:

Prompt: "agencias de marketing digital en Madrid"
→ type: agencia, service: ["marketing digital"], location.city: "Madrid"

Prompt: "ecommerce de ropa sin shopify"
→ type: ecommerce, niche: ["moda", "ropa"], must_not: ["shopify"]

Prompt: "saas de gestión de proyectos para pymes"
→ type: saas, service: ["gestión de proyectos"], audience: pymes, scale_hint: small/medium

Prompt: "tiendas online con hubspot y buen seo"
→ type: ecommerce, must_have: ["hubspot"], quality: [{"label": "good_seo"}]

Responde SOLO con el JSON, nada más.'''

    def __init__(self):
        settings = get_settings()
        genai.configure(api_key=settings.gemini_api_key)
        self.model = genai.GenerativeModel(settings.gemini_model)
    
    def parse(self, prompt: str) -> ParsedPrompt:
        """
        Parsea un prompt y devuelve un JSON estructurado.
        
        Args:
            prompt: El prompt del usuario
            
        Returns:
            ParsedPrompt con toda la información extraída
        """
        try:
            # Construir el prompt para Gemini
            full_prompt = f"{self.SYSTEM_PROMPT}\n\nPROMPT A ANALIZAR:\n{prompt}"
            
            response = self.model.generate_content(full_prompt)
            json_data = self._parse_response(response.text, prompt)
            
            return ParsedPrompt.from_dict(json_data)
            
        except Exception as e:
            print(f"Error en SemanticParser con Gemini: {e}")
            # Fallback a análisis local
            return self._local_parse(prompt)
    
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
        
        # Detectar must_not (negaciones)
        negation_patterns = [
            r"sin\s+(\w+)",
            r"que no tenga\s+(\w+(?:\s+\w+)?)",
            r"excluir\s+(\w+(?:\s+\w+)?)",
            r"no\s+usar\s+(\w+)",
            r"no\s+incluir\s+(\w+)",
        ]
        
        # Palabras que no son herramientas/exclusiones válidas
        invalid_exclusions = ["en", "de", "para", "con", "el", "la", "los", "las", "que", "y", "o"]
        
        for pattern in negation_patterns:
            matches = re.findall(pattern, prompt_lower)
            for match in matches:
                match_clean = match.strip().lower()
                if match_clean and len(match_clean) > 2 and match_clean not in invalid_exclusions:
                    result["must_not"].append(match_clean)
        
        # Detectar must_have
        required_patterns = [
            r"que tenga\s+(\w+(?:\s+\w+)?)",
            r"con\s+(\w+(?:\s+\w+)?)",
            r"usando\s+(\w+(?:\s+\w+)?)",
        ]
        
        known_tools = ["hubspot", "salesforce", "shopify", "wordpress", "mailchimp", 
                       "klaviyo", "intercom", "stripe", "paypal", "woocommerce"]
        
        for pattern in required_patterns:
            matches = re.findall(pattern, prompt_lower)
            for match in matches:
                match_lower = match.strip().lower()
                if any(tool in match_lower for tool in known_tools):
                    result["must_have"].append(match.strip())
        
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
