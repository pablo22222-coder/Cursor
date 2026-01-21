"""
Configuración centralizada del proyecto.
Gestiona todas las API keys y configuraciones.
"""
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Settings:
    """Configuración principal del sistema."""
    
    # API Keys
    serper_api_key: str = "93cde5ee506245ba3c5613b0d1112f248d534be7"
    gemini_api_key: str = "AIzaSyAPKic5KaE4KVMD6-HLDsfCXEAMwUA81LM"
    pagespeed_api_key: str = "AIzaSyBRtOyTpP55RnUuu-2S7-yXiI55yhe0lWo"
    
    # Serper Config
    serper_base_url: str = "https://google.serper.dev/search"
    serper_max_results: int = 30  # Resultados por búsqueda
    
    # WebTech Config
    webtech_timeout: int = 10  # Segundos
    
    # PageSpeed Config
    pagespeed_base_url: str = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
    
    # Gemini Config
    gemini_model: str = "gemini-1.5-flash"
    
    # Validación Config
    max_domains_to_validate: int = 50
    validation_timeout: int = 15
    
    # Búsqueda Config
    search_languages: list = None
    search_countries: list = None
    
    def __post_init__(self):
        # Permitir override desde variables de entorno
        self.serper_api_key = os.getenv("SERPER_API_KEY", self.serper_api_key)
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", self.gemini_api_key)
        self.pagespeed_api_key = os.getenv("PAGESPEED_API_KEY", self.pagespeed_api_key)
        
        if self.search_languages is None:
            self.search_languages = ["es", "en"]
        if self.search_countries is None:
            self.search_countries = ["es", "us", "mx", "ar", "co"]


# Singleton para la configuración
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Obtiene la instancia de configuración (singleton)."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
