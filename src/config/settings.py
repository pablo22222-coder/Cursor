"""
Configuration settings for Web Domain Finder
"""
import os
from typing import Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()


class APISettings(BaseModel):
    """API Keys and endpoints configuration"""
    serper_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("SERPER_API_KEY"))
    pagespeed_api_key: str = "AIzaSyBRtOyTpP55RnUuu-2S7-yXiI55yhe0lWo"
    
    # API Endpoints
    serper_endpoint: str = "https://google.serper.dev/search"
    pagespeed_endpoint: str = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


class SearchSettings(BaseModel):
    """Search configuration"""
    max_results_per_query: int = 10
    max_total_results: int = 50
    search_languages: list = ["es", "en"]
    search_countries: list = ["es", "us", "mx", "ar", "co"]
    timeout_seconds: int = 30
    

class AnalysisSettings(BaseModel):
    """Analysis configuration"""
    webtech_timeout: int = 10
    pagespeed_timeout: int = 30
    max_concurrent_analysis: int = 5
    enable_pagespeed: bool = True
    enable_webtech: bool = True


class ScoringSettings(BaseModel):
    """Scoring weights for domain matching"""
    technology_match_weight: float = 0.35
    content_match_weight: float = 0.30
    metrics_match_weight: float = 0.20
    domain_quality_weight: float = 0.15
    minimum_score_threshold: float = 0.60


class Settings(BaseModel):
    """Main settings container"""
    api: APISettings = Field(default_factory=APISettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    analysis: AnalysisSettings = Field(default_factory=AnalysisSettings)
    scoring: ScoringSettings = Field(default_factory=ScoringSettings)


# Global settings instance
settings = Settings()


# Business type definitions with their technology signatures
BUSINESS_TYPE_SIGNATURES = {
    "ecommerce": {
        "keywords": ["tienda online", "shop", "store", "comprar", "carrito", "checkout"],
        "technologies": ["Shopify", "WooCommerce", "Magento", "PrestaShop", "BigCommerce", 
                        "OpenCart", "Wix Stores", "Squarespace Commerce", "Stripe", "PayPal"],
        "search_modifiers": [
            "tienda online de", "comprar", "shop", "store", 
            "-que es -definicion -como crear -tutorial -guia"
        ],
        "anti_keywords": ["blog", "noticias", "que es", "definicion", "como crear", "tutorial"]
    },
    "saas": {
        "keywords": ["software", "plataforma", "app", "dashboard", "login", "signup", "pricing", "plans"],
        "technologies": ["React", "Vue.js", "Angular", "Node.js", "Stripe", "Intercom", "Drift"],
        "search_modifiers": [
            "software para", "plataforma de", "herramienta de",
            "-que es saas -definicion -tutorial"
        ],
        "anti_keywords": ["que es saas", "definicion", "tutorial", "blog"]
    },
    "agencia": {
        "keywords": ["agencia", "servicios", "portfolio", "clientes", "contacto", "proyectos"],
        "technologies": ["WordPress", "Webflow", "Squarespace", "HubSpot", "Calendly"],
        "search_modifiers": [
            "agencia de", "servicios de", "empresa de",
            "-ofertas empleo -trabajo -vacantes"
        ],
        "anti_keywords": ["empleo", "trabajo", "vacantes", "ofertas"]
    },
    "dropshipping": {
        "keywords": ["tienda", "productos", "envio gratis", "oferta", "descuento"],
        "technologies": ["Shopify", "AliExpress", "Oberlo", "Spocket", "DSers", "Stripe"],
        "search_modifiers": [
            "tienda de", "comprar", "productos de",
            "-que es dropshipping -como hacer -tutorial -guia"
        ],
        "anti_keywords": ["que es dropshipping", "como hacer", "tutorial", "guia", "curso"]
    },
    "blog": {
        "keywords": ["blog", "articulos", "posts", "autor", "categorias"],
        "technologies": ["WordPress", "Ghost", "Medium", "Substack", "Blogger"],
        "search_modifiers": ["blog de", "articulos sobre"],
        "anti_keywords": []
    },
    "marketplace": {
        "keywords": ["marketplace", "vendedores", "comprar", "vender", "productos"],
        "technologies": ["Shopify", "WooCommerce", "Magento", "Stripe", "PayPal"],
        "search_modifiers": [
            "marketplace de", "comprar y vender",
            "-que es marketplace -definicion"
        ],
        "anti_keywords": ["que es marketplace", "definicion"]
    },
    "landing": {
        "keywords": ["landing", "registro", "suscribete", "descarga", "prueba gratis"],
        "technologies": ["Unbounce", "Leadpages", "Instapage", "ClickFunnels", "Mailchimp"],
        "search_modifiers": [],
        "anti_keywords": []
    },
    "corporativo": {
        "keywords": ["empresa", "sobre nosotros", "mision", "vision", "equipo", "historia"],
        "technologies": ["WordPress", "Webflow", "Squarespace"],
        "search_modifiers": ["empresa de", "compañia de"],
        "anti_keywords": []
    },
    "restaurante": {
        "keywords": ["menu", "reservar", "carta", "restaurante", "pedidos"],
        "technologies": ["WordPress", "Squarespace", "Wix", "OpenTable", "TheFork"],
        "search_modifiers": ["restaurante", "bar", "cafeteria"],
        "anti_keywords": ["recetas", "como cocinar"]
    },
    "inmobiliaria": {
        "keywords": ["inmuebles", "propiedades", "alquiler", "venta", "pisos", "casas"],
        "technologies": ["WordPress", "Jestate", "Inmovilla"],
        "search_modifiers": ["inmobiliaria", "venta de pisos", "alquiler de"],
        "anti_keywords": ["portal inmobiliario", "idealista", "fotocasa"]
    }
}


# Product/Service categories for more specific matching
PRODUCT_CATEGORIES = {
    "electronica": ["smartphones", "ordenadores", "tablets", "accesorios", "gadgets"],
    "moda": ["ropa", "zapatos", "accesorios", "bolsos", "vestidos"],
    "belleza": ["cosmeticos", "cremas", "maquillaje", "skincare", "cuidado facial"],
    "deportes": ["fitness", "running", "gym", "yoga", "equipamiento"],
    "hogar": ["decoracion", "muebles", "cocina", "jardin"],
    "alimentacion": ["comida", "bebidas", "gourmet", "organico"],
    "mascotas": ["perros", "gatos", "accesorios mascotas"],
    "juguetes": ["juegos", "niños", "educativos"],
    "salud": ["suplementos", "vitaminas", "bienestar"],
    "automotive": ["coches", "motos", "accesorios vehiculos"]
}


# Metrics that can be requested in prompts
REQUESTABLE_METRICS = {
    "velocidad": ["performance", "speed", "carga"],
    "seo": ["seo", "posicionamiento", "optimizacion"],
    "mobile": ["movil", "responsive", "mobile friendly"],
    "accesibilidad": ["accesible", "accessibility"],
    "seguridad": ["https", "ssl", "seguro"]
}
