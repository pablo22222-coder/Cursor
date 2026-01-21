"""
Modelos de datos para el sistema de detección de dominios.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


class BusinessType(Enum):
    """Tipos de negocio que el sistema puede detectar."""
    ECOMMERCE = "ecommerce"
    SAAS = "saas"
    AGENCY = "agency"
    BLOG = "blog"
    PORTFOLIO = "portfolio"
    CORPORATE = "corporate"
    MARKETPLACE = "marketplace"
    DROPSHIPPING = "dropshipping"
    SUBSCRIPTION = "subscription"
    SERVICE = "service"
    UNKNOWN = "unknown"


@dataclass
class PromptIntent:
    """
    Representa la intención extraída del prompt del usuario.
    
    Analiza QUÉ tipo de web busca el usuario y QUÉ características debe tener.
    """
    # Tipo de negocio que busca (ecommerce, saas, agencia, etc.)
    business_type: BusinessType
    
    # Nicho o sector específico (electrónica, moda, marketing, etc.)
    niche: Optional[str] = None
    
    # Producto o servicio específico (crema facial, software CRM, etc.)
    product_service: Optional[str] = None
    
    # Características adicionales del prompt
    characteristics: List[str] = field(default_factory=list)
    
    # Métricas específicas que el usuario quiere analizar
    metrics_to_analyze: List[str] = field(default_factory=list)
    
    # El prompt original (sin limpiar)
    original_prompt: str = ""
    
    # El prompt limpio (sin palabras de relleno)
    cleaned_prompt: str = ""
    
    # Exclusiones: tecnologías/características que NO quiere (ej: "sin mailchimp")
    exclusions: List[str] = field(default_factory=list)
    
    # Requisitos: tecnologías/características que SÍ quiere (ej: "con shopify")
    requirements: List[str] = field(default_factory=list)
    
    # Queries de búsqueda generadas
    search_queries: List[str] = field(default_factory=list)
    
    # Nivel de confianza en la interpretación (0-100)
    confidence: int = 0


@dataclass
class TechStack:
    """Tecnologías detectadas en un dominio usando WebTech."""
    
    # CMS detectado (WordPress, Shopify, etc.)
    cms: Optional[str] = None
    
    # Plataforma de ecommerce
    ecommerce_platform: Optional[str] = None
    
    # Frameworks frontend
    frontend_frameworks: List[str] = field(default_factory=list)
    
    # Procesadores de pago detectados
    payment_processors: List[str] = field(default_factory=list)
    
    # Herramientas de analytics
    analytics: List[str] = field(default_factory=list)
    
    # Herramientas de email marketing
    email_marketing: List[str] = field(default_factory=list)
    
    # Todas las tecnologías detectadas (raw)
    all_technologies: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PageSpeedMetrics:
    """Métricas de PageSpeed Insights."""
    
    # Scores principales (0-100)
    performance_score: Optional[int] = None
    seo_score: Optional[int] = None
    accessibility_score: Optional[int] = None
    best_practices_score: Optional[int] = None
    
    # Core Web Vitals
    largest_contentful_paint: Optional[float] = None  # en segundos
    first_input_delay: Optional[float] = None  # en milisegundos
    cumulative_layout_shift: Optional[float] = None
    
    # Tiempo de carga
    speed_index: Optional[float] = None  # en segundos
    time_to_interactive: Optional[float] = None  # en segundos
    
    # Mobile friendly
    is_mobile_friendly: bool = False


@dataclass
class DomainAnalysis:
    """Análisis completo de un dominio."""
    
    # Stack tecnológico
    tech_stack: Optional[TechStack] = None
    
    # Métricas de PageSpeed
    pagespeed: Optional[PageSpeedMetrics] = None
    
    # Tipo de negocio detectado
    detected_business_type: BusinessType = BusinessType.UNKNOWN
    
    # Razones por las que se detectó ese tipo
    detection_reasons: List[str] = field(default_factory=list)
    
    # ¿Cumple con el prompt?
    matches_prompt: bool = False
    
    # Puntuación de coincidencia (0-100)
    match_score: int = 0
    
    # Razones de la puntuación
    match_reasons: List[str] = field(default_factory=list)


@dataclass
class Domain:
    """Representa un dominio encontrado y analizado."""
    
    # URL completa
    url: str
    
    # Dominio base (ejemplo.com)
    domain: str
    
    # Título de la página
    title: Optional[str] = None
    
    # Descripción/snippet
    description: Optional[str] = None
    
    # Posición en resultados de búsqueda
    search_position: int = 0
    
    # Query que lo encontró
    found_by_query: str = ""
    
    # Análisis completo
    analysis: Optional[DomainAnalysis] = None
    
    # Estado del dominio
    is_valid: bool = True
    error_message: Optional[str] = None
    
    def __hash__(self):
        return hash(self.domain)
    
    def __eq__(self, other):
        if isinstance(other, Domain):
            return self.domain == other.domain
        return False
