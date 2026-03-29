"""
Configuración centralizada del proyecto.
Gestiona todas las API keys y configuraciones.

IMPORTANTE: Las API keys se cargan desde variables de entorno.
            Nunca escribir API keys directamente en el código.
            Usar archivo .env en la raíz del proyecto.
"""
import os
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

# Cargar variables de entorno desde .env
def _load_env():
    """Busca y carga el archivo .env desde varias ubicaciones posibles."""
    try:
        from dotenv import load_dotenv
        
        # Posibles ubicaciones del .env
        possible_paths = [
            Path(__file__).parent.parent / '.env',  # /workspace/.env
            Path.cwd() / '.env',  # Directorio actual
            Path.home() / '.env',  # Home del usuario
        ]
        
        for env_path in possible_paths:
            if env_path.exists():
                load_dotenv(env_path, override=True)
                return True
        
        # Intentar load_dotenv sin path (busca automáticamente)
        load_dotenv()
        return True
        
    except ImportError:
        return False  # python-dotenv no instalado

_load_env()


@dataclass
class Settings:
    """
    Configuración principal del sistema.
    
    SEGURIDAD: Las API keys NUNCA deben estar hardcodeadas.
    Se cargan exclusivamente desde variables de entorno (.env o sistema).
    """
    
    # API Keys — Se cargan desde variables de entorno (NUNCA hardcodeadas)
    serper_api_key: str = field(default="")
    gemini_api_key: str = field(default="")
    pagespeed_api_key: str = field(default="")
    # AI Fallback Chain
    groq_api_key: str = field(default="")
    cerebras_api_key: str = field(default="")
    sambanova_api_key: str = field(default="")

    
    # Serper Config
    serper_base_url: str = "https://google.serper.dev/search"
    serper_max_results: int = 30
    
    # WebTech Config
    webtech_timeout: int = 10
    
    # PageSpeed Config
    pagespeed_base_url: str = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
    
    # Gemini Config
    gemini_model: str = "gemini-2.0-flash"
    
    # Validación Config
    max_domains_to_validate: int = 50
    validation_timeout: int = 15
    
    # Búsqueda Config
    search_languages: list = field(default_factory=lambda: ["es", "en"])
    search_countries: list = field(default_factory=lambda: ["es", "us", "mx", "ar", "co"])
    
    def __post_init__(self):
        """Cargar API keys desde variables de entorno."""
        self.serper_api_key    = os.getenv("SERPER_API_KEY", "")
        self.gemini_api_key    = os.getenv("GEMINI_API_KEY", "")
        self.pagespeed_api_key = os.getenv("PAGESPEED_API_KEY", "")
        # AI Fallback Chain
        self.groq_api_key      = os.getenv("GROQ_API_KEY", "")
        self.cerebras_api_key  = os.getenv("CEREBRAS_API_KEY", "")
        self.sambanova_api_key = os.getenv("SAMBANOVA_API_KEY", "")
        
        # Validar que las keys críticas existen
        if not self.serper_api_key:
            print("⚠️  ADVERTENCIA: SERPER_API_KEY no configurada. Las búsquedas no funcionarán.")
        
        if not self.gemini_api_key:
            print("⚠️  ADVERTENCIA: GEMINI_API_KEY no configurada. Se usará análisis local.")
    
    def is_gemini_configured(self) -> bool:
        """Verifica si Gemini está configurado."""
        return bool(self.gemini_api_key and len(self.gemini_api_key) > 10)
    
    def is_serper_configured(self) -> bool:
        """Verifica si Serper está configurado."""
        return bool(self.serper_api_key and len(self.serper_api_key) > 10)


# Singleton para la configuración
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Obtiene la instancia de configuración (singleton)."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """Recarga la configuración (útil si cambian las variables de entorno)."""
    global _settings
    _settings = Settings()
    return _settings
