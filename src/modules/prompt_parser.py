"""
Intelligent Prompt Parser Module
Extracts business type, product category, metrics requirements, and search modifiers from user prompts
"""
import re
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from rapidfuzz import fuzz, process
from loguru import logger

from ..config.settings import (
    BUSINESS_TYPE_SIGNATURES, 
    PRODUCT_CATEGORIES, 
    REQUESTABLE_METRICS
)


@dataclass
class ParsedPrompt:
    """Structured representation of a parsed prompt"""
    original_prompt: str
    business_type: Optional[str] = None
    business_type_confidence: float = 0.0
    product_category: Optional[str] = None
    product_keywords: List[str] = field(default_factory=list)
    required_metrics: List[str] = field(default_factory=list)
    location_filter: Optional[str] = None
    custom_keywords: List[str] = field(default_factory=list)
    exclusion_keywords: List[str] = field(default_factory=list)
    search_queries: List[str] = field(default_factory=list)
    technology_signatures: List[str] = field(default_factory=list)
    is_looking_for_type: bool = True  # True = looking for webs that ARE X, not ABOUT X
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_prompt": self.original_prompt,
            "business_type": self.business_type,
            "business_type_confidence": self.business_type_confidence,
            "product_category": self.product_category,
            "product_keywords": self.product_keywords,
            "required_metrics": self.required_metrics,
            "location_filter": self.location_filter,
            "custom_keywords": self.custom_keywords,
            "exclusion_keywords": self.exclusion_keywords,
            "search_queries": self.search_queries,
            "technology_signatures": self.technology_signatures,
            "is_looking_for_type": self.is_looking_for_type
        }


