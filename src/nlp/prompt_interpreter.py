"""
Sistema avanzado de interpretación de prompts.

Módulo offline (sin APIs externas) que interpreta prompts en español
(incluyendo faltas ortográficas) y produce una representación estructurada (Spec).

Componentes:
- Sentence-Transformers para embeddings de frase
- spaCy para NER y tokenización
- RapidFuzz para fuzzy matching
- Clasificación de intención por similitud coseno
"""
import re
import json
import unicodedata
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple, Any
import numpy as np

# Importaciones condicionales
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False

try:
    from rapidfuzz import fuzz, process
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False

try:
    import spacy
    SPACY_AVAILABLE = True
except ImportError:
    SPACY_AVAILABLE = False


@dataclass
class IntentResult:
    """Resultado de clasificación de intención."""
    label: str
    confidence: float


@dataclass
class PromptSpec:
    """
    Especificación estructurada del prompt interpretado.
    
    Esta es la salida principal del sistema de interpretación.
    """
    prompt_original: str
    prompt_view: str
    corrections_tried: List[str] = field(default_factory=list)
    embedding_sentence: List[float] = field(default_factory=list)
    intent: Dict[str, Any] = field(default_factory=dict)
    business_type: Optional[str] = None
    niche: List[str] = field(default_factory=list)
    product_service: Optional[str] = None
    must_have: List[str] = field(default_factory=list)
    must_not: List[str] = field(default_factory=list)
    quality: Optional[str] = None
    location: Optional[str] = None
    target_audience: Optional[str] = None
    confidence: float = 0.0
    confidence_label: str = "low"
    notes: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        """Convierte a diccionario."""
        return asdict(self)
    
    def to_json(self) -> str:
        """Convierte a JSON."""
        data = self.to_dict()
        # Convertir embedding a lista si es numpy array
        if isinstance(data.get('embedding_sentence'), np.ndarray):
            data['embedding_sentence'] = data['embedding_sentence'].tolist()
        return json.dumps(data, ensure_ascii=False, indent=2)


