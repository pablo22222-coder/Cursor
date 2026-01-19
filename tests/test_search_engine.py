"""
Tests for the Search Engine module
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.modules.search_engine import SearchEngine, SearchResult
from src.modules.prompt_parser import ParsedPrompt


class TestSearchEngine:
    """Tests for SearchEngine"""
    
    def setup_method(self):
        self.engine = SearchEngine(api_key=None)  # No API key for unit tests
    
    def test_extract_domain(self):
        """Test domain extraction from URLs"""
        assert self.engine._extract_domain("https://www.example.com/path") == "example.com"
        assert self.engine._extract_domain("http://example.com") == "example.com"
        assert self.engine._extract_domain("https://subdomain.example.com") == "subdomain.example.com"
    
    def test_excluded_domains(self):
        """Test that known platforms are excluded"""
        # Educational/Platform sites should be excluded
        assert self.engine._is_excluded_domain("wikipedia.org")
        assert self.engine._is_excluded_domain("shopify.com")  # Platform, not store
        assert self.engine._is_excluded_domain("youtube.com")
        assert self.engine._is_excluded_domain("medium.com")
        
        # Regular domains should not be excluded
        assert not self.engine._is_excluded_domain("mystore.com")
        assert not self.engine._is_excluded_domain("randomsite.es")
    
    def test_business_type_exclusions(self):
        """Test business-type specific exclusions"""
        # For ecommerce searches, platform sites should be excluded
        assert self.engine._is_excluded_domain("shopify.com", "ecommerce")
        assert self.engine._is_excluded_domain("bigcommerce.com", "ecommerce")
        
        # For SaaS searches, review sites should be excluded
        assert self.engine._is_excluded_domain("g2.com", "saas")
        assert self.engine._is_excluded_domain("capterra.com", "saas")
    
    def test_is_likely_educational(self):
        """Test detection of educational content"""
        # Educational content
        assert self.engine._is_likely_educational(
            "Qué es el ecommerce - Guía completa",
            "Aprende todo sobre el comercio electrónico"
        )
        
        assert self.engine._is_likely_educational(
            "Cómo crear una tienda online - Tutorial",
            "Paso a paso para montar tu negocio"
        )
        
        # Not educational
        assert not self.engine._is_likely_educational(
            "Tienda de Electrónica - Compra Online",
            "Los mejores precios en smartphones y tablets"
        )
    
    def test_check_relevance_indicators(self):
        """Test relevance indicator detection"""
        parsed = ParsedPrompt(
            original_prompt="ecommerce de electronica",
            business_type="ecommerce",
            product_keywords=["electronica", "smartphones"]
        )
        
        # Should find positive indicators
        indicators = self.engine._check_relevance_indicators(
            "Tienda de Electrónica Online",
            "Compra smartphones y tablets con envío gratis. Los mejores precios.",
            parsed
        )
        
        # Should have some positive indicators
        positive = [i for i in indicators if not i.startswith("negative:")]
        assert len(positive) > 0
    
    def test_relevance_negative_indicators(self):
        """Test negative indicator detection"""
        parsed = ParsedPrompt(
            original_prompt="ecommerce",
            business_type="ecommerce"
        )
        
        # Should find negative indicators for educational content
        indicators = self.engine._check_relevance_indicators(
            "Qué es ecommerce - Definición",
            "Tutorial completo sobre cómo crear tu tienda",
            parsed
        )
        
        negative = [i for i in indicators if i.startswith("negative:")]
        assert len(negative) > 0


class TestSearchResult:
    """Tests for SearchResult data class"""
    
    def test_to_dict(self):
        """Test to_dict method"""
        result = SearchResult(
            url="https://example.com",
            domain="example.com",
            title="Test",
            snippet="Test snippet",
            position=1,
            query_used="test query",
            relevance_indicators=["test:indicator"]
        )
        
        d = result.to_dict()
        
        assert d["url"] == "https://example.com"
        assert d["domain"] == "example.com"
        assert d["position"] == 1
        assert "test:indicator" in d["relevance_indicators"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
