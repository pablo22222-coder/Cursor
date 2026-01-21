"""
Configuración central del sistema de detección de dominios.
"""
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class APIConfig:
    """Configuración de APIs externas."""
    
    # Serper API (búsqueda en Google)
    SERPER_API_KEY: str = "93cde5ee506245ba3c5613b0d1112f248d534be7"
    SERPER_BASE_URL: str = "https://google.serper.dev/search"
    
    # PageSpeed Insights API (métricas web)
    PAGESPEED_API_KEY: str = "AIzaSyBRtOyTpP55RnUuu-2S7-yXiI55yhe0lWo"
    PAGESPEED_BASE_URL: str = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


@dataclass
class SearchConfig:
    """Configuración de búsqueda."""
    
    # Número máximo de resultados por búsqueda
    MAX_RESULTS_PER_SEARCH: int = 10
    
    # Número máximo de búsquedas diferentes para un prompt
    MAX_SEARCH_VARIATIONS: int = 5
    
    # Timeout para requests HTTP (segundos)
    HTTP_TIMEOUT: int = 10
    
    # Idioma por defecto para búsquedas
    DEFAULT_LANGUAGE: str = "es"
    
    # País por defecto para búsquedas
    DEFAULT_COUNTRY: str = "es"


@dataclass
class ValidationConfig:
    """Configuración de validación de dominios."""
    
    # Timeout para WebTech (segundos)
    WEBTECH_TIMEOUT: int = 5
    
    # Número máximo de dominios a validar en paralelo
    MAX_CONCURRENT_VALIDATIONS: int = 5
    
    # Umbral de confianza mínimo para considerar un dominio válido (0-100)
    MIN_CONFIDENCE_SCORE: int = 60


@dataclass
class Settings:
    """Configuración global del sistema."""
    
    api: APIConfig
    search: SearchConfig
    validation: ValidationConfig
    
    @classmethod
    def load(cls) -> "Settings":
        """Carga la configuración desde variables de entorno o valores por defecto."""
        return cls(
            api=APIConfig(
                SERPER_API_KEY=os.getenv("SERPER_API_KEY", APIConfig.SERPER_API_KEY),
                PAGESPEED_API_KEY=os.getenv("PAGESPEED_API_KEY", APIConfig.PAGESPEED_API_KEY),
            ),
            search=SearchConfig(),
            validation=ValidationConfig(),
        )


# Instancia global de configuración
settings = Settings.load()
