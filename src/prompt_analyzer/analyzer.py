"""
Analizador de prompts - Interpreta qué tipo de web busca el usuario.

Este módulo es CRÍTICO para resolver el problema principal:
- Distinguir entre "webs que hablen de X" vs "webs que SEAN X"
- Extraer especificaciones del prompt (tipo de producto, nicho, etc.)
"""
import re
from typing import List, Tuple, Optional, Dict
from ..models.domain import PromptIntent, BusinessType


class PromptNormalizer:
    """
    Normaliza ortografía y semántica del prompt.
    
    FILOSOFÍA: Asumir errores humanos como norma, no como excepción.
    No corregimos el texto visible, corregimos la interpretación interna.
    """
    
    # Errores ortográficos comunes → corrección interna
    SPELLING_CORRECTIONS = {
        # Ecommerce y variantes
        "ecomerce": "ecommerce",
        "e-comerce": "ecommerce",
        "ecommerse": "ecommerce",
        "eccomerce": "ecommerce",
        "e-commerce": "ecommerce",
        "e commerce": "ecommerce",
        "icommerce": "ecommerce",
        "cormercio electronico": "ecommerce",
        "comercio electronico": "ecommerce",
        
        # Tienda y variantes
        "tinda": "tienda",
        "tiena": "tienda",
        "teinda": "tienda",
        "tienfa": "tienda",
        
        # Marketing y variantes
        "marqueting": "marketing",
        "marketin": "marketing",
        "markting": "marketing",
        "maketing": "marketing",
        "mkt": "marketing",
        
        # Digital y variantes
        "dijital": "digital",
        "digtal": "digital",
        "digitl": "digital",
        
        # Agencia y variantes
        "agncia": "agencia",
        "agenca": "agencia",
        "ajencia": "agencia",
        
        # Electrónica y variantes
        "eletronica": "electronica",
        "electronica": "electronica",
        "elctronica": "electronica",
        "electronca": "electronica",
        
        # Ropa y moda
        "rropa": "ropa",
        "rpoa": "ropa",
        "fasion": "moda",
        "fachion": "moda",
        "fashion": "moda",
        
        # Software/SaaS
        "sofware": "software",
        "sotfware": "software",
        "softwre": "software",
        "sas": "saas",
        "sass": "saas",
        
        # Dropshipping
        "dropshiping": "dropshipping",
        "drop shipping": "dropshipping",
        "drop shiping": "dropshipping",
        "dropsipping": "dropshipping",
        
        # Tecnologías comunes
        "shopfy": "shopify",
        "shoppify": "shopify",
        "sopify": "shopify",
        "woocomerce": "woocommerce",
        "woo commerce": "woocommerce",
        "wodpress": "wordpress",
        "wordpres": "wordpress",
        "word press": "wordpress",
        "mailchim": "mailchimp",
        "mailchip": "mailchimp",
        "mail chimp": "mailchimp",
        "stripe": "stripe",
        "paypa": "paypal",
        "pay pal": "paypal",
        
        # Países/ubicaciones
        "espana": "españa",
        "espania": "españa",
        "mejico": "mexico",
        "mexco": "mexico",
        
        # Otros términos comunes
        "joyeria": "joyeria",
        "jolleria": "joyeria",
        "bellesa": "belleza",
        "beleza": "belleza",
        "cosmetica": "cosmetica",
        "cosmetca": "cosmetica",
        "tecnolojia": "tecnologia",
        "tecnologua": "tecnologia",
    }
    
    # Sinónimos semánticos → término normalizado interno
    SEMANTIC_SYNONYMS = {
        # Tienda online
        "shop": "tienda",
        "store": "tienda",
        "boutique": "tienda",
        "almacen": "tienda",
        "comercio": "tienda",
        
        # Ecommerce
        "tienda online": "ecommerce",
        "tienda virtual": "ecommerce",
        "tienda en linea": "ecommerce",
        "tienda en línea": "ecommerce",
        "negocio online": "ecommerce",
        "venta online": "ecommerce",
        
        # Ropa/Moda
        "ropa": "moda",
        "textil": "moda",
        "prendas": "moda",
        "vestimenta": "moda",
        "indumentaria": "moda",
        "clothing": "moda",
        "apparel": "moda",
        
        # Tecnología/Electrónica  
        "electronica": "tecnologia",
        "electrónica": "tecnologia",
        "gadgets": "tecnologia",
        "tech": "tecnologia",
        "informatica": "tecnologia",
        "informática": "tecnologia",
        "ordenadores": "tecnologia",
        "computadoras": "tecnologia",
        "computadores": "tecnologia",
        
        # Belleza
        "cosmetica": "belleza",
        "cosmética": "belleza",
        "skincare": "belleza",
        "cuidado de la piel": "belleza",
        "maquillaje": "belleza",
        "makeup": "belleza",
        "beauty": "belleza",
        
        # Marketing
        "publicidad": "marketing",
        "advertising": "marketing",
        "ads": "marketing",
        "promocion": "marketing",
        
        # Agencia
        "estudio": "agencia",
        "consultora": "agencia",
        "consultoria": "agencia",
        "empresa de servicios": "agencia",
        "agency": "agencia",
    }
    
    # Caracteres con/sin tilde para normalización
    ACCENT_MAP = {
        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
        'ä': 'a', 'ë': 'e', 'ï': 'i', 'ö': 'o', 'ü': 'u',
        'à': 'a', 'è': 'e', 'ì': 'i', 'ò': 'o', 'ù': 'u',
        'ñ': 'n',
    }
    
    def normalize(self, text: str) -> str:
        """
        Normaliza el texto para interpretación interna.
        
        Args:
            text: Texto original
            
        Returns:
            Texto normalizado para procesamiento interno
        """
        normalized = text.lower().strip()
        
        # 1. Corregir errores ortográficos conocidos
        for wrong, correct in self.SPELLING_CORRECTIONS.items():
            # Buscar palabra completa
            pattern = r'\b' + re.escape(wrong) + r'\b'
            normalized = re.sub(pattern, correct, normalized, flags=re.IGNORECASE)
        
        # 2. NO aplicamos sinónimos aquí - eso lo hacemos en el análisis
        # para mantener el texto legible pero interpretar correctamente
        
        return normalized
    
    def normalize_for_matching(self, text: str) -> str:
        """
        Normaliza texto eliminando acentos para comparaciones.
        
        Args:
            text: Texto a normalizar
            
        Returns:
            Texto sin acentos
        """
        result = text.lower()
        for accented, plain in self.ACCENT_MAP.items():
            result = result.replace(accented, plain)
        return result
    
    def get_semantic_variations(self, term: str) -> List[str]:
        """
        Obtiene variaciones semánticas de un término.
        
        Args:
            term: Término a expandir
            
        Returns:
            Lista de términos equivalentes
        """
        variations = [term]
        term_lower = term.lower()
        
        # Buscar sinónimos directos
        for synonym, canonical in self.SEMANTIC_SYNONYMS.items():
            if term_lower == canonical:
                variations.append(synonym)
            elif term_lower == synonym:
                variations.append(canonical)
                # También añadir otros sinónimos del mismo grupo
                for syn, can in self.SEMANTIC_SYNONYMS.items():
                    if can == canonical and syn not in variations:
                        variations.append(syn)
        
        return list(set(variations))