class IntentClassifier:
    """
    Clasificador de intención usando similitud de embeddings.
    
    Intenciones canónicas:
    - PROSPECT: Buscar webs que SEAN algo (ecommerce, agencia, etc.)
    - ANALYZE: Analizar características de webs
    - RESEARCH: Investigar mercado/competencia
    - EXTRACT_CONTACTS: Extraer información de contacto
    - COMPARE: Comparar webs/servicios
    - MONITOR: Monitorear cambios en webs
    """
    
    # Prototipos de intención (3-6 frases por intención)
    INTENT_PROTOTYPES = {
        "PROSPECT": [
            "buscar tiendas online de ropa",
            "encontrar ecommerce de electrónica",
            "webs que sean agencias de marketing",
            "tiendas que vendan productos de belleza",
            "empresas que ofrezcan servicios de software",
            "negocios online de moda",
        ],
        "ANALYZE": [
            "analizar el SEO de estas webs",
            "ver las tecnologías que usan",
            "comprobar la velocidad de carga",
            "revisar las métricas de rendimiento",
            "examinar qué plataforma utilizan",
        ],
        "RESEARCH": [
            "investigar el mercado de cosmética",
            "estudiar la competencia en el sector",
            "conocer el panorama de tiendas online",
            "explorar qué hacen otras empresas similares",
        ],
        "EXTRACT_CONTACTS": [
            "extraer emails de contacto",
            "conseguir teléfonos de las empresas",
            "obtener información de contacto",
            "sacar los datos de las webs",
        ],
        "COMPARE": [
            "comparar estas tiendas",
            "ver diferencias entre competidores",
            "contrastar precios y servicios",
        ],
        "MONITOR": [
            "monitorear cambios en la web",
            "vigilar actualizaciones de precios",
            "seguir la evolución del sitio",
        ],
    }
    
    def __init__(self, model=None):
        """
        Inicializa el clasificador.
        
        Args:
            model: Modelo Sentence-Transformer (opcional, se crea si no se pasa)
        """
        self.model = model
        self._prototype_embeddings = {}
        
        if self.model:
            self._compute_prototype_embeddings()
    
    def _compute_prototype_embeddings(self):
        """Precalcula embeddings de los prototipos."""
        if not self.model:
            return
        
        for intent, phrases in self.INTENT_PROTOTYPES.items():
            embeddings = self.model.encode(phrases)
            # Promedio de embeddings como representación de la intención
            self._prototype_embeddings[intent] = np.mean(embeddings, axis=0)
    
    def classify(self, embedding: np.ndarray) -> IntentResult:
        """
        Clasifica la intención basándose en similitud con prototipos.
        
        Args:
            embedding: Embedding del prompt
            
        Returns:
            IntentResult con label y confidence
        """
        if not self._prototype_embeddings:
            return IntentResult(label="PROSPECT", confidence=0.5)
        
        best_intent = "PROSPECT"
        best_score = 0.0
        
        for intent, proto_emb in self._prototype_embeddings.items():
            similarity = self._cosine_similarity(embedding, proto_emb)
            if similarity > best_score:
                best_score = similarity
                best_intent = intent
        
        return IntentResult(label=best_intent, confidence=float(best_score))
    
    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Calcula similitud coseno entre dos vectores."""
        dot = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot / (norm1 * norm2)


class EntityExtractor:
    """
    Extractor de entidades usando spaCy, regex y fuzzy matching.
    """
    
    # Patrones para tipos de negocio (incluir errores comunes)
    BUSINESS_TYPE_PATTERNS = {
        "ecommerce": [
            r'\b(ecommerce|e-commerce|ecomerce|ecomers|ecommer[sc]e)\b',
            r'\b(tienda\s*(?:online|virtual)?|tinda|tiena)\b',
            r'\b(shop|store|comercio)\b',
            r'\b(comercio\s+electr[oó]nico|venta\s+online)\b',
        ],
        "agency": [
            r'\b(agencia|agency|consultora|consultor[ií]a|estudio)\b',
        ],
        "saas": [
            r'\b(saas|software|plataforma|herramienta|app|aplicaci[oó]n)\b',
            r'\b(crm|erp|cms)\b',
        ],
        "marketplace": [
            r'\b(marketplace|mercado|plataforma\s+de\s+ventas)\b',
        ],
        "dropshipping": [
            r'\b(dropshipping|drop\s*shipping)\b',
        ],
    }
    
    # Patrones para nichos
    NICHE_PATTERNS = {
        "moda": r'\b(moda|ropa|fashion|textil|prendas|vestimenta|calzado)\b',
        "tecnologia": r'\b(tecnolog[ií]a|electr[oó]nica|tech|gadgets|inform[aá]tica)\b',
        "belleza": r'\b(belleza|cosm[eé]tica|skincare|maquillaje|beauty)\b',
        "marketing": r'\b(marketing|publicidad|seo|sem|ads|digital)\b',
        "salud": r'\b(salud|fitness|bienestar|nutrici[oó]n|farmacia)\b',
        "hogar": r'\b(hogar|muebles|decoraci[oó]n|casa|jard[ií]n)\b',
        "alimentacion": r'\b(alimentaci[oó]n|comida|bebidas|food|gourmet)\b',
        "deportes": r'\b(deportes?|fitness|gym|running|outdoor)\b',
        "mascotas": r'\b(mascotas?|perros?|gatos?|pets?|veterinaria)\b',
        "infantil": r'\b(infantil|beb[eé]s?|ni[ñn]os?|juguetes?|kids)\b',
        "joyeria": r'\b(joyer[ií]a|joyas?|relojes?|bisuter[ií]a)\b',
        "automocion": r'\b(autom[oó]vil|coches?|motos?|veh[ií]culos?|cars?)\b',
    }
    
    # Tecnologías/marcas conocidas
    KNOWN_TECHNOLOGIES = [
        "shopify", "woocommerce", "wordpress", "magento", "prestashop",
        "wix", "squarespace", "webflow", "stripe", "paypal", "redsys",
        "mailchimp", "klaviyo", "hubspot", "salesforce", "zendesk",
        "google analytics", "hotjar", "mixpanel", "segment",
        "react", "angular", "vue", "nextjs", "nodejs",
    ]
    
    # Patrones para must_have / must_not
    MUST_HAVE_PATTERNS = [
        r'\bcon\s+(\w+)',
        r'\bque\s+(?:tenga|use|utilice)\s+(\w+)',
        r'\busando\s+(\w+)',
    ]
    
    MUST_NOT_PATTERNS = [
        r'\bsin\s+(\w+)',
        r'\bque\s+no\s+(?:tenga|use|utilice)\s+(\w+)',
        r'\bexcluyendo\s+(\w+)',
        r'\bexcepto\s+(\w+)',
        r'\bno\s+(?:tenga|use)\s+(\w+)',
    ]
    
    # Patrones para calidad
    QUALITY_PATTERNS = {
        "good_seo": r'\b(buen\s+seo|buen\s+posicionamiento|bien\s+posicionad[oa])\b',
        "bad_seo": r'\b(mal\s+seo|mal\s+posicionamiento|poco\s+tr[aá]fico)\b',
        "fast": r'\b(r[aá]pid[oa]|veloz|buena\s+velocidad|carga\s+r[aá]pida)\b',
        "slow": r'\b(lent[oa]|mala\s+velocidad|carga\s+lenta)\b',
        "modern": r'\b(modern[oa]|actualizada|nueva)\b',
        "outdated": r'\b(anticuad[oa]|desactualizada|vieja)\b',
    }
    
    # Patrones para ubicación
    LOCATION_PATTERNS = [
        r'\ben\s+(espa[ñn]a|m[eé]xico|argentina|colombia|chile|per[uú])\b',
        r'\ben\s+(madrid|barcelona|valencia|sevilla|bilbao)\b',
        r'\b(espa[ñn]ol(?:a|es)?|mexican[oa]|argentin[oa])\b',
        r'\b(europa|latinoam[eé]rica|internacional|global|local)\b',
    ]
    
    # Patrones para audiencia
    AUDIENCE_PATTERNS = {
        "b2b": r'\b(b2b|empresas|negocios|corporativ[oa])\b',
        "b2c": r'\b(b2c|consumidores?|clientes?\s+finales?)\b',
        "pymes": r'\b(pymes?|peque[ñn]as?\s+empresas?|aut[oó]nomos?)\b',
        "startups": r'\b(startups?|emprendedores?)\b',
        "enterprise": r'\b(enterprise|grandes?\s+empresas?|corporaciones?)\b',
    }
    
    def __init__(self, nlp=None):
        """
        Inicializa el extractor.
        
        Args:
            nlp: Pipeline de spaCy (opcional)
        """
        self.nlp = nlp
    
    def extract(self, text: str) -> Dict[str, Any]:
        """
        Extrae todas las entidades del texto.
        
        Args:
            text: Texto a analizar
            
        Returns:
            Diccionario con entidades extraídas
        """
        text_lower = text.lower()
        
        result = {
            "business_type": self._extract_business_type(text_lower),
            "niche": self._extract_niche(text_lower),
            "product_service": self._extract_product_service(text_lower),
            "must_have": self._extract_must_have(text_lower),
            "must_not": self._extract_must_not(text_lower),
            "quality": self._extract_quality(text_lower),
            "location": self._extract_location(text_lower),
            "target_audience": self._extract_audience(text_lower),
            "technologies": self._extract_technologies(text_lower),
        }
        
        return result
    
    def _extract_business_type(self, text: str) -> Optional[str]:
        """Extrae el tipo de negocio."""
        for biz_type, patterns in self.BUSINESS_TYPE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    return biz_type
        return None
    
    def _extract_niche(self, text: str) -> List[str]:
        """Extrae nichos/sectores."""
        niches = []
        for niche, pattern in self.NICHE_PATTERNS.items():
            if re.search(pattern, text, re.IGNORECASE):
                niches.append(niche)
        return niches
    
    def _extract_product_service(self, text: str) -> Optional[str]:
        """Extrae producto o servicio específico."""
        # Patrones para extraer producto después de "de"
        patterns = [
            r'\btienda\s+(?:online\s+)?de\s+([a-záéíóúñ\s]+?)(?:\s+(?:con|sin|en|que|$))',
            r'\becommerce\s+de\s+([a-záéíóúñ\s]+?)(?:\s+(?:con|sin|en|que|$))',
            r'\bagencia\s+de\s+([a-záéíóúñ\s]+?)(?:\s+(?:con|sin|en|que|$))',
            r'\bsoftware\s+de\s+([a-záéíóúñ\s]+?)(?:\s+(?:con|sin|en|que|$))',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                product = match.group(1).strip()
                if len(product) > 2:
                    return product
        
        return None
    
    def _extract_must_have(self, text: str) -> List[str]:
        """Extrae requisitos (must have)."""
        must_have = []
        
        for pattern in self.MUST_HAVE_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                # Limpiar y normalizar
                item = match.strip().lower()
                # Verificar si es una tecnología conocida
                if RAPIDFUZZ_AVAILABLE:
                    result = process.extractOne(item, self.KNOWN_TECHNOLOGIES, scorer=fuzz.ratio)
                    if result and result[1] >= 80:
                        item = result[0]
                if item and len(item) > 1:
                    must_have.append(item)
        
        return list(set(must_have))
    
    def _extract_must_not(self, text: str) -> List[str]:
        """Extrae exclusiones (must not)."""
        must_not = []
        
        for pattern in self.MUST_NOT_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                item = match.strip().lower()
                if RAPIDFUZZ_AVAILABLE:
                    result = process.extractOne(item, self.KNOWN_TECHNOLOGIES, scorer=fuzz.ratio)
                    if result and result[1] >= 80:
                        item = result[0]
                if item and len(item) > 1:
                    must_not.append(item)
        
        return list(set(must_not))
    
    def _extract_quality(self, text: str) -> Optional[str]:
        """Extrae indicadores de calidad."""
        for quality, pattern in self.QUALITY_PATTERNS.items():
            if re.search(pattern, text, re.IGNORECASE):
                return quality
        return None
    
    def _extract_location(self, text: str) -> Optional[str]:
        """Extrae ubicación geográfica."""
        for pattern in self.LOCATION_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1) if match.lastindex else match.group(0)
        return None
    
    def _extract_audience(self, text: str) -> Optional[str]:
        """Extrae audiencia/target."""
        for audience, pattern in self.AUDIENCE_PATTERNS.items():
            if re.search(pattern, text, re.IGNORECASE):
                return audience
        return None
    
    def _extract_technologies(self, text: str) -> List[str]:
        """Extrae tecnologías mencionadas."""
        found = []
        text_lower = text.lower()
        
        for tech in self.KNOWN_TECHNOLOGIES:
            if tech in text_lower:
                found.append(tech)
            elif RAPIDFUZZ_AVAILABLE:
                # Buscar con fuzzy matching
                words = text_lower.split()
                for word in words:
                    if len(word) >= 4:
                        score = fuzz.ratio(word, tech)
                        if score >= 85:
                            found.append(tech)
                            break
        
        return list(set(found))


class ConditionalCorrector:
    """
    Corrector condicional que solo aplica correcciones con alta certeza.
    """
    
    # Vocabulario para corrección
    VOCABULARY = {
        # Tipos de negocio
        "ecommerce", "tienda", "shop", "store", "agencia", "agency",
        "consultora", "saas", "software", "plataforma", "dropshipping",
        "marketplace",
        # Nichos
        "moda", "ropa", "fashion", "tecnologia", "electronica", "belleza",
        "cosmetica", "marketing", "publicidad", "digital", "salud",
        "fitness", "hogar", "muebles", "alimentacion", "deportes",
        "mascotas", "infantil", "joyeria",
        # Tecnologías
        "shopify", "woocommerce", "wordpress", "magento", "stripe",
        "paypal", "mailchimp", "klaviyo", "hubspot",
        # Otros
        "online", "virtual", "web", "internet", "servicios",
    }
    
    def __init__(self, min_similarity: float = 85.0):
        """
        Inicializa el corrector.
        
        Args:
            min_similarity: Similitud mínima para aplicar corrección
        """
        self.min_similarity = min_similarity
    
    def correct(self, text: str) -> Tuple[str, List[str]]:
        """
        Aplica correcciones condicionales al texto.
        
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
            word_lower = word.lower()
            
            # Si la palabra ya está en el vocabulario, no corregir
            if word_lower in self.VOCABULARY:
                corrected_words.append(word_lower)
                continue
            
            # Si es muy corta, no corregir
            if len(word_lower) < 3:
                corrected_words.append(word_lower)
                continue
            
            # Buscar corrección
            result = process.extractOne(
                word_lower,
                self.VOCABULARY,
                scorer=fuzz.ratio
            )
            
            if result and result[1] >= self.min_similarity:
                corrected_words.append(result[0])
                corrections.append(f"{word} → {result[0]} ({result[1]}%)")
            else:
                corrected_words.append(word_lower)
        
        return " ".join(corrected_words), corrections


