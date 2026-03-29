"""
Validador de dominios.
Verifica si un dominio cumple con los criterios especificados en el prompt.
Incluye análisis de Schema.org / JSON-LD para validación precisa.
Usa Wappalyzergo para detección de tecnologías.
"""
import requests
import re
import json
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# validator accepts any analysis object with business_type, required_tools,
# excluded_tools, validation_indicators attrs (PromptAnalysis or SearchIntent)
from typing import Any as PromptAnalysis  # type alias for backwards compat
from src.web_analyzer.wappalyzer_analyzer import WappalyzerAnalyzer, WappalyzerProfile
from src.web_analyzer.pagespeed_analyzer import PageSpeedAnalyzer, PerformanceMetrics
from src.web_search.serper_search import SearchResult


@dataclass
class SchemaData:
    """Datos estructurados Schema.org extraídos de la página."""
    
    # Tipos Schema.org detectados
    types: List[str] = field(default_factory=list)  # Product, Organization, LocalBusiness, etc.
    
    # Datos específicos extraídos
    organization_name: Optional[str] = None
    organization_type: Optional[str] = None
    
    # Datos de producto (si es ecommerce)
    has_products: bool = False
    product_count: int = 0
    product_names: List[str] = field(default_factory=list)
    price_range: Optional[str] = None
    currency: Optional[str] = None
    
    # Datos de negocio local
    is_local_business: bool = False
    business_type: Optional[str] = None
    address: Optional[str] = None
    
    # Datos de servicio
    has_services: bool = False
    service_types: List[str] = field(default_factory=list)
    
    # Otros datos
    has_offers: bool = False
    has_reviews: bool = False
    aggregate_rating: Optional[float] = None
    
    # Indicadores de tipo de web
    is_ecommerce: bool = False
    is_blog: bool = False
    is_service_business: bool = False
    is_software: bool = False
    
    # Raw data
    raw_schemas: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "types": self.types,
            "organization_name": self.organization_name,
            "organization_type": self.organization_type,
            "has_products": self.has_products,
            "product_count": self.product_count,
            "product_names": self.product_names[:5],  # Limitar a 5
            "price_range": self.price_range,
            "is_local_business": self.is_local_business,
            "business_type": self.business_type,
            "has_services": self.has_services,
            "service_types": self.service_types[:5],
            "has_offers": self.has_offers,
            "has_reviews": self.has_reviews,
            "aggregate_rating": self.aggregate_rating,
            "is_ecommerce": self.is_ecommerce,
            "is_blog": self.is_blog,
            "is_service_business": self.is_service_business,
            "is_software": self.is_software
        }


@dataclass
class ValidationResult:
    """Resultado de la validación de un dominio."""
    domain: str
    url: str
    
    # Resultado de validación
    is_valid: bool = False
    confidence_score: float = 0.0  # 0-100
    
    # Razones de validación/invalidación
    validation_reasons: List[str] = field(default_factory=list)
    rejection_reasons: List[str] = field(default_factory=list)
    
    # Datos del análisis
    search_result: Optional[Dict[str, Any]] = None
    tech_profile: Optional[Dict[str, Any]] = None
    performance_metrics: Optional[Dict[str, Any]] = None
    schema_data: Optional[Dict[str, Any]] = None  # NUEVO: Datos Schema.org
    
    # Contenido analizado
    page_title: str = ""
    page_description: str = ""
    detected_keywords: List[str] = field(default_factory=list)
    
    # Estado
    analysis_complete: bool = False
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "url": self.url,
            "is_valid": self.is_valid,
            "confidence_score": self.confidence_score,
            "validation_reasons": self.validation_reasons,
            "rejection_reasons": self.rejection_reasons,
            "page_title": self.page_title,
            "page_description": self.page_description,
            "detected_keywords": self.detected_keywords,
            "tech_profile": self.tech_profile,
            "schema_data": self.schema_data,
            "performance_metrics": self.performance_metrics,
            "analysis_complete": self.analysis_complete,
            "error_message": self.error_message
        }