class PromptCleaner:
    """
    Limpia el prompt de palabras innecesarias y normaliza expresiones.
    
    Ejemplo:
    - "busco mas o menos ecommerce de ropa que no usen mailchimp"
    - Se convierte en: "ecommerce de ropa sin mailchimp"
    """
    
    def __init__(self):
        self.normalizer = PromptNormalizer()
    
    # Palabras de relleno a eliminar
    FILLER_WORDS = [
        # Verbos de búsqueda
        "busco", "buscar", "buscando", "necesito", "necesitar", "quiero", "queremos",
        "encuentra", "encontrar", "dame", "dime", "muestra", "mostrar", "listar",
        # Expresiones de aproximación
        "mas o menos", "más o menos", "aproximadamente", "como", "algo así como",
        "tipo", "estilo", "parecido a", "similar a",
        # Artículos y conectores
        "el", "la", "los", "las", "un", "una", "unos", "unas",
        "que", "sean", "son", "es", "sea", "siendo",
        "me", "te", "nos", "les",
        "por favor", "porfavor", "porfa",
        # Expresiones de cortesía/relleno
        "oye", "mira", "vale", "ok", "bueno", "pues",
        "básicamente", "realmente", "simplemente", "solo",
    ]
    
    # Expresiones a normalizar (original -> normalizado)
    NORMALIZE_EXPRESSIONS = [
        # Negaciones
        (r'\bque no usen?\b', 'sin'),
        (r'\bque no tengan?\b', 'sin'),
        (r'\bque no utilicen?\b', 'sin'),
        (r'\bsin usar\b', 'sin'),
        (r'\bsin tener\b', 'sin'),
        (r'\bno tengan?\b', 'sin'),
        (r'\bno usen?\b', 'sin'),
        (r'\bexcluyendo\b', 'sin'),
        (r'\bexcepto\b', 'sin'),
        # Afirmaciones
        (r'\bque usen?\b', 'con'),
        (r'\bque tengan?\b', 'con'),
        (r'\bque utilicen?\b', 'con'),
        (r'\busando\b', 'con'),
        (r'\bcon uso de\b', 'con'),
        # Ubicación
        (r'\bque est[eé]n? en\b', 'en'),
        (r'\bubicad[oa]s? en\b', 'en'),
        (r'\bde la zona de\b', 'en'),
        # Especificaciones
        (r'\bque vendan?\b', 'de'),
        (r'\bque ofrezcan?\b', 'de'),
        (r'\bdedicad[oa]s? a\b', 'de'),
    ]
    
    def clean(self, prompt: str) -> Tuple[str, Dict]:
        """
        Limpia el prompt de palabras innecesarias.
        
        Args:
            prompt: El prompt original del usuario
            
        Returns:
            Tuple de (prompt limpio, metadata extraída)
        """
        original = prompt
        cleaned = prompt.lower().strip()
        metadata = {
            "original": original,
            "exclusions": [],  # Cosas que NO quiere (sin X)
            "requirements": [],  # Cosas que SÍ quiere (con X)
        }
        
        # 0. Normalizar ortografía (corregir errores comunes)
        cleaned = self.normalizer.normalize(cleaned)
        
        # 1. Normalizar expresiones complejas
        for pattern, replacement in self.NORMALIZE_EXPRESSIONS:
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
        
        # 2. Extraer exclusiones (sin X)
        exclusion_pattern = r'\bsin\s+([a-záéíóúñ]+)'
        exclusions = re.findall(exclusion_pattern, cleaned)
        metadata["exclusions"] = exclusions
        
        # 3. Extraer requisitos (con X)
        requirement_pattern = r'\bcon\s+([a-záéíóúñ]+)'
        requirements = re.findall(requirement_pattern, cleaned)
        metadata["requirements"] = requirements
        
        # 4. Eliminar palabras de relleno
        for filler in self.FILLER_WORDS:
            # Usar regex para eliminar palabra completa
            pattern = r'\b' + re.escape(filler) + r'\b'
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
        
        # 5. Limpiar espacios múltiples
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        # 6. Limpiar puntuación innecesaria al inicio/final
        cleaned = re.sub(r'^[,.\s]+|[,.\s]+$', '', cleaned)
        
        return cleaned, metadata


