"""
Domain Verifier Module
Verifies and scores domains against prompt specifications
"""
import asyncio
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from loguru import logger

from ..config.settings import settings, BUSINESS_TYPE_SIGNATURES
from .prompt_parser import ParsedPrompt
from .search_engine import SearchResult
from .web_analyzer import WebAnalysis, WebAnalyzer


@dataclass
class VerificationResult:
    """Result of domain verification against prompt specifications"""
    domain: str
    url: str
    is_match: bool
    total_score: float  # 0.0 to 1.0
    
    # Component scores
    technology_score: float = 0.0
    content_score: float = 0.0
    metrics_score: float = 0.0
    quality_score: float = 0.0
    
    # Match details
    matched_technologies: List[str] = field(default_factory=list)
    matched_keywords: List[str] = field(default_factory=list)
    matched_metrics: Dict[str, bool] = field(default_factory=dict)
    
    # Business type detection
    detected_business_type: Optional[str] = None
    business_type_matches: bool = False
    
    # Analysis data
    web_analysis: Optional[WebAnalysis] = None
    search_result: Optional[SearchResult] = None
    
    # Reasons for match/no match
    match_reasons: List[str] = field(default_factory=list)
    rejection_reasons: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "url": self.url,
            "is_match": self.is_match,
            "total_score": round(self.total_score, 3),
            "scores": {
                "technology": round(self.technology_score, 3),
                "content": round(self.content_score, 3),
                "metrics": round(self.metrics_score, 3),
                "quality": round(self.quality_score, 3)
            },
            "detected_business_type": self.detected_business_type,
            "business_type_matches": self.business_type_matches,
            "matched_technologies": self.matched_technologies,
            "matched_keywords": self.matched_keywords,
            "matched_metrics": self.matched_metrics,
            "match_reasons": self.match_reasons,
            "rejection_reasons": self.rejection_reasons,
            "web_analysis": self.web_analysis.to_dict() if self.web_analysis else None
        }


