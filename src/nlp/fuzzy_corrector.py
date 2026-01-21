"""
Corrector automático de errores usando Fuzzy Matching.

En lugar de mantener un diccionario de errores → correcciones,
este sistema compara palabras desconocidas con un vocabulario
y encuentra automáticamente la más similar.

Ejemplo:
- "ecomrs" → encuentra "ecommerce" (92% similar)
- "marketng" → encuentra "marketing" (91% similar)
- "shpify" → encuentra "shopify" (83% similar)
"""
from typing import Optional, Tuple, List, Set
import re

try:
    from rapidfuzz import fuzz, process
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False
    print("⚠ rapidfuzz no disponible. Instalar con: pip install rapidfuzz")


class FuzzyCorrector:
    """
    Corrector automático de errores ortográficos usando fuzzy matching.
    
    Ventajas sobre diccionario manual:
    - No necesita añadir cada error manualmente
    - Detecta errores nuevos automáticamente
    - Escala mejor con vocabulario grande
    """
    
    # Vocabulario de términos conocidos organizados por categoría
    VOCABULARY = {
        # Tipos de negocio (incluir variantes para mejor matching)
        "business_types": [
            "ecommerce", "e-commerce", "tienda", "shop", "store", "comercio",
            "tienda online", "tienda virtual", "comercio electronico",
            "saas", "software", "plataforma", "herramienta", "aplicacion", "app",
            "agencia", "consultora", "consultoria", "estudio", "empresa",
            "dropshipping", "marketplace", "blog", "portfolio",
        ],
        
        # Nichos/sectores
        "niches": [
            "moda", "ropa", "fashion", "textil", "calzado",
            "tecnologia", "electronica", "gadgets", "informatica", "tech",
            "belleza", "cosmetica", "skincare", "maquillaje", "beauty",
            "marketing", "publicidad", "digital", "seo", "sem", "ads",
            "salud", "fitness", "bienestar", "nutricion", "farmacia",
            "hogar", "muebles", "decoracion", "jardin", "inmobiliaria",
            "alimentacion", "comida", "bebidas", "gourmet", "organico",
            "deportes", "gym", "outdoor", "running",
            "mascotas", "perros", "gatos", "veterinaria",
            "infantil", "bebes", "ninos", "juguetes", "kids",
            "joyeria", "joyas", "relojes", "accesorios", "lujo",
            "automocion", "coches", "motos", "vehiculos",
        ],
        
        # Términos de software/SaaS
        "software": [
            "crm", "erp", "cms", "api",
            "gestion", "proyectos", "tareas", "equipos",
            "contabilidad", "facturacion", "finanzas", "nominas",
            "inventario", "stock", "almacen", "logistica",
            "rrhh", "recursos", "humanos", "empleados", "talento",
            "analytics", "metricas", "datos", "reportes",
            "automatizacion", "workflow", "procesos",
            "email", "newsletter", "mailing", "campanas",
            "ventas", "leads", "pipeline", "clientes",
            "soporte", "tickets", "helpdesk", "chat",
        ],
        
        # Tecnologías/plataformas
        "technologies": [
            "shopify", "woocommerce", "wordpress", "magento", "prestashop",
            "wix", "squarespace", "webflow", "drupal", "joomla",
            "stripe", "paypal", "redsys", "bizum", "klarna",
            "mailchimp", "klaviyo", "hubspot", "salesforce", "zendesk",
            "google", "facebook", "instagram", "tiktok", "linkedin",
            "react", "angular", "vue", "nextjs", "nodejs",
        ],
        
        # Ubicaciones
        "locations": [
            "españa", "espana", "spain", "mexico", "argentina", "colombia",
            "chile", "peru", "madrid", "barcelona", "valencia", "sevilla",
            "europa", "latinoamerica", "internacional", "global", "local",
        ],
        
        # Modificadores comunes
        "modifiers": [
            "online", "digital", "virtual", "web", "internet",
            "pequeño", "grande", "nuevo", "mejor", "top",
            "gratis", "premium", "profesional", "empresarial",
            "rapido", "facil", "simple", "completo", "avanzado",
        ],
    }
    
    def __init__(self, min_similarity: float = 80.0):
        """
        Inicializa el corrector.
        
        Args:
            min_similarity: Similitud mínima (0-100) para aceptar una corrección
        """
        self.min_similarity = min_similarity
        
        # Crear vocabulario plano para búsqueda rápida
        self._all_terms: Set[str] = set()
        for category_terms in self.VOCABULARY.values():
            self._all_terms.update(category_terms)
        
        # Términos que NO deben corregirse (marcas exactas, etc.)
        self._protected_terms = {
            "shopify", "woocommerce", "wordpress", "magento",
            "stripe", "paypal", "mailchimp", "hubspot",
            "google", "facebook", "instagram", "tiktok",
        }
    
    def correct_word(self, word: str) -> Tuple[str, float]:
        """
        Corrige una palabra si encuentra una similar en el vocabulario.
        
        Args:
            word: Palabra a corregir
            
        Returns:
            Tuple de (palabra corregida, score de similitud 0-100)
            Si no hay corrección, devuelve (palabra original, 100.0)
        """
        if not RAPIDFUZZ_AVAILABLE:
            return word, 100.0
        
        word_lower = word.lower().strip()
        
        # Si la palabra ya está en el vocabulario, no corregir
        if word_lower in self._all_terms:
            return word_lower, 100.0
        
        # Si es muy corta, no intentar corregir (alto riesgo de error)
        if len(word_lower) < 3:
            return word_lower, 100.0
        
        # Buscar la palabra más similar en el vocabulario
        result = process.extractOne(
            word_lower,
            self._all_terms,
            scorer=fuzz.ratio
        )
        
        if result:
            match, score, _ = result
            
            # Solo corregir si la similitud supera el umbral
            if score >= self.min_similarity:
                return match, score
        
        # No se encontró corrección suficientemente buena
        return word_lower, 0.0
    
    def correct_text(self, text: str) -> Tuple[str, List[dict]]:
        """
        Corrige un texto completo palabra por palabra.
        
        Args:
            text: Texto a corregir
            
        Returns:
            Tuple de (texto corregido, lista de correcciones aplicadas)
        """
        if not RAPIDFUZZ_AVAILABLE:
            return text, []
        
        corrections = []
        words = text.split()
        corrected_words = []
        
        for word in words:
            # Preservar puntuación
            prefix = ""
            suffix = ""
            clean_word = word
            
            # Extraer puntuación del inicio
            while clean_word and not clean_word[0].isalnum():
                prefix += clean_word[0]
                clean_word = clean_word[1:]
            
            # Extraer puntuación del final
            while clean_word and not clean_word[-1].isalnum():
                suffix = clean_word[-1] + suffix
                clean_word = clean_word[:-1]
            
            if clean_word:
                corrected, score = self.correct_word(clean_word)
                
                if corrected != clean_word.lower() and score >= self.min_similarity:
                    corrections.append({
                        "original": clean_word,
                        "corrected": corrected,
                        "similarity": score
                    })
                    corrected_words.append(prefix + corrected + suffix)
                else:
                    corrected_words.append(prefix + clean_word.lower() + suffix)
            else:
                corrected_words.append(word)
        
        return " ".join(corrected_words), corrections
    
    def find_similar(self, word: str, top_k: int = 5) -> List[Tuple[str, float]]:
        """
        Encuentra las palabras más similares en el vocabulario.
        
        Útil para debugging y para ver qué correcciones se harían.
        
        Args:
            word: Palabra a buscar
            top_k: Número de resultados
            
        Returns:
            Lista de (palabra, similitud) ordenada por similitud
        """
        if not RAPIDFUZZ_AVAILABLE:
            return []
        
        results = process.extract(
            word.lower(),
            self._all_terms,
            scorer=fuzz.ratio,
            limit=top_k
        )
        
        return [(match, score) for match, score, _ in results]
    
    def add_to_vocabulary(self, terms: List[str], category: str = "custom"):
        """
        Añade términos al vocabulario.
        
        Args:
            terms: Lista de términos a añadir
            category: Categoría (para organización)
        """
        if category not in self.VOCABULARY:
            self.VOCABULARY[category] = []
        
        for term in terms:
            term_lower = term.lower()
            if term_lower not in self._all_terms:
                self.VOCABULARY[category].append(term_lower)
                self._all_terms.add(term_lower)


# Singleton
_fuzzy_corrector = None

def get_fuzzy_corrector(min_similarity: float = 80.0) -> FuzzyCorrector:
    """Obtiene la instancia singleton del corrector fuzzy."""
    global _fuzzy_corrector
    
    if _fuzzy_corrector is None:
        _fuzzy_corrector = FuzzyCorrector(min_similarity=min_similarity)
    
    return _fuzzy_corrector
