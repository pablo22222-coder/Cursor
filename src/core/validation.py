from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from detection.content_verifier import ContentSignals
from detection.product_service_extractor import ProductMatch
from detection.site_type_classifier import SiteTypeSignal
from models.prompt_spec import PromptMetrics, PromptSpec
from providers.pagespeed_client import PageSpeedMetrics
from scoring.metrics import compute_score
from scoring.rules import MIN_MATCH_SCORE


@dataclass(frozen=True)
class ValidationResult:
    matched: bool
    score: float
    reasons: List[str] = field(default_factory=list)
    metrics: Dict[str, Optional[float]] = field(default_factory=dict)


class DomainValidator:
    def __init__(self, min_score: float = MIN_MATCH_SCORE) -> None:
        self.min_score = min_score

    def validate(
        self,
        prompt: PromptSpec,
        content_signals: ContentSignals,
        site_type_signals: List[SiteTypeSignal],
        product_match: ProductMatch,
        pagespeed_metrics: Optional[PageSpeedMetrics],
    ) -> ValidationResult:
        reasons: List[str] = []
        metrics_dict = pagespeed_metrics.to_dict() if pagespeed_metrics else {}

        site_type_score, site_type_ok = self._evaluate_site_types(prompt, site_type_signals)
        if not site_type_ok:
            reasons.append("site_type_mismatch")

        product_score, product_ok = self._evaluate_products(prompt, product_match)
        if not product_ok:
            reasons.append("product_terms_not_found")

        content_score = self._evaluate_content(content_signals)
        if not content_signals.is_transactional and prompt.site_types:
            reasons.append("content_looks_informational")

        metrics_score, metrics_ok = self._evaluate_metrics(prompt.metrics, pagespeed_metrics)
        if not metrics_ok:
            reasons.append("metrics_do_not_match")

        score = compute_score(site_type_score, product_score, content_score, metrics_score)
        matched = score >= self.min_score and site_type_ok and product_ok and metrics_ok

        return ValidationResult(matched=matched, score=score, reasons=reasons, metrics=metrics_dict)

    def _evaluate_site_types(
        self, prompt: PromptSpec, signals: List[SiteTypeSignal]
    ) -> Tuple[float, bool]:
        if not prompt.site_types:
            return 0.5, True
        for signal in signals:
            if signal.site_type in prompt.site_types and signal.score >= 0.2:
                return signal.score, True
        return 0.0, False

    def _evaluate_products(self, prompt: PromptSpec, match: ProductMatch) -> Tuple[float, bool]:
        if not prompt.product_terms:
            return 0.5, True
        return match.score, match.score >= 0.2

    def _evaluate_content(self, signals: ContentSignals) -> float:
        base = (signals.transactional_score + signals.contact_score) / 2
        if signals.informational_score > signals.transactional_score:
            base *= 0.6
        return base

    def _evaluate_metrics(
        self, metrics: PromptMetrics, pagespeed: Optional[PageSpeedMetrics]
    ) -> Tuple[Optional[float], bool]:
        if not metrics.needs_pagespeed():
            return 0.5, True
        if pagespeed is None:
            return 0.0, False

        scores = []
        ok = True

        if metrics.performance_min is not None:
            if pagespeed.performance is None or pagespeed.performance < metrics.performance_min:
                ok = False
            else:
                scores.append(pagespeed.performance / 100)

        if metrics.performance_max is not None:
            if pagespeed.performance is None or pagespeed.performance > metrics.performance_max:
                ok = False
            else:
                scores.append(1 - (pagespeed.performance / 100))

        if metrics.seo_min is not None:
            if pagespeed.seo is None or pagespeed.seo < metrics.seo_min:
                ok = False
            else:
                scores.append(pagespeed.seo / 100)

        if metrics.accessibility_min is not None:
            if pagespeed.accessibility is None or pagespeed.accessibility < metrics.accessibility_min:
                ok = False
            else:
                scores.append(pagespeed.accessibility / 100)

        if metrics.best_practices_min is not None:
            if pagespeed.best_practices is None or pagespeed.best_practices < metrics.best_practices_min:
                ok = False
            else:
                scores.append(pagespeed.best_practices / 100)

        if metrics.load_speed == "slow":
            if pagespeed.performance is None or pagespeed.performance > 50:
                ok = False
            else:
                scores.append(1 - (pagespeed.performance / 100))

        if metrics.load_speed == "fast":
            if pagespeed.performance is None or pagespeed.performance < 70:
                ok = False
            else:
                scores.append(pagespeed.performance / 100)

        if not scores:
            scores.append(0.5)

        return sum(scores) / len(scores), ok
