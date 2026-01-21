"""
Validador de dominios - Verifica si un dominio cumple con el prompt.

Este es el componente que decide si un dominio encontrado realmente
ES lo que busca el usuario.
"""
from typing import List, Tuple, Optional
from ..models.domain import (
    Domain, DomainAnalysis, PromptIntent, BusinessType,
    TechStack, PageSpeedMetrics
)
from .tech_analyzer import TechAnalyzer
from .pagespeed_analyzer import PageSpeedAnalyzer


class DomainValidator:
    """
    Valida si un dominio cumple con los requisitos del prompt.
    
    Combina análisis de tecnologías (WebTech) y métricas (PageSpeed)
    para determinar si una web ES lo que busca el usuario.
    """
    
    def __init__(self):
        """Inicializa el validador."""
        self.tech_analyzer = TechAnalyzer()
        self.pagespeed_analyzer = PageSpeedAnalyzer()
    
    def validate(
        self, 
        domain: Domain, 
        intent: PromptIntent,
        analyze_pagespeed: bool = False
    ) -> Domain:
        """
        Valida un dominio contra la intención del usuario.
        
        Args:
            domain: Dominio a validar
            intent: Intención extraída del prompt
            analyze_pagespeed: Si se deben analizar métricas de PageSpeed
            
        Returns:
            Domain con el análisis completado
        """
        analysis = DomainAnalysis()
        match_score = 0
        match_reasons = []
        
        # 0. Puntuación base por aparecer en búsqueda relevante
        # Si Google lo devolvió para esta query, tiene relevancia
        base_score = 15
        match_score += base_score
        match_reasons.append(f"Encontrado en búsqueda (posición {domain.search_position})")
        
        # Bonus por buena posición en resultados
        if domain.search_position <= 3:
            match_score += 10
            match_reasons.append("Top 3 en resultados de Google")
        elif domain.search_position <= 5:
            match_score += 5
            match_reasons.append("Top 5 en resultados de Google")
        
        # 1. Analizar tecnologías (no bloquea si falla)
        tech_stack = self.tech_analyzer.analyze(domain.url)
        if tech_stack:
            analysis.tech_stack = tech_stack
            
            # Detectar tipo de negocio basado en tecnologías
            detected_type = self.tech_analyzer.detect_business_type(tech_stack)
            analysis.detected_business_type = detected_type
            analysis.detection_reasons = self.tech_analyzer.get_detection_reasons(
                tech_stack, detected_type
            )
            
            # Calcular puntuación de coincidencia
            type_score, type_reasons = self._score_business_type_match(
                detected_type, intent.business_type, tech_stack
            )
            match_score += type_score
            match_reasons.extend(type_reasons)
        else:
            # Si no podemos analizar tecnologías, asumimos tipo según búsqueda
            analysis.detected_business_type = intent.business_type
            match_reasons.append("Tipo asumido por contexto de búsqueda")
        
        # 2. Analizar contenido/título/descripción
        content_score, content_reasons = self._score_content_match(domain, intent)
        match_score += content_score
        match_reasons.extend(content_reasons)
        
        # 3. Analizar PageSpeed si se solicita
        if analyze_pagespeed or intent.metrics_to_analyze:
            pagespeed = self.pagespeed_analyzer.analyze(domain.url)
            if pagespeed:
                analysis.pagespeed = pagespeed
                
                # Verificar métricas específicas del prompt
                metrics_score, metrics_reasons = self._score_metrics_match(
                    pagespeed, intent.metrics_to_analyze
                )
                match_score += metrics_score
                match_reasons.extend(metrics_reasons)
        
        # 4. Aplicar exclusiones (penalizar si tiene tecnología excluida)
        if intent.exclusions and analysis.tech_stack:
            exclusion_score, exclusion_reasons = self._apply_exclusions(
                analysis.tech_stack, intent.exclusions
            )
            match_score += exclusion_score  # Será negativo si encuentra exclusiones
            match_reasons.extend(exclusion_reasons)
        
        # 5. Aplicar requisitos (bonus si tiene tecnología requerida)
        if intent.requirements and analysis.tech_stack:
            requirement_score, requirement_reasons = self._apply_requirements(
                analysis.tech_stack, intent.requirements
            )
            match_score += requirement_score
            match_reasons.extend(requirement_reasons)
        
        # Determinar si cumple el prompt
        analysis.match_score = max(0, min(match_score, 100))  # Entre 0 y 100
        analysis.match_reasons = match_reasons
        analysis.matches_prompt = match_score >= 30
        
        domain.analysis = analysis
        return domain
    
    def _apply_exclusions(
        self,
        tech_stack: TechStack,
        exclusions: List[str]
    ) -> Tuple[int, List[str]]:
        """
        Penaliza dominios que tienen tecnologías excluidas.
        
        Args:
            tech_stack: Tecnologías detectadas
            exclusions: Lista de tecnologías a excluir
            
        Returns:
            Tuple de (puntuación negativa, razones)
        """
        score = 0
        reasons = []
        
        # Obtener todas las tecnologías como string para buscar
        all_techs = " ".join(tech_stack.all_technologies.get("detected", [])).lower()
        
        # También incluir campos específicos
        if tech_stack.cms:
            all_techs += " " + tech_stack.cms.lower()
        if tech_stack.ecommerce_platform:
            all_techs += " " + tech_stack.ecommerce_platform.lower()
        all_techs += " " + " ".join(tech_stack.payment_processors).lower()
        all_techs += " " + " ".join(tech_stack.analytics).lower()
        all_techs += " " + " ".join(tech_stack.email_marketing).lower()
        
        for exclusion in exclusions:
            if exclusion.lower() in all_techs:
                score -= 50  # Penalización fuerte
                reasons.append(f"⛔ Tiene {exclusion} (excluido)")
        
        return score, reasons
    
    def _apply_requirements(
        self,
        tech_stack: TechStack,
        requirements: List[str]
    ) -> Tuple[int, List[str]]:
        """
        Premia dominios que tienen tecnologías requeridas.
        
        Args:
            tech_stack: Tecnologías detectadas
            requirements: Lista de tecnologías requeridas
            
        Returns:
            Tuple de (puntuación positiva, razones)
        """
        score = 0
        reasons = []
        
        # Obtener todas las tecnologías como string para buscar
        all_techs = " ".join(tech_stack.all_technologies.get("detected", [])).lower()
        
        if tech_stack.cms:
            all_techs += " " + tech_stack.cms.lower()
        if tech_stack.ecommerce_platform:
            all_techs += " " + tech_stack.ecommerce_platform.lower()
        all_techs += " " + " ".join(tech_stack.payment_processors).lower()
        all_techs += " " + " ".join(tech_stack.analytics).lower()
        all_techs += " " + " ".join(tech_stack.email_marketing).lower()
        
        for requirement in requirements:
            if requirement.lower() in all_techs:
                score += 25  # Bonus por tener lo requerido
                reasons.append(f"✅ Tiene {requirement} (requerido)")
        
        return score, reasons
    
    def _score_business_type_match(
        self,
        detected: BusinessType,
        expected: BusinessType,
        tech_stack: TechStack
    ) -> Tuple[int, List[str]]:
        """
        Calcula puntuación por coincidencia de tipo de negocio.
        
        Returns:
            Tuple de (puntuación, razones)
        """
        score = 0
        reasons = []
        
        # Coincidencia exacta
        if detected == expected:
            score += 40
            reasons.append(f"Tipo de negocio coincide: {detected.value}")
        
        # Coincidencias parciales
        elif expected == BusinessType.ECOMMERCE:
            if detected == BusinessType.DROPSHIPPING:
                score += 35
                reasons.append("Es dropshipping (tipo de ecommerce)")
            elif tech_stack.payment_processors:
                score += 20
                reasons.append("Tiene procesadores de pago (posible ecommerce)")
        
        elif expected == BusinessType.DROPSHIPPING:
            if detected == BusinessType.ECOMMERCE:
                score += 30
                reasons.append("Es ecommerce (podría ser dropshipping)")
        
        # Bonus por plataforma de ecommerce específica
        if expected in [BusinessType.ECOMMERCE, BusinessType.DROPSHIPPING]:
            if tech_stack.ecommerce_platform:
                score += 15
                reasons.append(f"Plataforma: {tech_stack.ecommerce_platform}")
        
        return score, reasons
    
    def _score_content_match(
        self,
        domain: Domain,
        intent: PromptIntent
    ) -> Tuple[int, List[str]]:
        """
        Calcula puntuación por coincidencia en contenido (título/descripción).
        
        Returns:
            Tuple de (puntuación, razones)
        """
        score = 0
        reasons = []
        
        # Combinar título y descripción para análisis
        content = f"{domain.title or ''} {domain.description or ''} {domain.domain or ''}".lower()
        
        # Verificar nicho en contenido
        if intent.niche:
            niche_lower = intent.niche.lower()
            if niche_lower in content:
                score += 20
                reasons.append(f"Nicho '{intent.niche}' encontrado")
        
        # Verificar producto/servicio
        if intent.product_service:
            product_lower = intent.product_service.lower()
            if product_lower in content:
                score += 20
                reasons.append(f"Producto/servicio '{intent.product_service}' encontrado")
        
        # Verificar palabras del prompt original en contenido
        prompt_words = intent.original_prompt.lower().split()
        matching_words = [w for w in prompt_words if len(w) > 3 and w in content]
        if matching_words:
            score += min(len(matching_words) * 5, 15)
            reasons.append(f"Palabras del prompt encontradas: {', '.join(matching_words[:3])}")
        
        # Verificar indicadores de tipo de negocio en contenido
        if intent.business_type == BusinessType.ECOMMERCE:
            ecommerce_words = ["comprar", "tienda", "carrito", "envío", "productos", "shop", "store", "precio", "añadir", "oferta", "descuento", "moda", "ropa", "compra"]
            found_words = [w for w in ecommerce_words if w in content]
            if found_words:
                score += min(len(found_words) * 5, 20)
                reasons.append(f"Indicadores de ecommerce: {', '.join(found_words[:3])}")
        
        elif intent.business_type == BusinessType.AGENCY:
            agency_words = ["servicios", "portfolio", "proyectos", "agencia", "equipo", "clientes", "contacto", "presupuesto", "marketing", "digital", "estrategia"]
            found_words = [w for w in agency_words if w in content]
            if found_words:
                score += min(len(found_words) * 5, 20)
                reasons.append(f"Indicadores de agencia: {', '.join(found_words[:3])}")
        
        elif intent.business_type == BusinessType.SAAS:
            saas_words = ["pricing", "plans", "demo", "trial", "features", "software"]
            for word in saas_words:
                if word in content:
                    score += 5
                    reasons.append(f"Palabra clave '{word}' encontrada")
                    break
        
        return min(score, 30), reasons
    
    def _score_metrics_match(
        self,
        pagespeed: PageSpeedMetrics,
        metrics_to_check: List[str]
    ) -> Tuple[int, List[str]]:
        """
        Verifica si las métricas cumplen requisitos específicos del prompt.
        
        Returns:
            Tuple de (puntuación, razones)
        """
        score = 0
        reasons = []
        
        for metric in metrics_to_check:
            if metric == "velocidad":
                # Si el usuario busca webs lentas
                if self.pagespeed_analyzer.check_slow_site(pagespeed):
                    score += 10
                    reasons.append(f"Velocidad lenta (Speed Index: {pagespeed.speed_index:.1f}s)")
            
            elif metric == "seo":
                if self.pagespeed_analyzer.check_good_seo(pagespeed):
                    score += 10
                    reasons.append(f"Buen SEO (Score: {pagespeed.seo_score})")
            
            elif metric == "mobile":
                if pagespeed.is_mobile_friendly:
                    score += 10
                    reasons.append("Mobile friendly")
            
            elif metric == "performance":
                if pagespeed.performance_score and pagespeed.performance_score >= 80:
                    score += 10
                    reasons.append(f"Buen rendimiento (Score: {pagespeed.performance_score})")
        
        return score, reasons
    
    def validate_batch(
        self,
        domains: List[Domain],
        intent: PromptIntent,
        analyze_pagespeed: bool = False,
        max_concurrent: int = 5
    ) -> List[Domain]:
        """
        Valida múltiples dominios.
        
        Args:
            domains: Lista de dominios a validar
            intent: Intención del usuario
            analyze_pagespeed: Si analizar PageSpeed
            max_concurrent: Máximo de validaciones concurrentes
            
        Returns:
            Lista de dominios validados, ordenados por puntuación
        """
        validated = []
        
        for domain in domains:
            try:
                validated_domain = self.validate(domain, intent, analyze_pagespeed)
                validated.append(validated_domain)
            except Exception as e:
                domain.error_message = str(e)
                domain.is_valid = False
                validated.append(domain)
        
        # Ordenar por puntuación de coincidencia
        validated.sort(
            key=lambda d: d.analysis.match_score if d.analysis else 0,
            reverse=True
        )
        
        return validated
    
    def filter_matching(
        self,
        domains: List[Domain],
        min_score: int = 50
    ) -> List[Domain]:
        """
        Filtra dominios que cumplen con el prompt.
        
        Args:
            domains: Dominios validados
            min_score: Puntuación mínima para considerar coincidencia
            
        Returns:
            Lista de dominios que cumplen el prompt
        """
        return [
            d for d in domains
            if d.analysis and d.analysis.match_score >= min_score
        ]