class PromptInterpreter:
    """
    Intérprete principal de prompts.
    
    Combina:
    - Sentence-Transformers para embeddings
    - Clasificación de intención por similitud
    - Extracción de entidades con regex/fuzzy
    - Corrección condicional
    """
    
    def __init__(self, load_models: bool = True):
        """
        Inicializa el intérprete.
        
        Args:
            load_models: Si cargar los modelos al inicializar
        """
        self.sentence_model = None
        self.nlp = None
        self.intent_classifier = IntentClassifier(model=None)
        self.entity_extractor = EntityExtractor(nlp=None)
        self.corrector = ConditionalCorrector(min_similarity=75.0)
        
        if load_models:
            self._load_models()
    
    def _load_models(self):
        """Carga los modelos necesarios."""
        # Sentence-Transformers
        if SENTENCE_TRANSFORMERS_AVAILABLE:
            try:
                self.sentence_model = SentenceTransformer('all-MiniLM-L6-v2')
                print("✓ Sentence-Transformers cargado")
            except Exception as e:
                print(f"⚠ Error cargando Sentence-Transformers: {e}")
        
        # spaCy (opcional)
        if SPACY_AVAILABLE:
            try:
                self.nlp = spacy.load("es_core_news_sm")
                print("✓ spaCy español cargado")
            except:
                try:
                    self.nlp = spacy.load("en_core_web_sm")
                    print("✓ spaCy inglés cargado (español no disponible)")
                except:
                    print("ℹ spaCy no disponible")
        
        # Inicializar componentes
        self.intent_classifier = IntentClassifier(model=self.sentence_model)
        self.entity_extractor = EntityExtractor(nlp=self.nlp)
        self.corrector = ConditionalCorrector(min_similarity=75.0)  # Más tolerante
    
    def interpret(self, prompt: str) -> PromptSpec:
        """
        Interpreta un prompt y genera la especificación estructurada.
        
        Args:
            prompt: Prompt del usuario (puede tener errores)
            
        Returns:
            PromptSpec con toda la información extraída
        """
        # 1. Mantener prompt original EXACTO
        prompt_original = prompt
        
        # 2. Crear prompt_view con transformación mínima
        prompt_view = self._create_prompt_view(prompt)
        
        # 3. Corrección condicional
        corrected_text, corrections = self.corrector.correct(prompt_view)
        
        # 4. Calcular embedding
        embedding = self._compute_embedding(prompt_original)
        
        # 5. Clasificar intención
        intent_result = self._classify_intent(embedding)
        
        # 6. Extraer entidades (usar texto corregido)
        entities = self.entity_extractor.extract(corrected_text)
        
        # 7. Calcular confianza final
        confidence, confidence_label = self._compute_confidence(
            intent_result, entities, corrections
        )
        
        # 8. Generar notas
        notes = self._generate_notes(confidence_label, entities, corrections)
        
        # 9. Construir Spec
        spec = PromptSpec(
            prompt_original=prompt_original,
            prompt_view=prompt_view,
            corrections_tried=corrections,
            embedding_sentence=embedding.tolist() if embedding is not None else [],
            intent={
                "label": intent_result.label,
                "confidence": round(intent_result.confidence, 2)
            },
            business_type=entities.get("business_type"),
            niche=entities.get("niche", []),
            product_service=entities.get("product_service"),
            must_have=entities.get("must_have", []),
            must_not=entities.get("must_not", []),
            quality=entities.get("quality"),
            location=entities.get("location"),
            target_audience=entities.get("target_audience"),
            confidence=round(confidence, 2),
            confidence_label=confidence_label,
            notes=notes
        )
        
        return spec
    
    def _create_prompt_view(self, prompt: str) -> str:
        """
        Crea vista normalizada mínima del prompt.
        
        Solo: normalizar Unicode (NFKC) y quitar espacios extra.
        NO hacer lowercase forzado.
        """
        # NFKC normalize
        normalized = unicodedata.normalize('NFKC', prompt)
        # Quitar espacios extra
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        return normalized
    
    def _compute_embedding(self, text: str) -> Optional[np.ndarray]:
        """Calcula embedding del texto."""
        if not self.sentence_model:
            return None
        
        try:
            return self.sentence_model.encode(text)
        except Exception as e:
            print(f"Error calculando embedding: {e}")
            return None
    
    def _classify_intent(self, embedding: Optional[np.ndarray]) -> IntentResult:
        """Clasifica la intención del prompt."""
        if embedding is None or not self.intent_classifier:
            return IntentResult(label="PROSPECT", confidence=0.5)
        
        return self.intent_classifier.classify(embedding)
    
    def _compute_confidence(
        self,
        intent: IntentResult,
        entities: Dict,
        corrections: List[str]
    ) -> Tuple[float, str]:
        """
        Calcula confianza final combinando señales.
        
        Pesos:
        - score_intención: 0.5
        - entidades detectadas: 0.3
        - correcciones aplicadas: 0.2 (penaliza si muchas)
        """
        # Score de intención (0-1)
        intent_score = intent.confidence
        
        # Score de entidades (0-1)
        entity_score = 0.0
        if entities.get("business_type"):
            entity_score += 0.4
        if entities.get("niche"):
            entity_score += 0.3
        if entities.get("product_service"):
            entity_score += 0.2
        if entities.get("must_have") or entities.get("must_not"):
            entity_score += 0.1
        entity_score = min(entity_score, 1.0)
        
        # Score de correcciones (penalizar si muchas correcciones)
        correction_score = 1.0
        if len(corrections) > 0:
            correction_score = max(0.5, 1.0 - (len(corrections) * 0.1))
        
        # Combinar con pesos
        confidence = (
            intent_score * 0.5 +
            entity_score * 0.3 +
            correction_score * 0.2
        )
        
        # Etiqueta de confianza
        if confidence >= 0.75:
            label = "high"
        elif confidence >= 0.50:
            label = "medium"
        else:
            label = "low"
        
        return confidence, label
    
    def _generate_notes(
        self,
        confidence_label: str,
        entities: Dict,
        corrections: List[str]
    ) -> List[str]:
        """Genera notas explicativas."""
        notes = []
        
        if confidence_label == "low":
            notes.append("Confianza baja: considerar pedir aclaración al usuario")
        
        if not entities.get("business_type"):
            notes.append("No se detectó tipo de negocio específico")
        
        if not entities.get("niche"):
            notes.append("No se detectó nicho/sector específico")
        
        if corrections:
            notes.append(f"Correcciones aplicadas: {len(corrections)}")
        
        return notes


# Singleton
_interpreter = None

def get_interpreter(load_models: bool = True) -> PromptInterpreter:
    """Obtiene la instancia singleton del intérprete."""
    global _interpreter
    
    if _interpreter is None:
        _interpreter = PromptInterpreter(load_models=load_models)
    
    return _interpreter


def interpret_prompt(prompt: str) -> Dict:
    """
    Función de conveniencia para interpretar un prompt.
    
    Args:
        prompt: Prompt a interpretar
        
    Returns:
        Diccionario con la especificación
    """
    interpreter = get_interpreter()
    spec = interpreter.interpret(prompt)
    return spec.to_dict()
