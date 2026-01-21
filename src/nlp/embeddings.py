"""
Motor de Embeddings para tolerancia a errores y comprensión semántica.

Usa:
- FastText: embeddings subword (tolera errores ortográficos)
- Sentence-Transformers: embeddings de frases (captura intención)
- Cosine similarity: comparación de vectores
"""
import os
import numpy as np
from typing import List, Dict, Optional, Tuple
from pathlib import Path


class EmbeddingEngine:
    """
    Motor de embeddings dual:
    - FastText para tolerancia a errores ortográficos (subword)
    - Sentence-Transformers para comprensión semántica (frases)
    """
    
    # Conceptos de negocio para matching semántico
    BUSINESS_CONCEPTS = {
        "ecommerce": [
            "tienda online", "comprar productos", "carrito de compra",
            "venta por internet", "comercio electrónico", "shop online"
        ],
        "agency": [
            "agencia de servicios", "consultora", "empresa de marketing",
            "estudio de diseño", "servicios profesionales"
        ],
        "saas": [
            "software como servicio", "aplicación web", "plataforma online",
            "herramienta digital", "software en la nube"
        ],
        "dropshipping": [
            "tienda dropshipping", "venta sin stock", "envío directo",
            "negocio online sin inventario"
        ],
    }
    
    # Nichos/categorías para matching
    NICHE_CONCEPTS = {
        "moda": ["ropa", "vestimenta", "fashion", "textil", "prendas", "calzado", "accesorios"],
        "tecnologia": ["electrónica", "gadgets", "ordenadores", "móviles", "tech", "informática"],
        "belleza": ["cosmética", "skincare", "maquillaje", "cuidado personal", "beauty"],
        "marketing": ["publicidad", "marketing digital", "seo", "redes sociales", "ads"],
        "salud": ["bienestar", "fitness", "suplementos", "farmacia", "nutrición"],
        "hogar": ["muebles", "decoración", "jardín", "casa", "inmobiliaria"],
        "alimentacion": ["comida", "bebidas", "gourmet", "orgánico", "food"],
        "deportes": ["fitness", "gym", "outdoor", "running", "ciclismo"],
        "mascotas": ["perros", "gatos", "animales", "veterinaria", "pet shop"],
        "infantil": ["bebés", "niños", "juguetes", "maternidad", "kids"],
        "joyeria": ["joyas", "relojes", "accesorios", "bisutería", "luxury"],
        # Software/SaaS nichos
        "crm": ["gestión de clientes", "customer relationship", "ventas", "leads", "pipeline"],
        "erp": ["gestión empresarial", "recursos empresa", "planificación", "enterprise"],
        "gestion_proyectos": ["project management", "tareas", "equipos", "colaboración", "proyectos"],
        "contabilidad": ["finanzas", "accounting", "facturas", "impuestos", "contable"],
        "inventario": ["stock", "almacén", "warehouse", "productos", "inventario"],
        "rrhh": ["recursos humanos", "empleados", "nóminas", "hr", "talento"],
        "email_marketing": ["newsletter", "campañas email", "mailing", "automatización email"],
    }
    
    def __init__(self, load_models: bool = True):
        """
        Inicializa el motor de embeddings.
        
        Args:
            load_models: Si cargar los modelos al inicializar
        """
        self.sentence_model = None
        self.fasttext_model = None
        self._models_loaded = False
        
        # Cache de embeddings precalculados
        self._concept_embeddings = {}
        self._niche_embeddings = {}
        
        if load_models:
            self._load_models()
    
    def _load_models(self):
        """Carga los modelos de embeddings."""
        # Cargar Sentence-Transformers (ligero y suficiente)
        try:
            from sentence_transformers import SentenceTransformer
            self.sentence_model = SentenceTransformer('all-MiniLM-L6-v2')
            print("✓ Sentence-Transformers cargado")
        except Exception as e:
            print(f"⚠ No se pudo cargar Sentence-Transformers: {e}")
            self.sentence_model = None
        
        # FastText es OPCIONAL - no lo cargamos automáticamente
        # porque el modelo español es muy grande (~4GB)
        # Solo se usa si ya existe el modelo en cache
        try:
            import fasttext
            from pathlib import Path
            
            model_path = Path.home() / ".cache" / "fasttext" / "cc.es.50.bin"
            
            if model_path.exists():
                self.fasttext_model = fasttext.load_model(str(model_path))
                print("✓ FastText cargado (desde cache)")
            else:
                # NO descargar automáticamente - es muy grande
                print("ℹ FastText no disponible (modelo no descargado)")
                print("  El sistema funciona correctamente sin él")
                self.fasttext_model = None
        except Exception as e:
            self.fasttext_model = None
        
        self._models_loaded = True
        
        # Precalcular embeddings de conceptos
        if self.sentence_model:
            self._precompute_concept_embeddings()
    
    def _precompute_concept_embeddings(self):
        """Precalcula embeddings de conceptos de negocio y nichos."""
        if not self.sentence_model:
            return
        
        # Embeddings de tipos de negocio
        for business_type, phrases in self.BUSINESS_CONCEPTS.items():
            embeddings = self.sentence_model.encode(phrases)
            self._concept_embeddings[business_type] = np.mean(embeddings, axis=0)
        
        # Embeddings de nichos
        for niche, phrases in self.NICHE_CONCEPTS.items():
            embeddings = self.sentence_model.encode(phrases)
            self._niche_embeddings[niche] = np.mean(embeddings, axis=0)
    
    def get_sentence_embedding(self, text: str) -> Optional[np.ndarray]:
        """
        Obtiene embedding de frase usando Sentence-Transformers.
        
        Captura la intención semántica completa de la frase.
        
        Args:
            text: Texto a embeber
            
        Returns:
            Vector de embedding o None si no hay modelo
        """
        if not self.sentence_model:
            return None
        
        return self.sentence_model.encode(text)
    
    def get_subword_embedding(self, text: str) -> Optional[np.ndarray]:
        """
        Obtiene embedding subword usando FastText.
        
        Tolerante a errores ortográficos por usar subwords.
        
        Args:
            text: Texto a embeber
            
        Returns:
            Vector de embedding o None si no hay modelo
        """
        if not self.fasttext_model:
            return None
        
        return self.fasttext_model.get_sentence_vector(text)
    
    def get_dual_embedding(self, text: str) -> Dict[str, Optional[np.ndarray]]:
        """
        Obtiene ambos embeddings (sentence y subword).
        
        Args:
            text: Texto a embeber
            
        Returns:
            Dict con 'sentence' y 'subword' embeddings
        """
        return {
            "sentence": self.get_sentence_embedding(text),
            "subword": self.get_subword_embedding(text)
        }
    
    def cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """
        Calcula similitud coseno entre dos vectores.
        
        Args:
            vec1: Primer vector
            vec2: Segundo vector
            
        Returns:
            Similitud entre 0 y 1
        """
        if vec1 is None or vec2 is None:
            return 0.0
        
        dot = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot / (norm1 * norm2)
    
    def detect_business_type(self, text: str) -> Tuple[str, float]:
        """
        Detecta el tipo de negocio usando similitud semántica.
        
        Args:
            text: Prompt del usuario
            
        Returns:
            Tuple de (tipo detectado, confianza 0-1)
        """
        if not self.sentence_model or not self._concept_embeddings:
            return "unknown", 0.0
        
        text_embedding = self.get_sentence_embedding(text)
        
        best_type = "unknown"
        best_score = 0.0
        
        for business_type, concept_embedding in self._concept_embeddings.items():
            similarity = self.cosine_similarity(text_embedding, concept_embedding)
            if similarity > best_score:
                best_score = similarity
                best_type = business_type
        
        # Solo considerar válido si supera umbral
        if best_score < 0.3:
            return "unknown", best_score
        
        return best_type, best_score
    
    def detect_niche(self, text: str) -> Tuple[Optional[str], float]:
        """
        Detecta el nicho/categoría usando similitud semántica.
        
        Args:
            text: Prompt del usuario
            
        Returns:
            Tuple de (nicho detectado, confianza 0-1)
        """
        if not self.sentence_model or not self._niche_embeddings:
            return None, 0.0
        
        text_embedding = self.get_sentence_embedding(text)
        
        best_niche = None
        best_score = 0.0
        
        for niche, niche_embedding in self._niche_embeddings.items():
            similarity = self.cosine_similarity(text_embedding, niche_embedding)
            if similarity > best_score:
                best_score = similarity
                best_niche = niche
        
        # Solo considerar válido si supera umbral
        if best_score < 0.25:
            return None, best_score
        
        return best_niche, best_score
    
    def find_similar_terms(self, term: str, candidates: List[str], top_k: int = 3) -> List[Tuple[str, float]]:
        """
        Encuentra términos similares usando embeddings.
        
        Útil para corregir errores ortográficos de forma inteligente.
        
        Args:
            term: Término a buscar
            candidates: Lista de candidatos correctos
            top_k: Número de resultados a devolver
            
        Returns:
            Lista de (candidato, similitud) ordenada por similitud
        """
        if not self.fasttext_model:
            return []
        
        term_vec = self.get_subword_embedding(term)
        
        similarities = []
        for candidate in candidates:
            candidate_vec = self.get_subword_embedding(candidate)
            sim = self.cosine_similarity(term_vec, candidate_vec)
            similarities.append((candidate, sim))
        
        # Ordenar por similitud descendente
        similarities.sort(key=lambda x: x[1], reverse=True)
        
        return similarities[:top_k]
    
    def is_semantically_similar(self, text1: str, text2: str, threshold: float = 0.7) -> bool:
        """
        Verifica si dos textos son semánticamente similares.
        
        Args:
            text1: Primer texto
            text2: Segundo texto
            threshold: Umbral de similitud (0-1)
            
        Returns:
            True si son similares
        """
        emb1 = self.get_sentence_embedding(text1)
        emb2 = self.get_sentence_embedding(text2)
        
        if emb1 is None or emb2 is None:
            return False
        
        return self.cosine_similarity(emb1, emb2) >= threshold


# Singleton para evitar cargar modelos múltiples veces
_embedding_engine = None

def get_embedding_engine(load_models: bool = True) -> EmbeddingEngine:
    """
    Obtiene la instancia singleton del motor de embeddings.
    
    Args:
        load_models: Si cargar los modelos
        
    Returns:
        Instancia de EmbeddingEngine
    """
    global _embedding_engine
    
    if _embedding_engine is None:
        _embedding_engine = EmbeddingEngine(load_models=load_models)
    
    return _embedding_engine
