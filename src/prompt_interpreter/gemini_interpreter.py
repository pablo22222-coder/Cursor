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
from src.prompt_interpreter.intent_detector import IntentDetector, UserIntent


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
    
    # Filtros de herramientas externas
    required_tools: List[str] = field(default_factory=list)  # Herramientas que DEBE tener
    excluded_tools: List[str] = field(default_factory=list)  # Herramientas que NO debe tener
    
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
            "required_tools": self.required_tools,
            "excluded_tools": self.excluded_tools,
            "search_queries": self.search_queries,
            "validation_indicators": self.validation_indicators,
            "exclusion_indicators": self.exclusion_indicators,
            "original_prompt": self.original_prompt
        }


class GeminiInterpreter:
    """Usa Gemini para interpretar y analizar prompts de búsqueda de webs."""
    
    def __init__(self):
        self.settings = get_settings()
        self.gemini_available = True   # siempre True: AIManager tiene múltiples fallbacks
        self.model = None

        # Mantener compatibilidad: inicializar SDK de Gemini si hay key
        if self.settings.is_gemini_configured():
            try:
                genai.configure(api_key=self.settings.gemini_api_key)
                self.model = genai.GenerativeModel(self.settings.gemini_model)
            except Exception as e:
                print(f"⚠️ No se pudo inicializar Gemini SDK: {e}")

        from src.services.ai_manager import get_ai_manager
        self._ai_manager = get_ai_manager()

    def analyze_prompt(self, prompt: str) -> PromptAnalysis:
        """
        Analiza el prompt del usuario y extrae información estructurada.
        Usa AIManager para fallback automático entre 5 proveedores.

        Orden: Groq → Cerebras → SambaNova → Gemini → WebLLM → basic_analysis
        """
        system_prompt_text = self._build_analysis_prompt(prompt)

        ai_response = self._ai_manager.complete(
            prompt=prompt,
            system_prompt=system_prompt_text,
        )

        if not ai_response.success or not ai_response.text.strip():
            print(
                f"[GeminiInterpreter] ⚠️ Todos los providers fallaron. "
                f"Usando análisis local. ({ai_response.error})"
            )
            return self._basic_analysis(prompt)

        try:
            analysis_data = self._parse_response(ai_response.text)
            analysis_data["original_prompt"] = prompt
            return PromptAnalysis(**analysis_data)
        except Exception as e:
            print(f"[GeminiInterpreter] Error parseando respuesta: {e}. Usando análisis local.")
            return self._basic_analysis(prompt)
    
    def _handle_gemini_error(self, error_msg: str):
        """Muestra mensaje de error apropiado según el tipo de error."""
        if "403" in error_msg or "leaked" in error_msg.lower():
            print("⚠️ API Key de Gemini bloqueada. Usando análisis local.")
        elif "429" in error_msg or "quota" in error_msg.lower():
            print("⚠️ Límite de Gemini excedido. Usando análisis local.")
        elif "401" in error_msg:
            print("⚠️ API Key de Gemini inválida. Usando análisis local.")
        else:
            print(f"⚠️ Error con Gemini: {error_msg[:80]}. Usando análisis local.")
    
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
        """
        Análisis avanzado usando IntentDetector.
        Extrae TODA la información del prompt sin inventar nada.
        """
        # Usar IntentDetector para análisis profundo
        intent_detector = IntentDetector()
        intent = intent_detector.detect(prompt)
        
        # Usar QueryGenerator con la intención detectada
        query_gen = QueryGenerator()
        search_queries = query_gen.generate_from_intent(intent, max_queries=20)
        
        # Generar indicadores de validación según tipo de negocio e intención
        validation_indicators, exclusion_indicators = self._get_indicators_from_intent(intent)
        
        return PromptAnalysis(
            business_type=intent.business_type,
            product_category=intent.product_category,
            service_type=intent.service_type,
            niche=intent.niche,
            target_audience=intent.target_audience,
            check_performance=intent.check_speed,
            check_seo=intent.check_seo,
            performance_criteria=intent.performance_requirement,
            required_technologies=[intent.platform_preference] if intent.platform_preference else [],
            required_tools=intent.required_tools,
            excluded_tools=intent.excluded_tools,
            search_queries=search_queries,
            validation_indicators=validation_indicators,
            exclusion_indicators=exclusion_indicators,
            original_prompt=prompt
        )
    
    def _get_indicators_from_intent(self, intent: UserIntent) -> tuple:
        """Genera indicadores de validación basados en la intención detectada."""
        validation_indicators = []
        exclusion_indicators = [
            "qué es", "definición", "cómo crear", "tutorial",
            "wikipedia", "guía completa", "artículo", "blog post",
            "curso de", "aprende a"
        ]
        
        bt = intent.business_type.lower()
        
        if bt in ["ecommerce", "tienda", "shop", "marketplace"]:
            validation_indicators = [
                "añadir al carrito", "add to cart", "comprar", "buy now",
                "precio", "price", "€", "$", "envío", "shipping",
                "carrito", "cart", "checkout", "pagar", "stock",
                "talla", "color", "cantidad", "productos"
            ]
            # Si tiene nicho específico, añadir indicadores
            if intent.niche == "eco":
                validation_indicators.extend(["ecológico", "natural", "orgánico", "sostenible"])
            elif intent.niche == "luxury":
                validation_indicators.extend(["premium", "exclusivo", "lujo"])
                
        elif bt in ["saas", "software", "plataforma", "app"]:
            validation_indicators = [
                "pricing", "precios", "planes", "free trial", "prueba gratis",
                "registrarse", "sign up", "login", "dashboard", "features",
                "características", "integraciones", "api", "demo"
            ]
            
        elif bt in ["agencia", "agency", "consultora"]:
            validation_indicators = [
                "nuestros servicios", "portfolio", "casos de éxito",
                "clientes", "equipo", "contacto", "presupuesto", "about us",
                "sobre nosotros", "trabajos", "proyectos"
            ]
            # Si tiene ubicación, añadir indicadores locales
            if intent.location:
                validation_indicators.extend([intent.location, "dirección", "oficina"])
                
        elif bt == "blog":
            validation_indicators = [
                "artículos", "posts", "categorías", "autor", "publicado",
                "suscríbete", "newsletter"
            ]
            # Los blogs SÍ son informativos, ajustar exclusiones
            exclusion_indicators = ["wikipedia", "definición de diccionario"]
            
        else:
            validation_indicators = [
                "contacto", "servicios", "productos", "sobre nosotros",
                "empresa", "equipo"
            ]
        
        # Añadir keywords principales como indicadores
        if intent.main_keywords:
            validation_indicators.extend(intent.main_keywords)
        
        # Añadir industria como indicador si existe
        if intent.industry:
            validation_indicators.append(intent.industry)
        
        return validation_indicators, exclusion_indicators
    
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