class PromptAnalyzer:
    """
    Analiza el prompt del usuario para entender exactamente qué busca.
    
    Problema a resolver: Cuando el usuario pone "ecommerce", no quiere
    webs que hablen de ecommerce (como Shopify o artículos), sino webs
    que SEAN ecommerce (tiendas online reales).
    """
    
    # Patrones para detectar tipos de negocio
    BUSINESS_PATTERNS = {
        BusinessType.ECOMMERCE: [
            r'\becommerce\b', r'\be-commerce\b', r'\btienda\s+online\b',
            r'\btienda\s+virtual\b', r'\bshop\b', r'\bstore\b',
            r'\bcomercio\s+electr[oó]nico\b',
            r'\btienda\s+de\b', r'\btienda\b'  # "tienda de ropa", "tienda"
        ],
        BusinessType.SAAS: [
            r'\bsaas\b', r'\bsoftware\s+as\s+a\s+service\b',
            r'\bplataforma\b', r'\bherramienta\s+online\b',
            r'\bapp\s+web\b', r'\baplicaci[oó]n\s+web\b'
        ],
        BusinessType.AGENCY: [
            r'\bagencia\b', r'\bagency\b', r'\bestudio\b',
            r'\bconsultor[ií]a\b', r'\bconsulting\b'
        ],
        BusinessType.DROPSHIPPING: [
            r'\bdropshipping\b', r'\bdrop\s*shipping\b'
        ],
        BusinessType.MARKETPLACE: [
            r'\bmarketplace\b', r'\bmercado\b'
        ],
        BusinessType.BLOG: [
            r'\bblog\b', r'\bblogs\b'
        ],
        BusinessType.PORTFOLIO: [
            r'\bportfolio\b', r'\bportafolio\b'
        ],
        BusinessType.SUBSCRIPTION: [
            r'\bsuscripci[oó]n\b', r'\bsubscription\b', r'\bmembres[ií]a\b'
        ],
        BusinessType.SERVICE: [
            r'\bservicio\b', r'\bservice\b'
        ],
        BusinessType.CORPORATE: [
            r'\bcorporativ[oa]\b', r'\bempresa\b', r'\bcorporate\b'
        ]
    }
    
    # Palabras clave que indican nichos/sectores
    NICHE_KEYWORDS = [
        # Moda y ropa
        (r'\bmoda\b|\bfashion\b|\bropa\b|\bclothing\b|\btextil\b', 'moda'),
        (r'\bold\s*money\b', 'old money'),
        (r'\bstreet\s*wear\b|\burban\b', 'streetwear'),
        (r'\blujo\b|\bluxury\b|\bpremium\b', 'lujo'),
        
        # Tecnología
        (r'\belectr[oó]nica\b|\belectronics\b|\btech\b|\btecnolog[ií]a\b', 'tecnología'),
        (r'\bgadgets?\b|\bdispositivos?\b', 'gadgets'),
        (r'\bm[oó]viles?\b|\bsmartphones?\b|\bcelulares?\b', 'móviles'),
        
        # Salud y belleza
        (r'\bbelleza\b|\bbeauty\b|\bcosm[eé]tic[oa]s?\b', 'belleza'),
        (r'\bcremas?\s*(faciale?s?)?\b|\bskincare\b|\bcuidado\s*(de\s*la)?\s*piel\b', 'skincare'),
        (r'\bmaquillaje\b|\bmakeup\b', 'maquillaje'),
        (r'\bsalud\b|\bhealth\b|\bbienestar\b|\bwellness\b', 'salud'),
        (r'\bsuplementos?\b|\bvitaminas?\b', 'suplementos'),
        
        # Hogar
        (r'\bhogar\b|\bhome\b|\bcasa\b|\bmuebles?\b|\bfurniture\b', 'hogar'),
        (r'\bdecoraci[oó]n\b|\bdecor\b', 'decoración'),
        
        # Alimentación
        (r'\baliment(os?|aci[oó]n)\b|\bfood\b|\bcomida\b', 'alimentación'),
        (r'\bvegan[oa]?\b|\bvegetarian[oa]?\b|\borg[aá]nic[oa]?\b', 'orgánico'),
        
        # Marketing
        (r'\bmarketing\b', 'marketing'),
        (r'\bmarketing\s+digital\b|\bdigital\s+marketing\b', 'marketing digital'),
        (r'\bseo\b', 'SEO'),
        (r'\bpublicidad\b|\badvertising\b|\bads\b', 'publicidad'),
        (r'\bredes\s+sociales\b|\bsocial\s+media\b', 'redes sociales'),
        
        # Otros
        (r'\bdeportes?\b|\bsports?\b|\bfitness\b', 'deportes'),
        (r'\bmascotas?\b|\bpets?\b', 'mascotas'),
        (r'\bni[ñn]os?\b|\binfantil\b|\bkids?\b|\bbeb[eé]s?\b', 'infantil'),
        (r'\bjuguetes?\b|\btoys?\b', 'juguetes'),
        (r'\bjoyer[ií]a\b|\bjewelry\b|\bjoyas?\b', 'joyería'),
        (r'\brelojes?\b|\bwatches?\b', 'relojes'),
        (r'\bautom[oó]vil(es)?\b|\bcars?\b|\bcoches?\b|\bveh[ií]culos?\b', 'automoción'),
    ]
    
    # Indicadores de métricas que el usuario quiere analizar
    METRICS_KEYWORDS = {
        'velocidad': [r'\bvelocidad\b', r'\br[aá]pida?\b', r'\blenta?\b', r'\bcarga\b', r'\bspeed\b'],
        'seo': [r'\bseo\b', r'\bposicionamiento\b', r'\branking\b'],
        'mobile': [r'\bm[oó]vil\b', r'\bmobile\b', r'\bresponsive\b'],
        'performance': [r'\bperformance\b', r'\brendimiento\b'],
        'accesibilidad': [r'\baccesibilidad\b', r'\baccessibility\b'],
    }
    
    def __init__(self):
        """Inicializa el analizador de prompts."""
        self.cleaner = PromptCleaner()
        self.normalizer = PromptNormalizer()
    
    def analyze(self, prompt: str) -> PromptIntent:
        """
        Analiza el prompt y extrae la intención del usuario.
        
        FILOSOFÍA: Asumir errores humanos como norma.
        "ecomerce de rropa" → se interpreta como "ecommerce de ropa"
        
        Args:
            prompt: El prompt del usuario (puede tener errores)
            
        Returns:
            PromptIntent con toda la información extraída
        """
        # Limpiar el prompt de palabras innecesarias Y normalizar ortografía
        cleaned_prompt, metadata = self.cleaner.clean(prompt)
        
        # Usar el prompt limpio y normalizado para el análisis
        prompt_lower = cleaned_prompt.lower().strip()
        
        # Detectar tipo de negocio
        business_type, business_confidence = self._detect_business_type(prompt_lower)
        
        # Detectar nicho/sector
        niche = self._detect_niche(prompt_lower)
        
        # Detectar producto/servicio específico
        product_service = self._detect_product_service(prompt_lower, business_type, niche)
        
        # Detectar características adicionales
        characteristics = self._extract_characteristics(prompt_lower)
        
        # Detectar métricas a analizar
        metrics = self._detect_metrics_to_analyze(prompt_lower)
        
        # Generar queries de búsqueda
        search_queries = self._generate_search_queries(
            business_type, niche, product_service, characteristics, prompt
        )
        
        return PromptIntent(
            business_type=business_type,
            niche=niche,
            product_service=product_service,
            characteristics=characteristics,
            metrics_to_analyze=metrics,
            original_prompt=prompt,
            cleaned_prompt=cleaned_prompt,
            exclusions=metadata.get("exclusions", []),
            requirements=metadata.get("requirements", []),
            search_queries=search_queries,
            confidence=business_confidence
        )
    
    def _detect_business_type(self, prompt: str) -> Tuple[BusinessType, int]:
        """Detecta el tipo de negocio que busca el usuario."""
        for business_type, patterns in self.BUSINESS_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, prompt, re.IGNORECASE):
                    # Calcular confianza basada en la especificidad del patrón
                    confidence = 80 if len(pattern) > 10 else 60
                    return business_type, confidence
        
        return BusinessType.UNKNOWN, 30
    
    def _detect_niche(self, prompt: str) -> Optional[str]:
        """Detecta el nicho o sector específico."""
        for pattern, niche_name in self.NICHE_KEYWORDS:
            if re.search(pattern, prompt, re.IGNORECASE):
                return niche_name
        return None
    
    def _detect_product_service(
        self, 
        prompt: str, 
        business_type: BusinessType,
        niche: Optional[str]
    ) -> Optional[str]:
        """
        Detecta el producto o servicio específico mencionado.
        
        Intenta extraer especificaciones más allá del nicho general.
        Ej: "ecommerce de crema facial" -> producto = "crema facial"
        """
        # Patrones para extraer el producto/servicio después de "de"
        de_patterns = [
            r'\bde\s+([a-záéíóúñ\s]+?)(?:\s+que|\s+con|\s*$)',
            r'\bpara\s+([a-záéíóúñ\s]+?)(?:\s+que|\s+con|\s*$)',
        ]
        
        for pattern in de_patterns:
            match = re.search(pattern, prompt, re.IGNORECASE)
            if match:
                product = match.group(1).strip()
                # Filtrar si es solo el nicho que ya detectamos
                if niche and product.lower() == niche.lower():
                    continue
                # Filtrar palabras muy genéricas
                if product and len(product) > 2 and product not in ['la', 'el', 'los', 'las', 'un', 'una']:
                    return product
        
        return None
    
    def _extract_characteristics(self, prompt: str) -> List[str]:
        """Extrae características adicionales del prompt."""
        characteristics = []
        
        # Patrones de características
        char_patterns = [
            (r'\bpequeñ[oa]s?\b', 'pequeño'),
            (r'\bgrandes?\b', 'grande'),
            (r'\blocal(es)?\b', 'local'),
            (r'\binternacional(es)?\b', 'internacional'),
            (r'\bespañol(es|as)?\b|\ben\s+españa\b', 'español'),
            (r'\bnuev[oa]s?\b', 'nuevo'),
            (r'\bestablecid[oa]s?\b', 'establecido'),
            (r'\bcon\s+blog\b', 'tiene blog'),
            (r'\bsin\s+blog\b', 'sin blog'),
            (r'\bcon\s+env[ií]o\s+gratis\b', 'envío gratis'),
        ]
        
        for pattern, char_name in char_patterns:
            if re.search(pattern, prompt, re.IGNORECASE):
                characteristics.append(char_name)
        
        return characteristics
    
    def _detect_metrics_to_analyze(self, prompt: str) -> List[str]:
        """Detecta si el usuario quiere analizar métricas específicas."""
        metrics = []
        
        for metric_name, patterns in self.METRICS_KEYWORDS.items():
            for pattern in patterns:
                if re.search(pattern, prompt, re.IGNORECASE):
                    metrics.append(metric_name)
                    break
        
        return metrics
    
    def _generate_search_queries(
        self,
        business_type: BusinessType,
        niche: Optional[str],
        product_service: Optional[str],
        characteristics: List[str],
        original_prompt: str
    ) -> List[str]:
        """
        Genera queries de búsqueda inteligentes.
        
        CLAVE: Usar términos TRANSACCIONALES que un comprador/cliente usaría,
        no términos informativos que usaría alguien investigando.
        """
        queries = []
        
        # Término principal para las búsquedas
        main_term = product_service or niche or ""
        
        if business_type == BusinessType.ECOMMERCE:
            if main_term:
                # Queries transaccionales (como buscaría un comprador)
                queries.append(f"comprar {main_term} online")
                queries.append(f"tienda {main_term}")
                queries.append(f"{main_term} precio envío")
                queries.append(f"donde comprar {main_term}")
                queries.append(f"mejores tiendas {main_term}")
            else:
                queries.append("tienda online comprar")
                queries.append("shop online productos")
                
        elif business_type == BusinessType.AGENCY:
            if main_term:
                queries.append(f"agencia {main_term} servicios")
                queries.append(f"contratar agencia {main_term}")
                queries.append(f"mejores agencias {main_term}")
                queries.append(f"empresa {main_term} portfolio")
            else:
                queries.append("agencia marketing servicios")
                queries.append("agencia diseño portfolio")
                
        elif business_type == BusinessType.SAAS:
            if main_term:
                queries.append(f"software {main_term} precio")
                queries.append(f"{main_term} herramienta online")
                queries.append(f"mejor {main_term} software")
            else:
                queries.append("software online pricing")
                
        elif business_type == BusinessType.DROPSHIPPING:
            if main_term:
                queries.append(f"comprar {main_term} barato")
                queries.append(f"tienda {main_term} ofertas")
            
        else:
            # Tipo desconocido - intentar queries genéricas útiles
            if main_term:
                queries.append(f"comprar {main_term} online")
                queries.append(f"{main_term} tienda")
                queries.append(f"mejores {main_term}")
            queries.append(original_prompt)
        
        # Añadir variante con España si aplica
        if 'español' in characteristics or 'local' in characteristics:
            if queries:
                queries.insert(1, f"{queries[0]} españa")
        
        # Eliminar duplicados
        seen = set()
        unique = []
        for q in queries:
            if q.lower() not in seen:
                seen.add(q.lower())
                unique.append(q)
        
        return unique[:6]
