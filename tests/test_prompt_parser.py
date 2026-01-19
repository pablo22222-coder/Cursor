"""
Tests for the Prompt Parser module
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.modules.prompt_parser import PromptParser, ParsedPrompt


class TestPromptParser:
    """Tests for PromptParser"""
    
    def setup_method(self):
        self.parser = PromptParser()
    
    def test_parse_ecommerce_basic(self):
        """Test parsing basic ecommerce prompt"""
        result = self.parser.parse("ecommerce")
        
        assert result.business_type == "ecommerce"
        assert result.is_looking_for_type == True
        assert result.business_type_confidence > 0.8
    
    def test_parse_ecommerce_with_product(self):
        """Test parsing ecommerce with product category"""
        result = self.parser.parse("ecommerce de electronica")
        
        assert result.business_type == "ecommerce"
        assert result.product_category == "electronica"
        assert "electronica" in result.product_keywords or result.product_category == "electronica"
    
    def test_parse_ecommerce_spanish(self):
        """Test parsing Spanish ecommerce prompt"""
        result = self.parser.parse("tienda online de ropa")
        
        assert result.business_type == "ecommerce"
        assert "ropa" in result.product_keywords or "ropa" in result.original_prompt
    
    def test_parse_agency(self):
        """Test parsing agency prompt"""
        result = self.parser.parse("agencia de marketing digital")
        
        assert result.business_type == "agencia"
        assert result.is_looking_for_type == True
    
    def test_parse_saas(self):
        """Test parsing SaaS prompt"""
        result = self.parser.parse("saas de gestion de proyectos")
        
        assert result.business_type == "saas"
    
    def test_parse_with_location(self):
        """Test parsing prompt with location"""
        result = self.parser.parse("ecommerce de moda en España")
        
        assert result.business_type == "ecommerce"
        assert result.location_filter is not None
        assert "españa" in result.location_filter.lower() or "spain" in (result.location_filter or "").lower()
    
    def test_parse_with_metrics(self):
        """Test parsing prompt with metric requirements"""
        result = self.parser.parse("ecommerce con buena velocidad de carga")
        
        assert result.business_type == "ecommerce"
        assert "velocidad" in result.required_metrics
    
    def test_detect_educational_intent(self):
        """Test detection of educational/informational intent"""
        result = self.parser.parse("que es ecommerce")
        
        # Should detect this is asking ABOUT ecommerce, not looking for ecommerce sites
        assert result.is_looking_for_type == False
    
    def test_detect_type_intent(self):
        """Test detection of type-seeking intent"""
        result = self.parser.parse("tiendas de electronica")
        
        assert result.is_looking_for_type == True
    
    def test_exclusion_keywords_generated(self):
        """Test that exclusion keywords are generated"""
        result = self.parser.parse("ecommerce")
        
        assert len(result.exclusion_keywords) > 0
        assert any("tutorial" in kw or "definicion" in kw for kw in result.exclusion_keywords)
    
    def test_search_queries_generated(self):
        """Test that search queries are generated"""
        result = self.parser.parse("ecommerce de electronica")
        
        assert len(result.search_queries) > 0
        # Should include the main terms
        assert any("electro" in q.lower() for q in result.search_queries)
    
    def test_technology_signatures(self):
        """Test that technology signatures are set for known types"""
        result = self.parser.parse("ecommerce")
        
        assert len(result.technology_signatures) > 0
        assert any("Shopify" in tech or "WooCommerce" in tech 
                  for tech in result.technology_signatures)
    
    def test_dropshipping_detection(self):
        """Test dropshipping business type detection"""
        result = self.parser.parse("dropshipping de productos")
        
        assert result.business_type == "dropshipping"
    
    def test_corporate_detection(self):
        """Test corporate website detection"""
        result = self.parser.parse("web corporativa de empresa")
        
        assert result.business_type == "corporativo"
    
    def test_complex_prompt(self):
        """Test parsing complex multi-part prompt"""
        result = self.parser.parse(
            "tienda online de crema facial de belleza en Madrid"
        )
        
        assert result.business_type == "ecommerce"
        assert result.product_category == "belleza" or "crema" in result.product_keywords
        assert result.location_filter is not None
    
    def test_metrics_detection_explicit(self):
        """Test that explicit metric keywords are detected"""
        result = self.parser.parse("ecommerce con carga rapida y buen seo")
        
        assert result.business_type == "ecommerce"
        # Should detect velocity/performance metric
        assert "velocidad" in result.required_metrics or "seo" in result.required_metrics


class TestParsedPrompt:
    """Tests for ParsedPrompt data class"""
    
    def test_to_dict(self):
        """Test to_dict method"""
        prompt = ParsedPrompt(
            original_prompt="test",
            business_type="ecommerce",
            product_keywords=["test"]
        )
        
        result = prompt.to_dict()
        
        assert isinstance(result, dict)
        assert result["original_prompt"] == "test"
        assert result["business_type"] == "ecommerce"
        assert result["product_keywords"] == ["test"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
