"""
Intérprete de prompts usando Gemini.
Analiza el prompt del usuario para entender qué tipo de web busca.
"""
import json
import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import google.generativeai as genai

from config.settings import get_settings
from src.prompt_interpreter.query_generator import QueryGenerator


@dataclass
class PromptAnalysis:
    """Resultado del análisis del prompt."""
    
    # Tipo de negocio/web que busca
    business_type: str  # ecommerce, saas, agencia, blog, etc.
    
    # Especificaciones adicionales
    product_category: Optional[str] = None  # electrónica, ropa, cosméticos, etc.
    service_type: Optional[str] = None  # marketing digital, desarrollo web, etc.
    niche: Optional[str] = None  # old money, luxury, budget, etc.
    target_audience: Optional[str] = None  # B2B, B2C, empresas, consumidores
    
    # Métricas a evaluar (si el prompt lo especifica)
    check_performance: bool = False  # Verificar velocidad de carga
    check_seo: bool = False  # Verificar SEO score
    check_mobile: bool = False  # Verificar mobile-friendly
    performance_criteria: Optional[str] = None  # "lenta", "rápida", etc.
    
    # Tecnologías específicas a buscar
    required_technologies: List[str] = field(default_factory=list)  # WordPress, Shopify, etc.
    excluded_technologies: List[str] = field(default_factory=list)
    
    # Queries de búsqueda generadas
    search_queries: List[str] = field(default_factory=list)
    
    # Indicadores para validación
    validation_indicators: List[str] = field(default_factory=list)  # Palabras clave que indican que la web ES lo buscado
    exclusion_indicators: List[str] = field(default_factory=list)  # Palabras que indican que NO es lo buscado
    
    # Prompt original
    original_prompt: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario."""
        return {
            "business_type": self.business_type,
            "product_category": self.product_category,
            "service_type": self.service_type,
            "niche": self.niche,
            "target_audience": self.target_audience,
            "check_performance": self.check_performance,
            "check_seo": self.check_seo,
            "check_mobile": self.check_mobile,
            "performance_criteria": self.performance_criteria,
            "required_technologies": self.required_technologies,
            "excluded_technologies": self.excluded_technologies,
            "search_queries": self.search_queries,
            "validation_indicators": self.validation_indicators,
            "exclusion_indicators": self.exclusion_indicators,
            "original_prompt": self.original_prompt
        }


class GeminiInterpreter:
    """Usa Gemini para interpretar y analizar prompts de búsqueda de webs."""
    
    def __init__(self):
        settings = get_settings()
        genai.configure(api_key=settings.gemini_api_key)
        self.model = genai.GenerativeModel(settings.gemini_model)
    
    def analyze_prompt(self, prompt: str) -> PromptAnalysis:
        """
        Analiza el prompt del usuario y extrae toda la información relevante.
        
        Args:
            prompt: El prompt del usuario describiendo qué webs busca
            
        Returns:
            PromptAnalysis con toda la información extraída
        """
        system_prompt = self._build_analysis_prompt(prompt)
        
        try:
            response = self.model.generate_content(system_prompt)
            analysis_data = self._parse_response(response.text)
            analysis_data["original_prompt"] = prompt
            return PromptAnalysis(**analysis_data)
        except Exception as e:
            print(f"Error analizando prompt con Gemini: {e}")
            # Fallback básico
            return self._basic_analysis(prompt)
    
    def _build_analysis_prompt(self, user_prompt: str) -> str:
        """Construye el prompt para Gemini."""
        return f"""Eres un experto en análisis de búsquedas web. Tu tarea es analizar el siguiente prompt de búsqueda y extraer información estructurada.

IMPORTANTE: El usuario quiere encontrar WEBS QUE SEAN lo que describe, NO webs que hablen sobre el tema.
Por ejemplo:
- "ecommerce" = quiere encontrar tiendas online reales, NO artículos sobre qué es ecommerce
- "agencia de marketing digital" = quiere encontrar agencias reales, NO blogs sobre marketing
- "saas de gestión de proyectos" = quiere encontrar herramientas SaaS reales, NO reviews

PROMPT DEL USUARIO: "{user_prompt}"

Analiza el prompt y devuelve un JSON con esta estructura EXACTA:

{{
    "business_type": "tipo de negocio/web (ecommerce, saas, agencia, blog, directorio, marketplace, portfolio, landing, corporativa, app, plataforma, servicio, consultoria, etc.)",
    "product_category": "categoría de productos si aplica (electrónica, ropa, cosméticos, alimentos, etc.) o null",
    "service_type": "tipo de servicio si aplica (marketing digital, desarrollo web, consultoría, etc.) o null",
    "niche": "nicho específico si se menciona (luxury, budget, old money, vintage, eco-friendly, etc.) o null",
    "target_audience": "audiencia objetivo si se menciona (B2B, B2C, empresas, consumidores, etc.) o null",
    "check_performance": true/false si el prompt menciona velocidad o rendimiento,
    "check_seo": true/false si el prompt menciona SEO o posicionamiento,
    "check_mobile": true/false si el prompt menciona móvil o responsive,
    "performance_criteria": "lenta/rápida/etc si se especifica, sino null",
    "required_technologies": ["lista de tecnologías requeridas como WordPress, Shopify, etc."],
    "excluded_technologies": ["lista de tecnologías a excluir"],
    "search_queries": [
        "GENERA 5-10 queries de búsqueda inteligentes para encontrar WEBS QUE SEAN esto, no que hablen de ello",
        "Usa formatos como: 'comprar [producto] online', '[tipo negocio] [ciudad/país]', 'tienda de [categoría]'",
        "Para ecommerce: 'tienda online de X', 'comprar X online', 'shop X'",
        "Para servicios: 'contratar [servicio]', '[servicio] para empresas'",
        "Para SaaS: '[tipo] software', '[tipo] tool', '[tipo] platform'",
        "Incluye variaciones en español e inglés"
    ],
    "validation_indicators": [
        "Lista de palabras/frases que indicarían que una web ES lo que buscamos",
        "Por ejemplo para ecommerce: 'añadir al carrito', 'comprar ahora', 'precio', 'envío'",
        "Para agencias: 'nuestros servicios', 'portfolio', 'contactar', 'presupuesto'"
    ],
    "exclusion_indicators": [
        "Lista de palabras/frases que indicarían que una web NO es lo que buscamos",
        "Por ejemplo: 'qué es', 'definición', 'guía de', 'cómo crear', 'artículo', 'wikipedia'"
    ]
}}

IMPORTANTE para search_queries:
- NO generes queries como "qué es ecommerce" o "mejores plataformas ecommerce"
- SÍ genera queries que encuentren webs reales del tipo buscado
- Incluye nombres de ciudades o países si es relevante
- Usa términos que los clientes usarían para encontrar ese tipo de negocio

