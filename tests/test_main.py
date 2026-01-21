"""
Tests para el sistema Domain Finder.
"""
import pytest
import sys
sys.path.insert(0, '/workspace')

from config.settings import Settings, get_settings
from src.prompt_interpreter.gemini_interpreter import GeminiInterpreter, PromptAnalysis


class TestSettings:
    """Tests para la configuración."""
    
    def test_settings_loads(self):
        """Verifica que la configuración se carga correctamente."""
        settings = get_settings()
        assert settings is not None
        assert settings.serper_api_key is not None
        assert settings.gemini_api_key is not None
        assert settings.pagespeed_api_key is not None
    
    def test_settings_singleton(self):
        """Verifica que get_settings retorna singleton."""
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2


class TestPromptAnalysis:
    """Tests para el análisis de prompts."""
    
    def test_prompt_analysis_creation(self):
        """Verifica la creación de PromptAnalysis."""
        analysis = PromptAnalysis(
            business_type="ecommerce",
            product_category="electrónica",
            search_queries=["tienda electronica online"],
            validation_indicators=["comprar", "precio"],
            exclusion_indicators=["qué es"],
            original_prompt="ecommerce de electrónica"
        )
        
        assert analysis.business_type == "ecommerce"
        assert analysis.product_category == "electrónica"
        assert len(analysis.search_queries) > 0
    
    def test_prompt_analysis_to_dict(self):
        """Verifica la conversión a diccionario."""
        analysis = PromptAnalysis(
            business_type="saas",
            original_prompt="test"
        )
        
        data = analysis.to_dict()
        assert "business_type" in data
        assert data["business_type"] == "saas"


class TestGeminiInterpreter:
    """Tests para el intérprete de Gemini."""
    
    def test_basic_analysis(self):
        """Test del análisis básico (fallback)."""
        interpreter = GeminiInterpreter()
        
        # Test análisis básico con prompt de ecommerce
        analysis = interpreter._basic_analysis("ecommerce de ropa")
        assert analysis.business_type == "ecommerce"
        assert len(analysis.search_queries) > 0
    
    def test_basic_analysis_saas(self):
        """Test análisis básico para SaaS."""
        interpreter = GeminiInterpreter()
        
        analysis = interpreter._basic_analysis("software de gestión")
        assert analysis.business_type == "saas"
    
    def test_basic_analysis_agency(self):
        """Test análisis básico para agencia."""
        interpreter = GeminiInterpreter()
        
        analysis = interpreter._basic_analysis("agencia de marketing")
        assert analysis.business_type == "agencia"


# Tests de integración (requieren APIs reales)
@pytest.mark.integration
class TestIntegration:
    """Tests de integración con APIs reales."""
    
    @pytest.mark.skip(reason="Requiere API key válida")
    def test_gemini_full_analysis(self):
        """Test completo del análisis con Gemini."""
        interpreter = GeminiInterpreter()
        analysis = interpreter.analyze_prompt("ecommerce de electrónica")
        
        assert analysis.business_type is not None
        assert len(analysis.search_queries) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