class PromptParser:
    """
    Intelligent parser that understands user prompts and extracts
    structured information for web searching and verification
    """
    
    # Patterns that indicate user wants webs ABOUT something (not that ARE something)
    ABOUT_PATTERNS = [
        r"informacion sobre",
        r"articulos de",
        r"noticias de",
        r"blogs? que hablen",
        r"webs? que hablen",
        r"que es",
        r"definicion de",
        r"aprende sobre",
        r"tutorial",
        r"guia de"
    ]
    
    # Patterns that indicate user wants webs that ARE something
    TYPE_PATTERNS = [
        r"^ecommerce",
        r"^tienda",
        r"^saas",
        r"^agencia",
        r"^empresa",
        r"^negocio",
        r"^plataforma",
        r"^app",
        r"^software",
        r"^marketplace",
        r"^dropshipping",
        r"webs? que sean",
        r"paginas? que sean",
        r"tiendas? de",
        r"tiendas? online",
        r"ecommerce de",
        r"empresas? de",
        r"agencias? de",
        r"negocios? de"
    ]
    
    # Location patterns
    LOCATION_PATTERNS = [
        r"en (españa|spain|madrid|barcelona|valencia|sevilla)",
        r"en (mexico|méxico|cdmx|guadalajara|monterrey)",
        r"en (argentina|buenos aires)",
        r"en (colombia|bogota|bogotá|medellin|medellín)",
        r"en (chile|santiago)",
        r"en (peru|perú|lima)",
        r"en (usa|estados unidos|eeuu|us)",
        r"españolas?",
        r"mexicanas?",
        r"argentinas?",
        r"colombianas?",
        r"latinoamericanas?",
        r"europeas?"
    ]
    
    def __init__(self):
        self.business_types = list(BUSINESS_TYPE_SIGNATURES.keys())
        self.product_categories = PRODUCT_CATEGORIES
        self.metrics = REQUESTABLE_METRICS
        
    def parse(self, prompt: str) -> ParsedPrompt:
        """
        Parse a user prompt and extract all relevant information
        
        Args:
            prompt: The user's natural language prompt
            
        Returns:
            ParsedPrompt with all extracted information
        """
        logger.info(f"Parsing prompt: {prompt}")
        
        # Normalize prompt
        normalized = self._normalize_prompt(prompt)
        
        # Create result object
        result = ParsedPrompt(original_prompt=prompt)
        
        # Determine if looking for type or about
        result.is_looking_for_type = self._is_looking_for_type(normalized)
        
        # Extract business type
        business_type, confidence = self._extract_business_type(normalized)
        result.business_type = business_type
        result.business_type_confidence = confidence
        
        # Extract product category and keywords
        category, keywords = self._extract_product_info(normalized)
        result.product_category = category
        result.product_keywords = keywords
        
        # Extract required metrics
        result.required_metrics = self._extract_metrics(normalized)
        
        # Extract location
        result.location_filter = self._extract_location(normalized)
        
        # Extract custom keywords (remaining important words)
        result.custom_keywords = self._extract_custom_keywords(normalized, result)
        
        # Generate technology signatures to look for
        result.technology_signatures = self._get_technology_signatures(result)
        
        # Generate exclusion keywords
        result.exclusion_keywords = self._generate_exclusions(result)
        
        # Generate optimized search queries
        result.search_queries = self._generate_search_queries(result)
        
        logger.info(f"Parsed result: business_type={result.business_type}, "
                   f"product_category={result.product_category}, "
                   f"queries_generated={len(result.search_queries)}")
        
        return result
    
    def _normalize_prompt(self, prompt: str) -> str:
        """Normalize the prompt for processing"""
        # Lowercase
        normalized = prompt.lower().strip()
        # Remove extra spaces
        normalized = re.sub(r'\s+', ' ', normalized)
        # Remove special characters but keep accents
        normalized = re.sub(r'[^\w\sáéíóúñü]', ' ', normalized)
        return normalized
    
    def _is_looking_for_type(self, prompt: str) -> bool:
        """
        Determine if user wants webs that ARE something vs webs ABOUT something
        Default is True (looking for type) unless ABOUT patterns detected
        """
        # Check for "about" patterns
        for pattern in self.ABOUT_PATTERNS:
            if re.search(pattern, prompt, re.IGNORECASE):
                logger.debug(f"Detected 'about' pattern: {pattern}")
                return False
        
        # Check for "type" patterns (reinforces default)
        for pattern in self.TYPE_PATTERNS:
            if re.search(pattern, prompt, re.IGNORECASE):
                logger.debug(f"Detected 'type' pattern: {pattern}")
                return True
        
        # Default: assume user wants webs that ARE the thing
        return True
    
    def _extract_business_type(self, prompt: str) -> tuple[Optional[str], float]:
        """
        Extract the business type from the prompt using fuzzy matching
        Returns (business_type, confidence_score)
        """
        # Direct keyword matching first
        for btype, config in BUSINESS_TYPE_SIGNATURES.items():
            # Check if business type name is in prompt
            if btype in prompt:
                return btype, 1.0
            
            # Check aliases/keywords
            for keyword in config.get("keywords", [])[:3]:  # Check first 3 keywords
                if keyword.lower() in prompt:
                    return btype, 0.9
        
        # Fuzzy matching as fallback
        best_match = None
        best_score = 0
        
        for btype in self.business_types:
            # Try fuzzy match on business type name
            score = fuzz.partial_ratio(btype, prompt) / 100
            if score > best_score and score > 0.7:
                best_score = score
                best_match = btype
        
        # Also check against common terms
        business_terms = {
            "tienda online": "ecommerce",
            "tienda de": "ecommerce",
            "tienda virtual": "ecommerce",
            "shop": "ecommerce",
            "store": "ecommerce",
            "comercio electronico": "ecommerce",
            "software como servicio": "saas",
            "aplicacion web": "saas",
            "agencia digital": "agencia",
            "agencia marketing": "agencia",
            "consultora": "agencia",
            "envio directo": "dropshipping",
            "sin stock": "dropshipping",
            "negocio dropshipping": "dropshipping",
            "web corporativa": "corporativo",
            "pagina empresa": "corporativo"
        }
        
        for term, btype in business_terms.items():
            if term in prompt:
                return btype, 0.95
        
        return best_match, best_score
    
    def _extract_product_info(self, prompt: str) -> tuple[Optional[str], List[str]]:
        """
        Extract product category and specific keywords
        Returns (category, [keywords])
        """
        found_category = None
        found_keywords = []
        
        for category, keywords in self.product_categories.items():
            # Check category name
            if category in prompt:
                found_category = category
                found_keywords.extend(keywords)
                break
            
            # Check keywords
            for keyword in keywords:
                if keyword in prompt:
                    found_category = category
                    found_keywords.append(keyword)
        
        # Extract additional product descriptors
        product_patterns = [
            r"de ([\w\s]+?)(?:\s+(?:con|que|en|para)|$)",
            r"productos? ([\w\s]+)",
            r"(?:venta|vender) ([\w\s]+)"
        ]
        
        for pattern in product_patterns:
            matches = re.findall(pattern, prompt)
            for match in matches:
                # Clean and add if not too generic
                clean_match = match.strip()
                if len(clean_match) > 2 and clean_match not in found_keywords:
                    found_keywords.append(clean_match)
        
        return found_category, found_keywords[:5]  # Limit to 5 keywords
    
    def _extract_metrics(self, prompt: str) -> List[str]:
        """Extract any metrics requirements from the prompt"""
        required = []
        
        for metric_key, keywords in self.metrics.items():
            for keyword in keywords:
                if keyword in prompt:
                    required.append(metric_key)
                    break
        
        # Check for specific metric conditions
        metric_conditions = {
            "velocidad lenta": "velocidad",
            "carga lenta": "velocidad",
            "carga rapida": "velocidad",
            "buena velocidad": "velocidad",
            "rapida": "velocidad",
            "buen seo": "seo",
            "mal seo": "seo",
            "optimizada": "seo",
            "mobile friendly": "mobile",
            "responsive": "mobile"
        }
        
        for condition, metric in metric_conditions.items():
            if condition in prompt and metric not in required:
                required.append(metric)
        
        return list(set(required))
    
    def _extract_location(self, prompt: str) -> Optional[str]:
        """Extract location filter from prompt"""
        for pattern in self.LOCATION_PATTERNS:
            match = re.search(pattern, prompt, re.IGNORECASE)
            if match:
                location = match.group(1) if match.groups() else match.group(0)
                return location.strip()
        return None
    
    def _extract_custom_keywords(self, prompt: str, result: ParsedPrompt) -> List[str]:
        """Extract remaining important keywords not captured by other extractors"""
        # Words to exclude (common words, already extracted, etc.)
        exclude_words = {
            "web", "webs", "pagina", "paginas", "sitio", "sitios",
            "que", "sea", "sean", "de", "con", "para", "en", "la", "el",
            "los", "las", "un", "una", "y", "o", "como",
            result.business_type or "", result.product_category or "",
            result.location_filter or ""
        }
        exclude_words.update(result.product_keywords)
        
        # Split prompt and find important words
        words = prompt.split()
        custom = []
        
        for word in words:
            if (len(word) > 3 and 
                word not in exclude_words and 
                not any(word in kw for kw in exclude_words)):
                custom.append(word)
        
        return custom[:5]  # Limit
    
    def _get_technology_signatures(self, result: ParsedPrompt) -> List[str]:
        """Get technology signatures based on detected business type"""
        if result.business_type and result.business_type in BUSINESS_TYPE_SIGNATURES:
            return BUSINESS_TYPE_SIGNATURES[result.business_type].get("technologies", [])
        return []
    
    def _generate_exclusions(self, result: ParsedPrompt) -> List[str]:
        """Generate keywords to exclude from search (anti-patterns)"""
        exclusions = []
        
        # Always exclude educational/informational content when looking for type
        if result.is_looking_for_type:
            exclusions.extend([
                "que es", "definicion", "significado",
                "como crear", "tutorial", "guia",
                "curso", "aprende", "wikipedia"
            ])
        
        # Add business-type specific exclusions
        if result.business_type and result.business_type in BUSINESS_TYPE_SIGNATURES:
            anti = BUSINESS_TYPE_SIGNATURES[result.business_type].get("anti_keywords", [])
            exclusions.extend(anti)
        
        return list(set(exclusions))
    
    def _generate_search_queries(self, result: ParsedPrompt) -> List[str]:
        """
        Generate optimized search queries for Serper API
        These queries are designed to find webs that ARE the type, not ABOUT it
        """
        queries = []
        
        # Base components
        business_type = result.business_type or ""
        product_info = " ".join(result.product_keywords[:2]) if result.product_keywords else ""
        location = result.location_filter or ""
        
        # Get search modifiers for business type
        modifiers = []
        if business_type and business_type in BUSINESS_TYPE_SIGNATURES:
            modifiers = BUSINESS_TYPE_SIGNATURES[business_type].get("search_modifiers", [])
        
        # Build exclusion string
        exclusion_str = " ".join(f"-{ex}" for ex in result.exclusion_keywords[:5])
        
        # Query templates for finding webs that ARE something
        if result.is_looking_for_type:
            templates = [
                # Direct business search
                f"{business_type} {product_info} {location}".strip(),
                
                # With "tienda" prefix for ecommerce
                f"tienda online de {product_info} {location}".strip() if business_type == "ecommerce" else None,
                
                # With modifier
                f"{modifiers[0] if modifiers else ''} {product_info} {location}".strip() if modifiers else None,
                
                # Product focused
                f"comprar {product_info} online {location}".strip() if product_info and business_type == "ecommerce" else None,
                
                # Service focused for agencies
                f"agencia de {product_info} {location}".strip() if business_type == "agencia" else None,
                
                # Software focused for SaaS
                f"software de {product_info} {location}".strip() if business_type == "saas" else None,
            ]
            
            # Add templates with exclusions
            for template in templates:
                if template and template.strip():
                    # Clean query
                    clean = re.sub(r'\s+', ' ', template).strip()
                    if clean and clean not in queries:
                        queries.append(clean)
                    
                    # Version with exclusions
                    with_exclusions = f"{clean} {exclusion_str}".strip()
                    if with_exclusions not in queries:
                        queries.append(with_exclusions)
        
        else:
            # User wants webs ABOUT something (informational)
            templates = [
                f"que es {business_type}",
                f"guia de {business_type}",
                f"blog sobre {business_type}"
            ]
            queries.extend(templates)
        
        # Add original prompt as fallback (cleaned)
        clean_original = re.sub(r'[^\w\s]', '', result.original_prompt)
        if clean_original and clean_original not in queries:
            queries.append(clean_original)
        
        # Filter empty queries and limit
        queries = [q.strip() for q in queries if q and q.strip()]
        queries = list(dict.fromkeys(queries))  # Remove duplicates preserving order
        
        return queries[:8]  # Limit to 8 queries


# Singleton instance
prompt_parser = PromptParser()