Responde SOLO con el JSON, sin texto adicional ni markdown."""

    def _parse_response(self, response_text: str) -> Dict[str, Any]:
        """Parsea la respuesta de Gemini."""
        # Limpiar el texto de posibles marcadores de código
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            # Remover marcadores de código markdown
            cleaned = re.sub(r'^```(?:json)?\n?', '', cleaned)
            cleaned = re.sub(r'\n?```$', '', cleaned)
        
        try:
            data = json.loads(cleaned)
            return data
        except json.JSONDecodeError:
            # Intentar extraer JSON del texto
            json_match = re.search(r'\{[\s\S]*\}', cleaned)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except:
                    pass
            raise ValueError(f"No se pudo parsear la respuesta de Gemini: {response_text[:500]}")
    
    def _basic_analysis(self, prompt: str) -> PromptAnalysis:
        """Análisis básico de fallback si Gemini falla. Usa QueryGenerator para queries inteligentes."""
        prompt_lower = prompt.lower()
        
        # Detectar tipo de negocio
        business_type = "web"
        product_category = None
        service_type = None
        niche = None
        
        # Detectar tipo de negocio
        if any(word in prompt_lower for word in ["ecommerce", "tienda", "shop", "store", "comprar", "venta"]):
            business_type = "ecommerce"
        elif any(word in prompt_lower for word in ["saas", "software", "app", "plataforma", "tool", "herramienta"]):
            business_type = "saas"
        elif any(word in prompt_lower for word in ["agencia", "agency", "servicios", "consultora", "consultoría"]):
            business_type = "agencia"
        elif any(word in prompt_lower for word in ["blog", "revista", "magazine", "noticias"]):
            business_type = "blog"
        
        # Extraer categoría/servicio del prompt
        # Buscar patrones como "ecommerce de X", "tienda de X", "agencia de X"
        patterns = [
            r"(?:ecommerce|tienda|shop|store|venta)\s+(?:de\s+)?(.+?)(?:\s+online|\s+en\s+|\s*$)",
            r"(?:agencia|agency|consultor[aí]a?)\s+(?:de\s+)?(.+?)(?:\s+en\s+|\s*$)",
            r"(?:saas|software|plataforma|app|herramienta)\s+(?:de|para)\s+(.+?)(?:\s+online|\s*$)",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, prompt_lower)
            if match:
                extracted = match.group(1).strip()
                if business_type == "ecommerce":
                    product_category = extracted
                else:
                    service_type = extracted
                break
        
        # Detectar nicho
        niche_keywords = {
            "luxury": ["lujo", "premium", "exclusivo", "luxury"],
            "eco": ["ecológico", "natural", "orgánico", "eco", "sostenible"],
            "vintage": ["vintage", "retro", "antiguo", "second hand"],
            "budget": ["barato", "económico", "low cost"],
            "old money": ["old money", "clásico", "elegante"],
        }
        
        for niche_name, keywords in niche_keywords.items():
            if any(kw in prompt_lower for kw in keywords):
                niche = niche_name
                break
        
        # Usar QueryGenerator para queries inteligentes
        query_gen = QueryGenerator()
        search_queries = query_gen.generate_queries(
            business_type=business_type,
            main_term=product_category or service_type or prompt,
            product_category=product_category,
            service_type=service_type,
            niche=niche,
            max_queries=15
        )
        
        # Indicadores de validación según tipo de negocio
        if business_type == "ecommerce":
            validation_indicators = [
                "añadir al carrito", "add to cart", "comprar", "buy now",
                "precio", "price", "€", "$", "envío", "shipping",
                "carrito", "cart", "checkout", "pagar"
            ]
            exclusion_indicators = [
                "qué es", "definición", "cómo crear", "tutorial",
                "wikipedia", "guía", "artículo", "blog post"
            ]
        elif business_type == "saas":
            validation_indicators = [
                "pricing", "precios", "planes", "free trial", "prueba gratis",
                "registrarse", "sign up", "login", "dashboard", "features"
            ]
            exclusion_indicators = [
                "qué es", "definición", "alternativas", "review",
                "comparativa", "wikipedia", "blog"
            ]
        elif business_type == "agencia":
            validation_indicators = [
                "nuestros servicios", "portfolio", "casos de éxito",
                "clientes", "equipo", "contacto", "presupuesto", "about us"
            ]
            exclusion_indicators = [
                "cómo montar", "qué es", "definición", "curso",
                "wikipedia", "guía para crear"
            ]
        else:
            validation_indicators = ["contacto", "servicios", "productos", "sobre nosotros"]
            exclusion_indicators = ["wikipedia", "qué es", "definición", "guía"]
        
        return PromptAnalysis(
            business_type=business_type,
            product_category=product_category,
            service_type=service_type,
            niche=niche,
            search_queries=search_queries,
            validation_indicators=validation_indicators,
            exclusion_indicators=exclusion_indicators,
            original_prompt=prompt
        )
    
    def generate_additional_queries(self, analysis: PromptAnalysis, count: int = 5) -> List[str]:
        """
        Genera queries adicionales basadas en el análisis inicial.
        Útil para ampliar la búsqueda si los primeros resultados no son suficientes.
        """
        prompt = f"""Basándote en esta búsqueda de webs:
- Tipo de negocio: {analysis.business_type}
- Categoría de producto: {analysis.product_category}
- Tipo de servicio: {analysis.service_type}
- Nicho: {analysis.niche}
- Queries ya usadas: {analysis.search_queries[:5]}

Genera {count} queries de búsqueda DIFERENTES y CREATIVAS para encontrar más webs de este tipo.
Las queries deben encontrar WEBS QUE SEAN esto, no que hablen de ello.

Responde SOLO con un JSON array de strings:
["query1", "query2", ...]"""
        
        try:
            response = self.model.generate_content(prompt)
            cleaned = response.text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r'^```(?:json)?\n?', '', cleaned)
                cleaned = re.sub(r'\n?```$', '', cleaned)
            return json.loads(cleaned)
        except:
            return []
