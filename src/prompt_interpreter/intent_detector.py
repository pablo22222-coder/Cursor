"""
Detector de intención del usuario.
Analiza el prompt para extraer TODA la información relevante sin inventar nada.
"""
import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any


@dataclass
class UserIntent:
    """Representa la intención completa del usuario extraída del prompt."""
    
    # === QUÉ BUSCA ===
    business_type: str = "web"  # ecommerce, saas, agencia, blog, directorio, etc.
    business_type_confidence: float = 0.0  # Confianza en la detección
    
    # === ESPECIFICACIONES DEL NEGOCIO ===
    product_category: Optional[str] = None  # Qué vende (electrónica, ropa, cosmética)
    service_type: Optional[str] = None  # Qué servicio ofrece (marketing, desarrollo)
    industry: Optional[str] = None  # Industria/sector (salud, tecnología, moda)
    
    # === CARACTERÍSTICAS ESPECÍFICAS ===
    niche: Optional[str] = None  # Nicho (luxury, eco, budget, vintage)
    style: Optional[str] = None  # Estilo (old money, minimalista, moderno)
    target_audience: Optional[str] = None  # A quién va dirigido (B2B, mujeres, jóvenes)
    price_range: Optional[str] = None  # Rango de precio (barato, premium, luxury)
    
    # === UBICACIÓN ===
    location: Optional[str] = None  # Ciudad/país específico
    location_type: Optional[str] = None  # local, nacional, internacional
    language_preference: Optional[str] = None  # es, en, etc.
    
    # === REQUISITOS TÉCNICOS ===
    platform_preference: Optional[str] = None  # Shopify, WordPress, custom
    performance_requirement: Optional[str] = None  # rápida, lenta
    mobile_requirement: bool = False
    
    # === MÉTRICAS A EVALUAR ===
    check_speed: bool = False
    check_seo: bool = False
    check_design: bool = False
    
    # === EXCLUSIONES ===
    exclusions: List[str] = field(default_factory=list)  # Lo que NO quiere
    
    # === TÉRMINOS CLAVE EXTRAÍDOS ===
    main_keywords: List[str] = field(default_factory=list)
    secondary_keywords: List[str] = field(default_factory=list)
    modifiers: List[str] = field(default_factory=list)
    
    # === METADATA ===
    original_prompt: str = ""
    detected_language: str = "es"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "business_type": self.business_type,
            "business_type_confidence": self.business_type_confidence,
            "product_category": self.product_category,
            "service_type": self.service_type,
            "industry": self.industry,
            "niche": self.niche,
            "style": self.style,
            "target_audience": self.target_audience,
            "price_range": self.price_range,
            "location": self.location,
            "location_type": self.location_type,
            "platform_preference": self.platform_preference,
            "performance_requirement": self.performance_requirement,
            "check_speed": self.check_speed,
            "check_seo": self.check_seo,
            "exclusions": self.exclusions,
            "main_keywords": self.main_keywords,
            "secondary_keywords": self.secondary_keywords,
            "modifiers": self.modifiers,
            "original_prompt": self.original_prompt,
            "detected_language": self.detected_language
        }
    
    def get_search_term(self) -> str:
        """Retorna el término principal de búsqueda."""
        if self.product_category:
            return self.product_category
        if self.service_type:
            return self.service_type
        if self.main_keywords:
            return " ".join(self.main_keywords[:2])
        return self.original_prompt


