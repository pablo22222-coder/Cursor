"""
Validador de dominios.
Verifica si un dominio cumple con los criterios especificados en el prompt.
"""
import requests
import re
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

from src.prompt_interpreter.gemini_interpreter import PromptAnalysis
from src.web_analyzer.webtech_analyzer import WebTechAnalyzer, TechnologyProfile
from src.web_analyzer.pagespeed_analyzer import PageSpeedAnalyzer, PerformanceMetrics
from src.web_search.serper_search import SearchResult


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
            "performance_metrics": self.performance_metrics,
            "analysis_complete": self.analysis_complete,
            "error_message": self.error_message
        }


class DomainValidator:
    """
    Valida si los dominios encontrados cumplen con los criterios del prompt.
    Usa múltiples señales para determinar si una web ES lo que se busca.
    """
    
    def __init__(self, use_webtech: bool = True, use_pagespeed: bool = False):
        """
        Args:
            use_webtech: Si usar WebTech para análisis de tecnologías
            use_pagespeed: Si usar PageSpeed para métricas (solo si el prompt lo requiere)
        """
        self.use_webtech = use_webtech
        self.use_pagespeed = use_pagespeed
        self.webtech = WebTechAnalyzer() if use_webtech else None
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
            
            # 2. Análisis del contenido de la página
            content_score, page_data = self._analyze_page_content(search_result.url, analysis)
            confidence += content_score * 0.4  # 40% del peso
            
            result.page_title = page_data.get("title", "")
            result.page_description = page_data.get("description", "")
            result.detected_keywords = page_data.get("keywords", [])
            
            if content_score > 50:
                result.validation_reasons.append(f"Contenido relevante (score: {content_score:.0f})")
            else:
                result.rejection_reasons.append(f"Contenido poco relevante (score: {content_score:.0f})")
            
            # 3. Análisis de tecnologías (si está habilitado)
            if self.use_webtech:
                tech_score, tech_profile = self._analyze_technologies(search_result.url, analysis)
                confidence += tech_score * 0.2  # 20% del peso
                result.tech_profile = tech_profile.to_dict() if tech_profile else None
                
                if tech_score > 50:
                    result.validation_reasons.append(f"Tecnologías compatibles (score: {tech_score:.0f})")
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
        Analiza el contenido real de la página.
        Retorna (score, page_data).
        """
        page_data = {
            "title": "",
            "description": "",
            "keywords": []
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
            if desc_match:
                page_data["description"] = desc_match.group(1).strip()
            
            score = 50.0
            
            # Verificar tipo de negocio según el análisis
            if analysis.business_type == "ecommerce":
                score = self._score_ecommerce(html_lower, score)
            elif analysis.business_type == "saas":
                score = self._score_saas(html_lower, score)
            elif analysis.business_type == "agencia":
                score = self._score_agency(html_lower, score)
            else:
                # Scoring genérico
                score = self._score_generic_business(html_lower, analysis, score)
            
            # Verificar categoría de producto/servicio si se especifica
            if analysis.product_category:
                if analysis.product_category.lower() in html_lower:
                    score += 15
                    page_data["keywords"].append(analysis.product_category)
            
            if analysis.service_type:
                if analysis.service_type.lower() in html_lower:
                    score += 15
                    page_data["keywords"].append(analysis.service_type)
            
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
            
            return max(0, min(100, score)), page_data
            
        except Exception as e:
            return 30, page_data
    
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
    
    def _analyze_technologies(self, url: str, analysis: PromptAnalysis) -> tuple:
        """
        Analiza las tecnologías de la web.
        Retorna (score, tech_profile).
        """
        if not self.webtech:
            return 50, None
        
        try:
            profile = self.webtech.analyze(url)
            score = 50.0
            
            # Verificar si las tecnologías coinciden con el tipo de negocio
            if analysis.business_type == "ecommerce":
                if profile.is_ecommerce:
                    score += 30
                if profile.payment:
                    score += 10
            elif analysis.business_type == "saas":
                if profile.is_saas:
                    score += 30
            
            # Verificar tecnologías requeridas
            if analysis.required_technologies:
                matches = self.webtech.matches_criteria(
                    profile,
                    required_techs=analysis.required_technologies
                )
                if matches:
                    score += 20
            
            # Verificar tecnologías excluidas
            if analysis.excluded_technologies:
                has_excluded = not self.webtech.matches_criteria(
                    profile,
                    excluded_techs=analysis.excluded_technologies
                )
                if has_excluded:
                    score -= 30
            
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