class DomainValidator:
    """
    Valida si los dominios encontrados cumplen con los criterios del prompt.
    Usa múltiples señales para determinar si una web ES lo que se busca.
    Utiliza Wappalyzergo para detección de tecnologías.
    """
    
    def __init__(self, use_wappalyzer: bool = True, use_pagespeed: bool = False):
        """
        Args:
            use_wappalyzer: Si usar Wappalyzergo para análisis de tecnologías
            use_pagespeed: Si usar PageSpeed para métricas (solo si el prompt lo requiere)
        """
        self.use_wappalyzer = use_wappalyzer
        self.use_pagespeed = use_pagespeed
        self.wappalyzer = WappalyzerAnalyzer() if use_wappalyzer else None
        self.pagespeed = PageSpeedAnalyzer() if use_pagespeed else None
        
        # Headers para requests
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8"
        }
    
    def validate(self, search_result: SearchResult, analysis: PromptAnalysis) -> ValidationResult:
        """
        Valida un resultado de búsqueda contra los criterios del análisis.
        
        Args:
            search_result: Resultado de la búsqueda de Serper
            analysis: Análisis del prompt con criterios de validación
            
        Returns:
            ValidationResult con el resultado de la validación
        """
        result = ValidationResult(
            domain=search_result.domain,
            url=search_result.url,
            search_result=search_result.to_dict()
        )
        
        confidence = 0.0
        
        try:
            # 1. Análisis del snippet y título de la búsqueda (rápido, sin request adicional)
            snippet_score = self._analyze_search_snippet(
                search_result.title,
                search_result.snippet,
                analysis
            )
            confidence += snippet_score * 0.3  # 30% del peso
            
            if snippet_score > 50:
                result.validation_reasons.append(f"Snippet relevante (score: {snippet_score:.0f})")
            else:
                result.rejection_reasons.append(f"Snippet poco relevante (score: {snippet_score:.0f})")
            
            # 2. Análisis del contenido de la página (incluye Schema.org)
            content_score, page_data = self._analyze_page_content(search_result.url, analysis)
            confidence += content_score * 0.4  # 40% del peso
            
            result.page_title = page_data.get("title", "")
            result.page_description = page_data.get("description", "")
            result.detected_keywords = page_data.get("keywords", [])
            result.schema_data = page_data.get("schema_data")
            
            if content_score > 50:
                result.validation_reasons.append(f"Contenido relevante (score: {content_score:.0f})")
            else:
                result.rejection_reasons.append(f"Contenido poco relevante (score: {content_score:.0f})")
            
            # Añadir razón si Schema.org confirma el tipo
            if result.schema_data:
                if result.schema_data.get("is_ecommerce") and analysis.business_type == "ecommerce":
                    result.validation_reasons.append("Schema.org confirma ecommerce")
                elif result.schema_data.get("is_software") and analysis.business_type in ["saas", "software"]:
                    result.validation_reasons.append("Schema.org confirma software")
                elif result.schema_data.get("is_service_business") and analysis.business_type in ["agencia", "agency"]:
                    result.validation_reasons.append("Schema.org confirma servicios")
            
            # 3. Análisis de tecnologías con Wappalyzer (si está habilitado)
            if self.use_wappalyzer:
                tech_score, wappalyzer_profile = self._analyze_technologies(search_result.url, analysis)
                confidence += tech_score * 0.2  # 20% del peso
                result.tech_profile = wappalyzer_profile.to_dict() if wappalyzer_profile else None
                
                if tech_score > 50:
                    result.validation_reasons.append(f"Tecnologías compatibles (score: {tech_score:.0f})")
                
                # Verificar filtros de herramientas si existen
                if wappalyzer_profile:
                    tools_ok, tools_reason = self._check_tool_filters(wappalyzer_profile, analysis)
                    if not tools_ok:
                        # Rechazar si no cumple con los filtros de herramientas
                        result.rejection_reasons.append(tools_reason)
                        confidence -= 30
                    elif tools_reason:
                        result.validation_reasons.append(tools_reason)
            else:
                confidence += 50 * 0.2  # Neutral si no se usa
            
            # 4. Análisis de rendimiento (solo si el prompt lo requiere)
            if self.use_pagespeed and (analysis.check_performance or analysis.check_seo or analysis.check_mobile):
                perf_score = self._analyze_performance(search_result.url, analysis)
                confidence += perf_score * 0.1  # 10% del peso
                
                if perf_score > 50:
                    result.validation_reasons.append(f"Métricas de rendimiento OK (score: {perf_score:.0f})")
            else:
                confidence += 50 * 0.1  # Neutral si no se usa
            
            # Determinar si es válido
            result.confidence_score = min(confidence, 100)
            result.is_valid = confidence >= 50  # Umbral de 50%
            result.analysis_complete = True
            
        except Exception as e:
            result.error_message = str(e)
            result.analysis_complete = False
        
        return result
    
    def _analyze_search_snippet(self, title: str, snippet: str, analysis: PromptAnalysis) -> float:
        """
        Analiza el título y snippet de los resultados de búsqueda.
        Retorna un score de 0-100.
        """
        score = 50.0  # Score base neutral
        text = f"{title} {snippet}".lower()
        
        # Verificar indicadores de validación
        for indicator in analysis.validation_indicators:
            if indicator.lower() in text:
                score += 10
        
        # Verificar indicadores de exclusión
        for indicator in analysis.exclusion_indicators:
            if indicator.lower() in text:
                score -= 15
        
        # Penalizar resultados informativos
        informative_patterns = [
            r'\bqu[eé] es\b', r'\bdefinici[oó]n\b', r'\bgu[ií]a\b',
            r'\bc[oó]mo crear\b', r'\btutorial\b', r'\bart[ií]culo\b',
            r'\bwikipedia\b', r'\bblog\b.*\bpost\b', r'\bnoticias\b'
        ]
        
        for pattern in informative_patterns:
            if re.search(pattern, text):
                score -= 20
        
        # Bonus por indicadores de negocio real
        business_indicators = [
            r'\bcontact[oa]?\b', r'\btel[eé]fono\b', r'\bprecio\b',
            r'\bcomprar\b', r'\bservicios\b', r'\bportfolio\b',
            r'\bnuestr[oa]s?\b', r'\bempresa\b', r'\bsobre nosotros\b'
        ]
        
        for pattern in business_indicators:
            if re.search(pattern, text):
                score += 5
        
        return max(0, min(100, score))
    
    def _analyze_page_content(self, url: str, analysis: PromptAnalysis) -> tuple:
        """
        Analiza el contenido real de la página incluyendo Schema.org/JSON-LD.
        Retorna (score, page_data).
        """
        page_data = {
            "title": "",
            "description": "",
            "keywords": [],
            "schema_data": None
        }
        
        try:
            response = requests.get(
                url,
                headers=self.headers,
                timeout=10,
                allow_redirects=True
            )
            
            if response.status_code != 200:
                return 30, page_data
            
            html = response.text
            html_lower = html.lower()
            
            # Extraer título
            title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
            if title_match:
                page_data["title"] = title_match.group(1).strip()
            
            # Extraer meta description
            desc_match = re.search(
                r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']+)["\']',
                html, re.IGNORECASE
            )
            if not desc_match:
                # Intentar formato alternativo
                desc_match = re.search(
                    r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']description["\']',
                    html, re.IGNORECASE
                )
            if desc_match:
                page_data["description"] = desc_match.group(1).strip()
            
            # Extraer meta keywords
            keywords_match = re.search(
                r'<meta[^>]*name=["\']keywords["\'][^>]*content=["\']([^"\']+)["\']',
                html, re.IGNORECASE
            )
            if keywords_match:
                meta_keywords = [k.strip() for k in keywords_match.group(1).split(',')]
                page_data["keywords"].extend(meta_keywords[:5])
            
            # Extraer Open Graph type
            og_type_match = re.search(
                r'<meta[^>]*property=["\']og:type["\'][^>]*content=["\']([^"\']+)["\']',
                html, re.IGNORECASE
            )
            if og_type_match:
                og_type = og_type_match.group(1)
                page_data["keywords"].append(f"og:{og_type}")
            
            # === NUEVO: Extraer y analizar Schema.org / JSON-LD ===
            schema_data = self._extract_schema_data(html)
            page_data["schema_data"] = schema_data.to_dict() if schema_data else None
            
            score = 50.0
            
            # === Scoring basado en Schema.org ===
            if schema_data:
                schema_score = self._score_from_schema(schema_data, analysis)
                score += schema_score
                
                # Añadir tipos de schema a keywords
                for schema_type in schema_data.types[:3]:
                    page_data["keywords"].append(f"schema:{schema_type}")
            
            # Verificar tipo de negocio según el análisis
            if analysis.business_type == "ecommerce":
                score = self._score_ecommerce(html_lower, score)
                # Bonus si Schema confirma ecommerce
                if schema_data and schema_data.is_ecommerce:
                    score += 15
            elif analysis.business_type == "saas":
                score = self._score_saas(html_lower, score)
                if schema_data and schema_data.is_software:
                    score += 15
            elif analysis.business_type == "agencia":
                score = self._score_agency(html_lower, score)
                if schema_data and schema_data.is_service_business:
                    score += 15
            else:
                # Scoring genérico
                score = self._score_generic_business(html_lower, analysis, score)
            
            # Verificar categoría de producto/servicio si se especifica
            if analysis.product_category:
                if analysis.product_category.lower() in html_lower:
                    score += 15
                    page_data["keywords"].append(analysis.product_category)
                # Verificar si el producto está en Schema
                if schema_data and schema_data.product_names:
                    for product in schema_data.product_names:
                        if analysis.product_category.lower() in product.lower():
                            score += 10
                            break
            
            if analysis.service_type:
                if analysis.service_type.lower() in html_lower:
                    score += 15
                    page_data["keywords"].append(analysis.service_type)
                # Verificar si el servicio está en Schema
                if schema_data and schema_data.service_types:
                    for service in schema_data.service_types:
                        if analysis.service_type.lower() in service.lower():
                            score += 10
                            break
            
            if analysis.niche:
                if analysis.niche.lower() in html_lower:
                    score += 10
                    page_data["keywords"].append(analysis.niche)
            
            # Detectar keywords relevantes encontradas
            for indicator in analysis.validation_indicators[:10]:
                if indicator.lower() in html_lower:
                    page_data["keywords"].append(indicator)
            
            # Penalizar contenido informativo
            informative_score = self._check_informative_content(html_lower)
            score -= informative_score
            
            # Penalizar si Schema indica que es blog/artículo
            if schema_data and schema_data.is_blog and analysis.business_type != "blog":
                score -= 20
            
            return max(0, min(100, score)), page_data
            
        except Exception as e:
            return 30, page_data
    
    def _extract_schema_data(self, html: str) -> Optional[SchemaData]:
        """
        Extrae y parsea datos Schema.org / JSON-LD del HTML.
        
        Busca:
        - <script type="application/ld+json">
        - Analiza @type para determinar tipo de negocio
        - Extrae información relevante de productos, servicios, organización
        """
        schema = SchemaData()
        
        try:
            # Buscar todos los bloques JSON-LD
            jsonld_pattern = r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
            matches = re.findall(jsonld_pattern, html, re.DOTALL | re.IGNORECASE)
            
            if not matches:
                return None
            
            for match in matches:
                try:
                    # Limpiar el JSON
                    json_str = match.strip()
                    # Remover comentarios HTML si existen
                    json_str = re.sub(r'<!--.*?-->', '', json_str, flags=re.DOTALL)
                    
                    data = json.loads(json_str)
                    schema.raw_schemas.append(data)
                    
                    # Procesar el schema (puede ser objeto único o array)
                    if isinstance(data, list):
                        for item in data:
                            self._process_schema_item(item, schema)
                    else:
                        self._process_schema_item(data, schema)
                        
                except json.JSONDecodeError:
                    continue
            
            # Determinar tipo de web basado en los schemas encontrados
            self._determine_web_type(schema)
            
            return schema if schema.types else None
            
        except Exception:
            return None
    
    def _process_schema_item(self, item: Dict, schema: SchemaData):
        """Procesa un item de Schema.org y extrae información relevante."""
        if not isinstance(item, dict):
            return
        
        # Obtener el tipo (@type)
        schema_type = item.get("@type", "")
        if isinstance(schema_type, list):
            schema_types = schema_type
        else:
            schema_types = [schema_type] if schema_type else []
        
        for st in schema_types:
            if st and st not in schema.types:
                schema.types.append(st)
        
        # Procesar según el tipo
        for schema_type in schema_types:
            schema_type_lower = schema_type.lower() if schema_type else ""
            
            # === PRODUCTOS ===
            if schema_type_lower in ["product", "productgroup", "indivisualproduct"]:
                schema.has_products = True
                schema.product_count += 1
                
                name = item.get("name", "")
                if name and name not in schema.product_names:
                    schema.product_names.append(name)
                
                # Extraer precio
                offers = item.get("offers", {})
                if isinstance(offers, dict):
                    price = offers.get("price") or offers.get("lowPrice")
                    currency = offers.get("priceCurrency", "")
                    if price:
                        schema.price_range = f"{price} {currency}".strip()
                        schema.currency = currency
                    schema.has_offers = True
                elif isinstance(offers, list) and offers:
                    schema.has_offers = True
            
            # === ORGANIZACIÓN / EMPRESA ===
            elif schema_type_lower in ["organization", "corporation", "localbusiness", 
                                        "store", "onlinestore", "shoppingcenter"]:
                schema.organization_name = item.get("name", "")
                schema.organization_type = schema_type
                
                if schema_type_lower in ["localbusiness", "store"]:
                    schema.is_local_business = True
                    schema.business_type = schema_type
                    
                    address = item.get("address", {})
                    if isinstance(address, dict):
                        schema.address = address.get("streetAddress", "")
            
            # === NEGOCIO LOCAL ESPECÍFICO ===
            elif schema_type_lower in ["restaurant", "hotel", "medicalclinic", "dentist",
                                        "beautysalon", "hairsalon", "spa", "gym",
                                        "autodealer", "realestateagent"]:
                schema.is_local_business = True
                schema.business_type = schema_type
                schema.is_service_business = True
                schema.organization_name = item.get("name", "")
            
            # === SERVICIOS ===
            elif schema_type_lower in ["service", "professionalservice", "financialservice",
                                        "legalservice", "medicalservice"]:
                schema.has_services = True
                schema.is_service_business = True
                
                name = item.get("name", "")
                if name and name not in schema.service_types:
                    schema.service_types.append(name)
            
            # === SOFTWARE / SAAS ===
            elif schema_type_lower in ["softwareapplication", "webapplication", 
                                        "mobileapplication", "saasapplication"]:
                schema.is_software = True
                schema.organization_name = item.get("name", "")
            
            # === BLOG / ARTÍCULO ===
            elif schema_type_lower in ["article", "newsarticle", "blogposting", 
                                        "blog", "webpage"]:
                if schema_type_lower in ["article", "newsarticle", "blogposting", "blog"]:
                    schema.is_blog = True
            
            # === OFERTAS ===
            elif schema_type_lower == "offer":
                schema.has_offers = True
                price = item.get("price")
                if price:
                    schema.price_range = str(price)
            
            # === REVIEWS ===
            elif schema_type_lower in ["review", "aggregaterating"]:
                schema.has_reviews = True
                if schema_type_lower == "aggregaterating":
                    rating = item.get("ratingValue")
                    if rating:
                        try:
                            schema.aggregate_rating = float(rating)
                        except:
                            pass
        
        # Procesar agregado de rating si existe dentro del item
        if "aggregateRating" in item:
            schema.has_reviews = True
            rating = item["aggregateRating"].get("ratingValue")
            if rating:
                try:
                    schema.aggregate_rating = float(rating)
                except:
                    pass
        
        # Procesar items anidados (ej: @graph)
        if "@graph" in item:
            for sub_item in item["@graph"]:
                self._process_schema_item(sub_item, schema)
        
        # Procesar mainEntity si existe
        if "mainEntity" in item:
            main_entity = item["mainEntity"]
            if isinstance(main_entity, dict):
                self._process_schema_item(main_entity, schema)
            elif isinstance(main_entity, list):
                for entity in main_entity:
                    self._process_schema_item(entity, schema)
    
    def _determine_web_type(self, schema: SchemaData):
        """Determina el tipo de web basado en los schemas encontrados."""
        types_lower = [t.lower() for t in schema.types]
        
        # Es ecommerce si tiene productos o es una tienda
        if schema.has_products or schema.has_offers:
            schema.is_ecommerce = True
        
        if any(t in types_lower for t in ["store", "onlinestore", "shoppingcenter"]):
            schema.is_ecommerce = True
        
        # Es servicio si tiene servicios o es negocio local de servicios
        if schema.has_services:
            schema.is_service_business = True
        
        # Es blog si tiene artículos
        if any(t in types_lower for t in ["article", "newsarticle", "blogposting", "blog"]):
            schema.is_blog = True
    
    def _score_from_schema(self, schema: SchemaData, analysis: PromptAnalysis) -> float:
        """
        Calcula score adicional basado en datos de Schema.org.
        Retorna puntos a añadir/restar del score.
        """
        score = 0.0
        bt = analysis.business_type.lower()
        
        # === ECOMMERCE ===
        if bt in ["ecommerce", "tienda", "shop", "marketplace"]:
            if schema.is_ecommerce:
                score += 20
            if schema.has_products:
                score += 15
                if schema.product_count >= 3:
                    score += 5  # Tiene varios productos
            if schema.has_offers:
                score += 10
            if schema.price_range:
                score += 5  # Tiene precios
            if schema.is_blog and not schema.has_products:
                score -= 15  # Es más blog que tienda
        
        # === SAAS / SOFTWARE ===
        elif bt in ["saas", "software", "plataforma", "app"]:
            if schema.is_software:
                score += 25
            if "softwareapplication" in [t.lower() for t in schema.types]:
                score += 15
            if schema.has_reviews:
                score += 5
        
        # === AGENCIA / SERVICIOS ===
        elif bt in ["agencia", "agency", "consultora", "servicios"]:
            if schema.is_service_business:
                score += 20
            if schema.has_services:
                score += 15
            if schema.is_local_business:
                score += 10
            if "organization" in [t.lower() for t in schema.types]:
                score += 5
        
        # === NEGOCIO LOCAL ===
        elif bt in ["local", "negocio local"]:
            if schema.is_local_business:
                score += 25
            if schema.address:
                score += 10
        
        # === BLOG ===
        elif bt == "blog":
            if schema.is_blog:
                score += 25
        
        # Bonus por tener reviews (indica negocio real)
        if schema.has_reviews and schema.aggregate_rating:
            score += 5
        
        # Bonus por nombre de organización (indica negocio real)
        if schema.organization_name:
            score += 5
        
        return score
    
    def _score_ecommerce(self, html: str, base_score: float) -> float:
        """Scoring específico para ecommerce."""
        score = base_score
        
        # Indicadores fuertes de ecommerce
        strong_indicators = [
            "add to cart", "añadir al carrito", "agregar al carrito",
            "buy now", "comprar ahora", "checkout", "shopping cart",
            "carrito de compra", "precio", "price", "€", "$",
            "envío", "shipping", "delivery", "entrega"
        ]
        
        for indicator in strong_indicators:
            if indicator in html:
                score += 8
        
        # Estructuras de ecommerce
        if re.search(r'class=["\'][^"\']*product[^"\']*["\']', html):
            score += 10
        if re.search(r'class=["\'][^"\']*cart[^"\']*["\']', html):
            score += 10
        if re.search(r'data-price|data-product|data-sku', html):
            score += 10
        
        # Indicadores de plataformas ecommerce
        if "shopify" in html or "woocommerce" in html or "prestashop" in html:
            score += 15
        
        return score
    
    def _score_saas(self, html: str, base_score: float) -> float:
        """Scoring específico para SaaS."""
        score = base_score
        
        # Indicadores de SaaS
        saas_indicators = [
            "pricing", "precios", "free trial", "prueba gratis",
            "sign up", "registrarse", "start free", "get started",
            "features", "características", "integrations", "integraciones",
            "api", "dashboard", "login", "iniciar sesión"
        ]
        
        for indicator in saas_indicators:
            if indicator in html:
                score += 6
        
        # Estructuras comunes en SaaS
        if re.search(r'class=["\'][^"\']*pricing[^"\']*["\']', html):
            score += 10
        if re.search(r'class=["\'][^"\']*feature[^"\']*["\']', html):
            score += 8
        
        return score
    
    def _score_agency(self, html: str, base_score: float) -> float:
        """Scoring específico para agencias."""
        score = base_score
        
        # Indicadores de agencia
        agency_indicators = [
            "nuestros servicios", "our services", "portfolio",
            "casos de éxito", "case studies", "clientes", "clients",
            "equipo", "team", "about us", "sobre nosotros",
            "contactar", "contact", "presupuesto", "quote"
        ]
        
        for indicator in agency_indicators:
            if indicator in html:
                score += 7
        
        # Estructuras comunes en agencias
        if re.search(r'class=["\'][^"\']*portfolio[^"\']*["\']', html):
            score += 10
        if re.search(r'class=["\'][^"\']*service[^"\']*["\']', html):
            score += 8
        
        return score
    
    def _score_generic_business(self, html: str, analysis: PromptAnalysis, base_score: float) -> float:
        """Scoring genérico para otros tipos de negocio."""
        score = base_score
        
        # Indicadores generales de negocio real
        business_indicators = [
            "contacto", "contact", "teléfono", "phone",
            "email", "dirección", "address", "horario",
            "sobre nosotros", "about us", "empresa", "company"
        ]
        
        for indicator in business_indicators:
            if indicator in html:
                score += 5
        
        return score
    
    def _check_informative_content(self, html: str) -> float:
        """
        Verifica si el contenido es informativo (artículo, definición, etc.)
        Retorna penalización a aplicar.
        """
        penalty = 0
        
        # Patrones de contenido informativo
        informative_patterns = [
            (r'<article[^>]*>', 10),  # Es un artículo
            (r'class=["\'][^"\']*blog[^"\']*["\']', 8),
            (r'class=["\'][^"\']*article[^"\']*["\']', 8),
            (r'class=["\'][^"\']*post[^"\']*["\']', 5),
            (r'\bqu[eé] es\b', 15),  # "Qué es X"
            (r'\bdefinici[oó]n\b', 15),
            (r'\bgu[ií]a (completa|definitiva)\b', 10),
            (r'\bc[oó]mo (crear|hacer|empezar)\b', 8),
        ]
        
        for pattern, pen in informative_patterns:
            if re.search(pattern, html):
                penalty += pen
        
        return min(penalty, 40)  # Máximo 40 de penalización
    
    def _check_tool_filters(self, wappalyzer_profile: WappalyzerProfile, analysis: PromptAnalysis) -> tuple:
        """
        Verifica si el perfil tecnológico de Wappalyzer cumple con los filtros de herramientas.
        
        Args:
            wappalyzer_profile: Perfil tecnológico de Wappalyzer
            analysis: Análisis del prompt con filtros
            
        Returns:
            (cumple: bool, razón: str)
        """
        # Obtener filtros del análisis (si existen)
        required_tools = getattr(analysis, 'required_tools', []) or []
        excluded_tools = getattr(analysis, 'excluded_tools', []) or []
        
        if not required_tools and not excluded_tools:
            return True, ""
        
        # Usar el método de WappalyzerProfile para verificar requisitos
        meets_requirements, reason = wappalyzer_profile.check_technology_requirements(
            wappalyzer_profile,
            must_have=required_tools,
            must_not=excluded_tools
        ) if hasattr(self.wappalyzer, 'check_technology_requirements') else (True, "")
        
        # Usar WappalyzerAnalyzer para verificar
        if self.wappalyzer:
            meets_requirements, reason = self.wappalyzer.check_technology_requirements(
                wappalyzer_profile,
                must_have=required_tools,
                must_not=excluded_tools
            )
            
            if not meets_requirements:
                return False, reason
        else:
            # Fallback: verificar manualmente
            all_detected_tools = [t.lower() for t in wappalyzer_profile.all_technologies_names]
            
            # Verificar herramientas requeridas
            for required in required_tools:
                required_lower = required.lower()
                
                has_tool = False
                
                # Verificar por nombre
                if any(required_lower in tool for tool in all_detected_tools):
                    has_tool = True
                
                # Verificar por categoría
                if not has_tool:
                    if required_lower == "crm" and wappalyzer_profile.has_crm:
                        has_tool = True
                    elif required_lower in ["chat", "livechat", "live_chat"] and wappalyzer_profile.has_live_chat:
                        has_tool = True
                    elif required_lower in ["email", "email_marketing", "email marketing"] and wappalyzer_profile.has_email_marketing:
                        has_tool = True
                    elif required_lower in ["analytics", "analíticas"] and wappalyzer_profile.has_analytics:
                        has_tool = True
                    elif required_lower in ["ecommerce", "e-commerce"] and wappalyzer_profile.has_ecommerce:
                        has_tool = True
                    elif required_lower in ["payment", "pago"] and wappalyzer_profile.has_payment:
                        has_tool = True
                
                if not has_tool:
                    return False, f"No tiene {required}"
            
            # Verificar herramientas excluidas
            for excluded in excluded_tools:
                excluded_lower = excluded.lower()
                
                # Verificar por nombre
                if any(excluded_lower in tool for tool in all_detected_tools):
                    return False, f"Tiene {excluded} (excluido)"
                
                # Verificar por categoría
                if excluded_lower == "crm" and wappalyzer_profile.has_crm:
                    return False, f"Tiene CRM: {', '.join(wappalyzer_profile.crm[:2])}"
                elif excluded_lower in ["chat", "livechat", "live_chat"] and wappalyzer_profile.has_live_chat:
                    return False, f"Tiene chat: {', '.join(wappalyzer_profile.live_chat[:2])}"
                elif excluded_lower in ["email", "email_marketing", "email marketing"] and wappalyzer_profile.has_email_marketing:
                    return False, f"Tiene email marketing: {', '.join(wappalyzer_profile.email_marketing[:2])}"
                elif excluded_lower in ["analytics", "analíticas"] and wappalyzer_profile.has_analytics:
                    return False, f"Tiene analytics: {', '.join(wappalyzer_profile.analytics[:2])}"
        
        # Todo OK
        if required_tools:
            return True, f"Tiene: {', '.join(required_tools)}"
        if excluded_tools:
            return True, f"No tiene: {', '.join(excluded_tools)}"
        
        return True, ""
    
    def _analyze_technologies(self, url: str, analysis: PromptAnalysis) -> tuple:
        """
        Analiza las tecnologías de la web usando Wappalyzergo.
        Retorna (score, wappalyzer_profile).
        """
        if not self.wappalyzer:
            return 50, None
        
        try:
            profile = self.wappalyzer.analyze(url)
            score = 50.0
            
            if not profile.analysis_success:
                return 50, profile
            
            # Verificar si las tecnologías coinciden con el tipo de negocio
            if analysis.business_type == "ecommerce":
                if profile.has_ecommerce:
                    score += 30
                if profile.has_payment:
                    score += 10
                # Bonus por plataformas ecommerce conocidas
                if any(ec in [t.lower() for t in profile.all_technologies_names] 
                       for ec in ["shopify", "woocommerce", "magento", "prestashop", "bigcommerce"]):
                    score += 15
            elif analysis.business_type == "saas":
                # Indicadores de SaaS
                if profile.has_analytics:
                    score += 10
                if any(fw in [t.lower() for t in profile.all_technologies_names]
                       for fw in ["react", "vue", "angular", "next.js", "nuxt"]):
                    score += 15
            
            # Verificar tecnologías requeridas
            required_techs = getattr(analysis, 'required_technologies', []) or []
            if required_techs:
                for tech in required_techs:
                    if profile.has_technology(tech):
                        score += 10
            
            # Verificar tecnologías excluidas
            excluded_techs = getattr(analysis, 'excluded_technologies', []) or []
            if excluded_techs:
                for tech in excluded_techs:
                    if profile.has_technology(tech):
                        score -= 20
            
            # Bonus por tener CRM (indica negocio activo)
            if profile.has_crm:
                score += 5
            
            # Bonus por tener email marketing (indica negocio activo)
            if profile.has_email_marketing:
                score += 5
            
            # Bonus por tener analytics (indica negocio que rastrea métricas)
            if profile.has_analytics:
                score += 3
            
            return max(0, min(100, score)), profile
            
        except Exception as e:
            return 50, None
    
    def _analyze_performance(self, url: str, analysis: PromptAnalysis) -> float:
        """
        Analiza las métricas de rendimiento si el prompt lo requiere.
        """
        if not self.pagespeed:
            return 50
        
        try:
            metrics = self.pagespeed.analyze(url)
            
            if not metrics.analysis_success:
                return 50
            
            score = 50.0
            
            # Verificar criterios de rendimiento
            if analysis.performance_criteria:
                criteria = analysis.performance_criteria.lower()
                
                if "lenta" in criteria or "slow" in criteria:
                    # Busca webs lentas
                    if metrics.performance_category == "slow":
                        score += 40
                    elif metrics.performance_category == "average":
                        score += 20
                elif "rápida" in criteria or "fast" in criteria:
                    # Busca webs rápidas
                    if metrics.performance_category == "fast":
                        score += 40
                    elif metrics.performance_category == "average":
                        score += 20
            
            # Verificar mobile friendly si se requiere
            if analysis.check_mobile:
                if metrics.is_mobile_friendly:
                    score += 20
                else:
                    score -= 10
            
            return max(0, min(100, score))
            
        except Exception:
            return 50
    
    def validate_batch(self, search_results: List[SearchResult], 
                      analysis: PromptAnalysis,
                      max_workers: int = 5) -> List[ValidationResult]:
        """
        Valida múltiples resultados en paralelo.
        
        Args:
            search_results: Lista de resultados a validar
            analysis: Análisis del prompt
            max_workers: Número de threads paralelos
            
        Returns:
            Lista de ValidationResult ordenada por confidence_score
        """
        results = []
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_result = {
                executor.submit(self.validate, sr, analysis): sr
                for sr in search_results
            }
            
            for future in as_completed(future_to_result):
                try:
                    validation_result = future.result()
                    results.append(validation_result)
                except Exception as e:
                    sr = future_to_result[future]
                    results.append(ValidationResult(
                        domain=sr.domain,
                        url=sr.url,
                        error_message=str(e)
                    ))
        
        # Ordenar por confidence score descendente
        results.sort(key=lambda x: x.confidence_score, reverse=True)
        return results
    
    def filter_valid(self, validation_results: List[ValidationResult], 
                    min_confidence: float = 50) -> List[ValidationResult]:
        """
        Filtra solo los resultados válidos con confianza mínima.
        """
        return [r for r in validation_results 
                if r.is_valid and r.confidence_score >= min_confidence]