class IntentDetector:
    """
    Detecta la intención del usuario analizando el prompt.
    NO inventa información - solo extrae lo que está en el prompt.
    """
    
    # === PATRONES DE TIPO DE NEGOCIO ===
    BUSINESS_PATTERNS = {
        "ecommerce": {
            "keywords": ["ecommerce", "e-commerce", "tienda online", "tienda", "shop", 
                        "store", "venta online", "vender", "comprar", "comercio electrónico"],
            "strong_indicators": ["tienda de", "shop de", "venta de", "ecommerce de"],
            "confidence": 0.9
        },
        "saas": {
            "keywords": ["saas", "software", "plataforma", "herramienta", "tool", 
                        "aplicación", "app", "sistema", "solución"],
            "strong_indicators": ["software de", "plataforma de", "herramienta de", "app de"],
            "confidence": 0.85
        },
        "agencia": {
            "keywords": ["agencia", "agency", "consultora", "consultoría", "estudio",
                        "empresa de servicios", "despacho"],
            "strong_indicators": ["agencia de", "consultoría de", "estudio de"],
            "confidence": 0.9
        },
        "marketplace": {
            "keywords": ["marketplace", "mercado", "plataforma de venta", "portal de compra"],
            "strong_indicators": ["marketplace de"],
            "confidence": 0.85
        },
        "blog": {
            "keywords": ["blog", "revista", "magazine", "portal de noticias", "medio digital"],
            "strong_indicators": ["blog de", "revista de"],
            "confidence": 0.8
        },
        "directorio": {
            "keywords": ["directorio", "listado", "buscador de", "comparador"],
            "strong_indicators": ["directorio de", "listado de"],
            "confidence": 0.8
        },
        "portfolio": {
            "keywords": ["portfolio", "portafolio", "trabajos", "proyectos"],
            "strong_indicators": ["portfolio de"],
            "confidence": 0.75
        },
        "landing": {
            "keywords": ["landing", "landing page", "página de aterrizaje", "página de venta"],
            "strong_indicators": ["landing de"],
            "confidence": 0.7
        },
        "webapp": {
            "keywords": ["webapp", "web app", "aplicación web"],
            "strong_indicators": ["webapp de", "aplicación web de"],
            "confidence": 0.8
        }
    }
    
    # === PATRONES DE INDUSTRIA/SECTOR ===
    INDUSTRY_PATTERNS = {
        "tecnología": ["tech", "tecnología", "informática", "software", "digital", "it"],
        "moda": ["moda", "fashion", "ropa", "vestimenta", "textil", "calzado", "zapatos"],
        "belleza": ["belleza", "cosmética", "cosméticos", "maquillaje", "skincare", "cuidado personal"],
        "salud": ["salud", "health", "medicina", "médico", "farmacia", "bienestar", "wellness"],
        "alimentación": ["alimentación", "comida", "food", "gastronomía", "restaurante", "bebidas"],
        "hogar": ["hogar", "casa", "decoración", "muebles", "mobiliario", "interiorismo"],
        "deportes": ["deporte", "sports", "fitness", "gym", "ejercicio", "athletic"],
        "educación": ["educación", "formación", "cursos", "academia", "escuela", "universidad"],
        "finanzas": ["finanzas", "finance", "banca", "inversión", "trading", "crypto", "seguros"],
        "inmobiliaria": ["inmobiliaria", "real estate", "propiedades", "vivienda", "alquiler"],
        "turismo": ["turismo", "viajes", "travel", "hotel", "vuelos", "vacaciones"],
        "automoción": ["coches", "autos", "vehículos", "automotive", "motor", "concesionario"],
        "electrónica": ["electrónica", "electronics", "gadgets", "dispositivos", "tecnología"],
        "mascotas": ["mascotas", "pets", "animales", "veterinario"],
        "infantil": ["infantil", "niños", "bebé", "baby", "kids", "juguetes"],
        "arte": ["arte", "art", "artístico", "galería", "creatividad"],
        "música": ["música", "music", "instrumentos", "audio"],
        "gaming": ["gaming", "videojuegos", "juegos", "esports", "gamer"],
    }
    
    # === PATRONES DE NICHO/ESTILO ===
    NICHE_PATTERNS = {
        "luxury": {
            "keywords": ["lujo", "luxury", "premium", "exclusivo", "high-end", "alta gama"],
            "price_indicator": "alto"
        },
        "budget": {
            "keywords": ["barato", "económico", "low cost", "asequible", "precio bajo", "ofertas"],
            "price_indicator": "bajo"
        },
        "eco": {
            "keywords": ["ecológico", "eco", "sostenible", "sustainable", "natural", "orgánico", 
                        "bio", "verde", "eco-friendly", "vegano", "cruelty-free"],
            "price_indicator": None
        },
        "vintage": {
            "keywords": ["vintage", "retro", "antiguo", "clásico", "second hand", "segunda mano"],
            "price_indicator": None
        },
        "artesanal": {
            "keywords": ["artesanal", "handmade", "hecho a mano", "artesano", "craft"],
            "price_indicator": None
        },
        "profesional": {
            "keywords": ["profesional", "enterprise", "empresarial", "corporativo", "business"],
            "price_indicator": None
        },
        "startup": {
            "keywords": ["startup", "emprendedor", "pyme", "pequeña empresa", "nuevo negocio"],
            "price_indicator": None
        },
        "minimalista": {
            "keywords": ["minimalista", "minimal", "simple", "clean", "sencillo"],
            "price_indicator": None
        },
        "old_money": {
            "keywords": ["old money", "clásico elegante", "tradicional", "heritage", "preppy"],
            "price_indicator": "alto"
        },
        "streetwear": {
            "keywords": ["streetwear", "urban", "urbano", "street style", "casual"],
            "price_indicator": None
        },
        "boho": {
            "keywords": ["boho", "bohemio", "hippie", "étnico", "tribal"],
            "price_indicator": None
        }
    }
    
    # === PATRONES DE AUDIENCIA ===
    AUDIENCE_PATTERNS = {
        "b2b": ["b2b", "empresas", "negocios", "corporativo", "business to business", "profesionales"],
        "b2c": ["b2c", "consumidores", "particulares", "clientes finales"],
        "mujeres": ["mujeres", "mujer", "femenino", "para ella", "women", "female"],
        "hombres": ["hombres", "hombre", "masculino", "para él", "men", "male"],
        "jóvenes": ["jóvenes", "juvenil", "teens", "adolescentes", "millennials", "gen z"],
        "adultos": ["adultos", "mayores", "senior", "tercera edad"],
        "familias": ["familias", "familiar", "family", "niños y padres"],
        "profesionales": ["profesionales", "expertos", "especialistas"],
    }
    
    # === UBICACIONES ===
    LOCATION_PATTERNS = {
        # España
        "españa": ["españa", "spain", "spanish", "español"],
        "madrid": ["madrid", "madrileño"],
        "barcelona": ["barcelona", "bcn", "cataluña"],
        "valencia": ["valencia", "valenciano"],
        "sevilla": ["sevilla", "andalucía"],
        "bilbao": ["bilbao", "país vasco", "euskadi"],
        "málaga": ["málaga", "costa del sol"],
        # Latinoamérica
        "méxico": ["méxico", "mexico", "mexicano", "cdmx", "df"],
        "argentina": ["argentina", "argentino", "buenos aires"],
        "colombia": ["colombia", "colombiano", "bogotá", "medellín"],
        "chile": ["chile", "chileno", "santiago"],
        "perú": ["perú", "peru", "peruano", "lima"],
        # Otros
        "usa": ["usa", "estados unidos", "eeuu", "american", "us"],
        "uk": ["uk", "reino unido", "british", "london", "londres"],
        "europa": ["europa", "european", "eu"],
        "latam": ["latam", "latinoamérica", "hispanoamérica"],
    }
    
    # === REQUISITOS TÉCNICOS/RENDIMIENTO ===
    TECH_PATTERNS = {
        "shopify": ["shopify"],
        "wordpress": ["wordpress", "wp", "woocommerce"],
        "magento": ["magento"],
        "prestashop": ["prestashop"],
        "custom": ["custom", "personalizado", "a medida"],
        "wix": ["wix"],
        "squarespace": ["squarespace"],
    }
    
    PERFORMANCE_PATTERNS = {
        "rápida": ["rápida", "rápido", "fast", "veloz", "velocidad alta", "carga rápida"],
        "lenta": ["lenta", "lento", "slow", "carga lenta", "velocidad baja"],
    }
    
    def __init__(self):
        pass
    
    def detect(self, prompt: str) -> UserIntent:
        """
        Analiza el prompt y extrae toda la información de intención.
        
        Args:
            prompt: El prompt del usuario
            
        Returns:
            UserIntent con toda la información extraída
        """
        intent = UserIntent(original_prompt=prompt)
        prompt_lower = prompt.lower().strip()
        
        # Detectar idioma
        intent.detected_language = self._detect_language(prompt_lower)
        
        # 1. Detectar tipo de negocio
        business_type, confidence = self._detect_business_type(prompt_lower)
        intent.business_type = business_type
        intent.business_type_confidence = confidence
        
        # 2. Extraer producto/servicio específico
        intent.product_category, intent.service_type = self._extract_product_service(
            prompt_lower, business_type
        )
        
        # 3. Detectar industria
        intent.industry = self._detect_industry(prompt_lower)
        
        # 4. Detectar nicho y estilo
        intent.niche, intent.style, intent.price_range = self._detect_niche_style(prompt_lower)
        
        # 5. Detectar audiencia objetivo
        intent.target_audience = self._detect_audience(prompt_lower)
        
        # 6. Detectar ubicación
        intent.location, intent.location_type = self._detect_location(prompt_lower)
        
        # 7. Detectar requisitos técnicos
        intent.platform_preference = self._detect_platform(prompt_lower)
        intent.performance_requirement = self._detect_performance(prompt_lower)
        
        # 8. Detectar si hay requisitos de métricas
        intent.check_speed = any(word in prompt_lower for word in 
                                 ["velocidad", "speed", "rendimiento", "performance", "carga"])
        intent.check_seo = any(word in prompt_lower for word in 
                              ["seo", "posicionamiento", "ranking", "google"])
        
        # 9. Extraer keywords principales
        intent.main_keywords, intent.secondary_keywords = self._extract_keywords(
            prompt_lower, intent
        )
        
        # 10. Extraer modificadores
        intent.modifiers = self._extract_modifiers(prompt_lower)
        
        return intent
    
    def _detect_language(self, prompt: str) -> str:
        """Detecta el idioma del prompt."""
        english_indicators = ["the", "and", "for", "with", "that", "shop", "store", "agency"]
        spanish_indicators = ["de", "para", "con", "que", "tienda", "agencia", "empresa"]
        
        en_count = sum(1 for word in english_indicators if f" {word} " in f" {prompt} ")
        es_count = sum(1 for word in spanish_indicators if f" {word} " in f" {prompt} ")
        
        return "en" if en_count > es_count else "es"
    
    def _detect_business_type(self, prompt: str) -> Tuple[str, float]:
        """Detecta el tipo de negocio con nivel de confianza."""
        best_match = ("web", 0.3)  # Default
        
        for btype, patterns in self.BUSINESS_PATTERNS.items():
            # Verificar indicadores fuertes primero
            for indicator in patterns["strong_indicators"]:
                if indicator in prompt:
                    return (btype, patterns["confidence"])
            
            # Verificar keywords
            for keyword in patterns["keywords"]:
                if keyword in prompt:
                    confidence = patterns["confidence"] * 0.85
                    if confidence > best_match[1]:
                        best_match = (btype, confidence)
        
        return best_match
    
    def _extract_product_service(self, prompt: str, business_type: str) -> Tuple[Optional[str], Optional[str]]:
        """Extrae el producto o servicio específico del prompt."""
        product = None
        service = None
        
        # Patrones para extraer lo que viene después de palabras clave
        extraction_patterns = [
            # "tienda de X", "ecommerce de X", "shop de X"
            r"(?:tienda|ecommerce|e-commerce|shop|store|venta)\s+(?:online\s+)?(?:de\s+)?([^,\.\-]+?)(?:\s+online|\s+en\s+|\s+con\s+|$)",
            # "agencia de X", "consultoría de X"
            r"(?:agencia|agency|consultor[ií]a|estudio|empresa)\s+(?:de\s+)?([^,\.\-]+?)(?:\s+en\s+|\s+con\s+|$)",
            # "software de X", "plataforma de X", "herramienta de X"
            r"(?:software|plataforma|herramienta|app|saas|sistema)\s+(?:de|para)\s+([^,\.\-]+?)(?:\s+online|\s+con\s+|$)",
            # "X online", "X shop"
            r"([^,\.\-]+?)\s+(?:online|shop|store|tienda)(?:\s|$)",
        ]
        
        for pattern in extraction_patterns:
            match = re.search(pattern, prompt, re.IGNORECASE)
            if match:
                extracted = match.group(1).strip()
                # Limpiar el texto extraído
                extracted = re.sub(r'\s+', ' ', extracted)
                extracted = extracted.strip()
                
                if len(extracted) > 2 and len(extracted) < 50:
                    if business_type in ["ecommerce", "marketplace"]:
                        product = extracted
                    else:
                        service = extracted
                    break
        
        return product, service
    
    def _detect_industry(self, prompt: str) -> Optional[str]:
        """Detecta la industria/sector del prompt."""
        for industry, keywords in self.INDUSTRY_PATTERNS.items():
            for keyword in keywords:
                if keyword in prompt:
                    return industry
        return None
    
    def _detect_niche_style(self, prompt: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Detecta nicho, estilo y rango de precio."""
        niche = None
        style = None
        price_range = None
        
        for niche_name, data in self.NICHE_PATTERNS.items():
            for keyword in data["keywords"]:
                if keyword in prompt:
                    niche = niche_name
                    if data.get("price_indicator"):
                        price_range = data["price_indicator"]
                    # Algunos nichos también indican estilo
                    if niche_name in ["old_money", "minimalista", "streetwear", "boho", "vintage"]:
                        style = niche_name
                    break
            if niche:
                break
        
        return niche, style, price_range
    
    def _detect_audience(self, prompt: str) -> Optional[str]:
        """Detecta la audiencia objetivo."""
        for audience, keywords in self.AUDIENCE_PATTERNS.items():
            for keyword in keywords:
                if keyword in prompt:
                    return audience
        return None
    
    def _detect_location(self, prompt: str) -> Tuple[Optional[str], Optional[str]]:
        """Detecta ubicación y tipo de ubicación."""
        location = None
        location_type = None
        
        for loc_name, keywords in self.LOCATION_PATTERNS.items():
            for keyword in keywords:
                if keyword in prompt:
                    location = loc_name
                    # Determinar tipo
                    if loc_name in ["españa", "méxico", "argentina", "colombia", "usa", "uk"]:
                        location_type = "nacional"
                    elif loc_name in ["europa", "latam"]:
                        location_type = "regional"
                    else:
                        location_type = "local"
                    break
            if location:
                break
        
        return location, location_type
    
    def _detect_platform(self, prompt: str) -> Optional[str]:
        """Detecta preferencia de plataforma técnica."""
        for platform, keywords in self.TECH_PATTERNS.items():
            for keyword in keywords:
                if keyword in prompt:
                    return platform
        return None
    
    def _detect_performance(self, prompt: str) -> Optional[str]:
        """Detecta requisitos de rendimiento."""
        for perf, keywords in self.PERFORMANCE_PATTERNS.items():
            for keyword in keywords:
                if keyword in prompt:
                    return perf
        return None
    
    def _extract_keywords(self, prompt: str, intent: UserIntent) -> Tuple[List[str], List[str]]:
        """Extrae keywords principales y secundarias."""
        main_keywords = []
        secondary_keywords = []
        
        # El producto/servicio es keyword principal
        if intent.product_category:
            main_keywords.append(intent.product_category)
        if intent.service_type:
            main_keywords.append(intent.service_type)
        
        # La industria es secundaria
        if intent.industry:
            secondary_keywords.append(intent.industry)
        
        # El nicho/estilo es secundario
        if intent.niche:
            # Buscar el keyword específico del nicho que está en el prompt
            if intent.niche in self.NICHE_PATTERNS:
                for kw in self.NICHE_PATTERNS[intent.niche]["keywords"]:
                    if kw in prompt:
                        secondary_keywords.append(kw)
                        break
        
        return main_keywords, secondary_keywords
    
    def _extract_modifiers(self, prompt: str) -> List[str]:
        """Extrae modificadores del prompt (palabras que modifican la búsqueda)."""
        modifiers = []
        
        # Modificadores de calidad
        quality_mods = ["mejor", "mejores", "top", "bueno", "buenos", "profesional", 
                       "especializado", "especializada", "recomendado", "popular"]
        for mod in quality_mods:
            if mod in prompt:
                modifiers.append(mod)
        
        # Modificadores de tiempo
        time_mods = ["2024", "2025", "nuevo", "nuevos", "actual", "moderno"]
        for mod in time_mods:
            if mod in prompt:
                modifiers.append(mod)
        
        return modifiers


def detect_intent(prompt: str) -> UserIntent:
    """Función de conveniencia para detectar intención."""
    detector = IntentDetector()
    return detector.detect(prompt)