class DomainVerifier:
    """
    Verifies domains against prompt specifications using multiple signals:
    - Technology detection (WebTech)
    - Content analysis (search snippets)
    - Performance metrics (PageSpeed)
    - Quality indicators
    """
    
    def __init__(self, analyzer: Optional[WebAnalyzer] = None):
        self.analyzer = analyzer or WebAnalyzer()
        self.weights = settings.scoring
    
    def _calculate_technology_score(self, analysis: WebAnalysis, 
                                   parsed_prompt: ParsedPrompt) -> tuple[float, List[str]]:
        """
        Calculate technology match score
        Returns (score, matched_technologies)
        """
        if not parsed_prompt.technology_signatures:
            return 0.5, []  # Neutral if no specific tech required
        
        tech_names = {t.name for t in analysis.technologies}
        expected_techs = set(parsed_prompt.technology_signatures)
        
        matched = tech_names & expected_techs
        
        if not matched:
            # Check for related technologies
            if parsed_prompt.business_type == "ecommerce":
                # Any ecommerce platform is good
                if analysis.detected_ecommerce_platform:
                    return 0.8, [analysis.detected_ecommerce_platform]
                if analysis.has_payment_processor:
                    return 0.6, ["payment_processor"]
            return 0.0, []
        
        # Score based on match percentage
        score = len(matched) / len(expected_techs)
        return min(score, 1.0), list(matched)
    
    def _calculate_content_score(self, search_result: SearchResult,
                                parsed_prompt: ParsedPrompt) -> tuple[float, List[str]]:
        """
        Calculate content relevance score based on search result
        Returns (score, matched_keywords)
        """
        matched = []
        score = 0.0
        
        # Combine title and snippet
        content = f"{search_result.title} {search_result.snippet}".lower()
        
        # Check product keywords
        for keyword in parsed_prompt.product_keywords:
            if keyword.lower() in content:
                matched.append(keyword)
                score += 0.2
        
        # Check custom keywords
        for keyword in parsed_prompt.custom_keywords:
            if keyword.lower() in content:
                matched.append(keyword)
                score += 0.15
        
        # Check business type keywords
        if parsed_prompt.business_type:
            btype_config = BUSINESS_TYPE_SIGNATURES.get(parsed_prompt.business_type, {})
            keywords = btype_config.get("keywords", [])
            for keyword in keywords[:5]:
                if keyword.lower() in content:
                    matched.append(f"business:{keyword}")
                    score += 0.1
        
        # Check for negative indicators
        negative_patterns = ["que es", "definicion", "como crear", "tutorial", "curso"]
        for pattern in negative_patterns:
            if pattern in content:
                score -= 0.2
        
        # Check relevance indicators from search
        positive_indicators = [i for i in search_result.relevance_indicators 
                             if not i.startswith("negative:")]
        negative_indicators = [i for i in search_result.relevance_indicators 
                              if i.startswith("negative:")]
        
        score += len(positive_indicators) * 0.05
        score -= len(negative_indicators) * 0.1
        
        return max(0.0, min(1.0, score)), matched
    
    def _calculate_metrics_score(self, analysis: WebAnalysis,
                                parsed_prompt: ParsedPrompt) -> tuple[float, Dict[str, bool]]:
        """
        Calculate metrics match score
        Returns (score, matched_metrics)
        """
        if not parsed_prompt.required_metrics:
            return 1.0, {}  # Full score if no metrics required
        
        if not analysis.pagespeed_metrics:
            return 0.5, {}  # Neutral if couldn't analyze
        
        matched = self.analyzer.check_metrics_match(analysis, parsed_prompt.required_metrics)
        
        if not matched:
            return 0.5, {}
        
        # Calculate score based on matched metrics
        match_count = sum(1 for v in matched.values() if v)
        score = match_count / len(matched)
        
        return score, matched
    
    def _calculate_quality_score(self, analysis: WebAnalysis,
                                search_result: SearchResult) -> float:
        """
        Calculate overall quality score
        """
        score = 0.0
        
        # HTTPS is good
        if analysis.pagespeed_metrics and analysis.pagespeed_metrics.has_https:
            score += 0.3
        elif analysis.url.startswith("https://"):
            score += 0.3
        
        # Having analytics indicates active business
        if analysis.has_analytics:
            score += 0.2
        
        # Having marketing tools indicates active business
        if analysis.has_marketing_tools:
            score += 0.15
        
        # Search position bonus (top results usually better)
        if search_result.position <= 3:
            score += 0.2
        elif search_result.position <= 10:
            score += 0.1
        
        # Performance score if available
        if analysis.pagespeed_metrics:
            if analysis.pagespeed_metrics.performance_score > 70:
                score += 0.15
            elif analysis.pagespeed_metrics.performance_score > 50:
                score += 0.1
        
        return min(score, 1.0)
    
    def _check_business_type_match(self, analysis: WebAnalysis,
                                   parsed_prompt: ParsedPrompt) -> tuple[bool, List[str], List[str]]:
        """
        Check if detected business type matches prompt requirements
        Returns (matches, reasons_for_match, reasons_for_rejection)
        """
        match_reasons = []
        rejection_reasons = []
        
        expected_type = parsed_prompt.business_type
        detected_type = analysis.detected_business_type
        
        # If no specific type required, consider it a match
        if not expected_type:
            return True, ["no_specific_type_required"], []
        
        # Direct match
        if detected_type == expected_type:
            match_reasons.append(f"business_type_match:{detected_type}")
            return True, match_reasons, rejection_reasons
        
        # Special case: dropshipping is a type of ecommerce
        if expected_type == "ecommerce" and detected_type == "dropshipping":
            match_reasons.append("dropshipping_is_ecommerce")
            return True, match_reasons, rejection_reasons
        
        # Check for specific indicators based on expected type
        if expected_type == "ecommerce":
            if analysis.detected_ecommerce_platform:
                match_reasons.append(f"ecommerce_platform:{analysis.detected_ecommerce_platform}")
                return True, match_reasons, rejection_reasons
            if analysis.has_payment_processor:
                match_reasons.append("has_payment_processor")
                return True, match_reasons, rejection_reasons
            rejection_reasons.append("no_ecommerce_indicators")
        
        elif expected_type == "saas":
            # Check for SaaS indicators
            tech_names = {t.name for t in analysis.technologies}
            saas_techs = {"React", "Vue.js", "Angular", "Next.js", "Node.js"}
            if tech_names & saas_techs and analysis.has_analytics:
                match_reasons.append("has_saas_stack")
                return True, match_reasons, rejection_reasons
            rejection_reasons.append("no_saas_indicators")
        
        elif expected_type == "agencia":
            # Agencies often have WordPress/Webflow + marketing tools
            if analysis.detected_cms and (analysis.has_marketing_tools or analysis.has_analytics):
                match_reasons.append("agency_pattern_detected")
                return True, match_reasons, rejection_reasons
            rejection_reasons.append("no_agency_indicators")
        
        # No match found
        if not rejection_reasons:
            rejection_reasons.append(f"type_mismatch:expected={expected_type},detected={detected_type}")
        
        return False, match_reasons, rejection_reasons
    
    async def verify(self, search_result: SearchResult, 
                    parsed_prompt: ParsedPrompt,
                    include_pagespeed: bool = True) -> VerificationResult:
        """
        Verify a single domain against prompt specifications
        """
        logger.info(f"Verifying domain: {search_result.domain}")
        
        # Perform web analysis
        analysis = await self.analyzer.analyze(
            search_result.url, 
            include_pagespeed=include_pagespeed
        )
        
        # Calculate component scores
        tech_score, matched_techs = self._calculate_technology_score(analysis, parsed_prompt)
        content_score, matched_keywords = self._calculate_content_score(search_result, parsed_prompt)
        metrics_score, matched_metrics = self._calculate_metrics_score(analysis, parsed_prompt)
        quality_score = self._calculate_quality_score(analysis, search_result)
        
        # Check business type match
        type_matches, match_reasons, rejection_reasons = self._check_business_type_match(
            analysis, parsed_prompt
        )
        
        # Calculate total score with weights
        total_score = (
            tech_score * self.weights.technology_match_weight +
            content_score * self.weights.content_match_weight +
            metrics_score * self.weights.metrics_match_weight +
            quality_score * self.weights.quality_score_weight
        )
        
        # Determine if it's a match
        is_match = (
            total_score >= self.weights.minimum_score_threshold and
            type_matches
        )
        
        # Add scoring reasons
        if tech_score > 0.5:
            match_reasons.append(f"technology_score:{tech_score:.2f}")
        if content_score > 0.5:
            match_reasons.append(f"content_score:{content_score:.2f}")
        if quality_score > 0.5:
            match_reasons.append(f"quality_score:{quality_score:.2f}")
        
        if tech_score < 0.3:
            rejection_reasons.append(f"low_technology_score:{tech_score:.2f}")
        if content_score < 0.3:
            rejection_reasons.append(f"low_content_score:{content_score:.2f}")
        if total_score < self.weights.minimum_score_threshold:
            rejection_reasons.append(f"below_threshold:{total_score:.2f}<{self.weights.minimum_score_threshold}")
        
        result = VerificationResult(
            domain=search_result.domain,
            url=search_result.url,
            is_match=is_match,
            total_score=total_score,
            technology_score=tech_score,
            content_score=content_score,
            metrics_score=metrics_score,
            quality_score=quality_score,
            matched_technologies=matched_techs,
            matched_keywords=matched_keywords,
            matched_metrics=matched_metrics,
            detected_business_type=analysis.detected_business_type,
            business_type_matches=type_matches,
            web_analysis=analysis,
            search_result=search_result,
            match_reasons=match_reasons,
            rejection_reasons=rejection_reasons
        )
        
        logger.info(f"Verification complete for {search_result.domain}: "
                   f"match={is_match}, score={total_score:.3f}")
        
        return result
    
    async def verify_batch(self, search_results: List[SearchResult],
                          parsed_prompt: ParsedPrompt,
                          include_pagespeed: bool = True,
                          max_concurrent: int = 5) -> List[VerificationResult]:
        """
        Verify multiple domains concurrently
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def verify_with_semaphore(result: SearchResult) -> VerificationResult:
            async with semaphore:
                try:
                    return await self.verify(result, parsed_prompt, include_pagespeed)
                except Exception as e:
                    logger.error(f"Verification error for {result.domain}: {e}")
                    return VerificationResult(
                        domain=result.domain,
                        url=result.url,
                        is_match=False,
                        total_score=0.0,
                        rejection_reasons=[f"error: {str(e)}"],
                        search_result=result
                    )
        
        tasks = [verify_with_semaphore(result) for result in search_results]
        results = await asyncio.gather(*tasks)
        
        # Sort by score descending
        results.sort(key=lambda r: r.total_score, reverse=True)
        
        return results
    
    def filter_matches(self, results: List[VerificationResult],
                      min_score: Optional[float] = None) -> List[VerificationResult]:
        """
        Filter results to only include matches above threshold
        """
        threshold = min_score or self.weights.minimum_score_threshold
        return [r for r in results if r.is_match and r.total_score >= threshold]


# Factory function
def create_domain_verifier(analyzer: Optional[WebAnalyzer] = None) -> DomainVerifier:
    """Create a DomainVerifier instance"""
    return DomainVerifier(analyzer=analyzer)
