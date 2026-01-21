"""
Normalizador avanzado de texto.

FILOSOFÍA: Normalización LIGERA, no agresiva.
- Lowercase, NFKC normalize, collapse spaces
- Solo elimina stop-phrases conversacionales
- Corrige errores ortográficos usando fuzzy matching automático
- NO sustituye nombres propios/marcas automáticamente
"""
import re
import unicodedata
from typing import Tuple, Dict, List, Optional

# Importar fuzzy corrector
try:
    from .fuzzy_corrector import get_fuzzy_corrector, FuzzyCorrector
    FUZZY_AVAILABLE = True
except ImportError:
    FUZZY_AVAILABLE = False


class AdvancedNormalizer:
    
    # Correcciones ortográficas MUY seguras (errores comunes evidentes)
    SAFE_SPELLING_CORRECTIONS = {
        # Ecommerce y variantes (muy común)
        "ecomerce": "ecommerce",
        "ecomerse": "ecommerce",
        "e-comerce": "ecommerce",
        "ecommerse": "ecommerce",
        "eccomerce": "ecommerce",
        "e-commerce": "ecommerce",
        "e commerce": "ecommerce",
        "icommerce": "ecommerce",
        "comercio electronico": "ecommerce",
        
        # Tienda y variantes
        "tinda": "tienda",
        "tiena": "tienda",
        "teinda": "tienda",
        "tienfa": "tienda",
        
        # Ropa (muy común)
        "rropa": "ropa",
        "rpoa": "ropa",
        "roap": "ropa",
        
        # Marketing
        "marqueting": "marketing",
        "marketin": "marketing",
        "markting": "marketing",
        "maketing": "marketing",
        
        # Digital
        "dijital": "digital",
        "digtal": "digital",
        "digitl": "digital",
        
        # Agencia
        "agncia": "agencia",
        "agenca": "agencia",
        "ajencia": "agencia",
        
        # Electrónica
        "eletronica": "electronica",
        "elctronica": "electronica",
        "electronca": "electronica",
        
        # Moda/Fashion
        "fasion": "moda",
        "fachion": "moda",
        "fashion": "moda",
        
        # Software
        "sofware": "software",
        "sotfware": "software",
        "softwre": "software",
        
        # SaaS
        "sas": "saas",
        "sass": "saas",
        "saass": "saas",
        
        # CRM (muy común confundir con CMR)
        "cmr": "crm",
        "crm": "crm",
        "crmm": "crm",
        
        # ERP
        "erp": "erp",
        "erpp": "erp",
        
        # Dropshipping
        "dropshiping": "dropshipping",
        "drop shipping": "dropshipping",
        "dropsipping": "dropshipping",
        
        # Otros términos tech comunes
        "analitycs": "analytics",
        "analitics": "analytics",
        "analyitcs": "analytics",
        "seo": "seo",
        "sem": "sem",
        "gestion": "gestion",
        "gestión": "gestion",
        "proyectos": "proyectos",
        "projectos": "proyectos",
        "inventario": "inventario",
        "imventario": "inventario",
        "contabilidad": "contabilidad",
        "contavilidad": "contabilidad",
        "facturacion": "facturacion",
        "facturación": "facturacion",
    }
    """
    Normalización ligera de texto para procesamiento NLP.
    
    Principios:
    1. Preservar la información semántica
    2. Solo normalización segura (no agresiva)
    3. No corregir marcas/nombres propios
    """
    
    # Stop-phrases conversacionales a eliminar (muy conservador)
    CONVERSATIONAL_STOPS = [
        # Verbos de búsqueda
        r'\b(busco|buscando|quiero|necesito|me interesa|me interesan)\b',
        r'\b(encuentra|encontrar|dame|dime|muestra|muestrame)\b',
        r'\b(podrias|podrías|puedes|puede)\b',
        # Expresiones de cortesía
        r'\b(por favor|porfavor|porfa|gracias)\b',
        # Muletillas
        r'\b(oye|mira|vale|ok|bueno|pues|eh|um)\b',
        r'\b(basicamente|básicamente|realmente|simplemente)\b',
    ]
    
    # Patrones para extraer entidades (regex)
    ENTITY_PATTERNS = {
        # Tecnologías/Plataformas (preservar exactamente)
        "technology": r'\b(shopify|woocommerce|wordpress|magento|prestashop|wix|squarespace|stripe|paypal|mailchimp|klaviyo|hubspot|google analytics|hotjar)\b',
        # Ubicaciones
        "location": r'\b(españa|spain|mexico|méxico|argentina|colombia|chile|peru|perú|madrid|barcelona|valencia)\b',
        # Modificadores de exclusión/inclusión
        "modifier": r'\b(sin|con|que tenga|que use|que no tenga|que no use|excluyendo|incluyendo)\b',
    }
    
    def __init__(self, use_fuzzy: bool = True, fuzzy_threshold: float = 80.0):
        """
        Inicializa el normalizador.
        
        Args:
            use_fuzzy: Si usar fuzzy matching para corrección automática
            fuzzy_threshold: Similitud mínima (0-100) para aceptar corrección
        """
        # Compilar patrones para eficiencia
        self._stop_patterns = [re.compile(p, re.IGNORECASE) for p in self.CONVERSATIONAL_STOPS]
        self._entity_patterns = {k: re.compile(v, re.IGNORECASE) for k, v in self.ENTITY_PATTERNS.items()}
        
        # Fuzzy corrector para corrección automática
        self._use_fuzzy = use_fuzzy and FUZZY_AVAILABLE
        self._fuzzy_corrector = None
        
        if self._use_fuzzy:
            self._fuzzy_corrector = get_fuzzy_corrector(min_similarity=fuzzy_threshold)
    
    def normalize(self, text: str) -> Tuple[str, Dict]:
        """
        Normaliza texto de forma ligera pero corrigiendo errores evidentes.
        
        Args:
            text: Texto original
            
        Returns:
            Tuple de (texto normalizado, metadata extraída)
        """
        metadata = {
            "original": text,
            "extracted_entities": {},
            "removed_stops": [],
            "spelling_corrections": [],
        }
        
        # 1. NFKC normalization (normaliza caracteres unicode)
        normalized = unicodedata.normalize('NFKC', text)
        
        # 2. Lowercase
        normalized = normalized.lower()
        
        # 3. Extraer entidades ANTES de normalizar (para preservarlas)
        for entity_type, pattern in self._entity_patterns.items():
            matches = pattern.findall(normalized)
            if matches:
                metadata["extracted_entities"][entity_type] = matches
        
        # 4. Aplicar correcciones ortográficas
        # Primero: correcciones manuales SEGURAS (errores muy comunes)
        for wrong, correct in self.SAFE_SPELLING_CORRECTIONS.items():
            if wrong in normalized:
                normalized = normalized.replace(wrong, correct)
                metadata["spelling_corrections"].append(f"{wrong} → {correct}")
        
        # Segundo: fuzzy matching automático (detecta errores nuevos)
        if self._use_fuzzy and self._fuzzy_corrector:
            normalized, fuzzy_corrections = self._fuzzy_corrector.correct_text(normalized)
            for corr in fuzzy_corrections:
                metadata["spelling_corrections"].append(
                    f"{corr['original']} → {corr['corrected']} ({corr['similarity']:.0f}%)"
                )
        
        # 5. Eliminar SOLO stop-phrases conversacionales
        for pattern in self._stop_patterns:
            matches = pattern.findall(normalized)
            if matches:
                metadata["removed_stops"].extend(matches)
            normalized = pattern.sub('', normalized)
        
        # 6. Collapse multiple spaces
        normalized = re.sub(r'\s+', ' ', normalized)
        
        # 7. Strip
        normalized = normalized.strip()
        
        # 8. Limpiar puntuación redundante al inicio/final
        normalized = re.sub(r'^[,.\s:;]+|[,.\s:;]+$', '', normalized)
        
        return normalized, metadata
    
    def extract_requirements(self, text: str) -> Dict[str, List[str]]:
        """
        Extrae requisitos y exclusiones del texto.
        
        Args:
            text: Texto normalizado
            
        Returns:
            Dict con 'requirements' y 'exclusions'
        """
        result = {
            "requirements": [],  # con X
            "exclusions": [],    # sin X
        }
        
        # Patrones para extraer requisitos
        req_patterns = [
            r'\bcon\s+([a-záéíóúñ\w]+)',
            r'\bque\s+(?:tenga|use|utilice)\s+([a-záéíóúñ\w]+)',
            r'\bincluyendo\s+([a-záéíóúñ\w]+)',
        ]
        
        # Patrones para extraer exclusiones
        excl_patterns = [
            r'\bsin\s+([a-záéíóúñ\w]+)',
            r'\bque\s+no\s+(?:tenga|use|utilice)\s+([a-záéíóúñ\w]+)',
            r'\bexcluyendo\s+([a-záéíóúñ\w]+)',
        ]
        
        text_lower = text.lower()
        
        for pattern in req_patterns:
            matches = re.findall(pattern, text_lower)
            result["requirements"].extend(matches)
        
        for pattern in excl_patterns:
            matches = re.findall(pattern, text_lower)
            result["exclusions"].extend(matches)
        
        # Eliminar duplicados
        result["requirements"] = list(set(result["requirements"]))
        result["exclusions"] = list(set(result["exclusions"]))
        
        return result
    
    def is_brand_or_proper_noun(self, term: str) -> bool:
        """
        Verifica si un término parece ser una marca o nombre propio.
        
        NO debemos corregir estos automáticamente.
        
        Args:
            term: Término a verificar
            
        Returns:
            True si parece marca/nombre propio
        """
        # Lista de marcas/tecnologías conocidas
        known_brands = {
            'shopify', 'woocommerce', 'wordpress', 'magento', 'prestashop',
            'stripe', 'paypal', 'mailchimp', 'klaviyo', 'hubspot',
            'google', 'facebook', 'instagram', 'tiktok', 'amazon',
            'zara', 'mango', 'nike', 'adidas', 'apple', 'samsung',
        }
        
        term_lower = term.lower()
        
        # Es marca conocida
        if term_lower in known_brands:
            return True
        
        # Empieza con mayúscula en el original (posible nombre propio)
        if term and term[0].isupper():
            return True
        
        # Contiene números (posible nombre de producto/versión)
        if any(c.isdigit() for c in term):
            return True
        
        return False
    
    def safe_normalize_term(self, term: str, corrections: Dict[str, str]) -> str:
        """
        Normaliza un término de forma segura, evitando corregir marcas.
        
        Args:
            term: Término a normalizar
            corrections: Diccionario de correcciones conocidas
            
        Returns:
            Término normalizado o original si es marca
        """
        # No corregir marcas/nombres propios
        if self.is_brand_or_proper_noun(term):
            return term.lower()
        
        term_lower = term.lower()
        
        # Aplicar corrección solo si existe y es segura
        if term_lower in corrections:
            return corrections[term_lower]
        
        return term_lower
