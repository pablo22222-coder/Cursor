from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, List, Optional

from config.settings import Settings
from core.prompt_parser import PromptParser
from core.validation import DomainValidator
from detection.content_verifier import analyze_content, extract_content_summary
from detection.product_service_extractor import match_product_terms
from detection.site_type_classifier import classify_site_types
from models.domain_result import DomainResult
from models.prompt_spec import PromptSpec
from providers.pagespeed_client import PageSpeedClient, PageSpeedMetrics
from providers.serper_client import SerperClient, SerperSearchResult
from providers.webtech_client import WebTechClient
from utils.http import FetchResult, fetch_html
from utils.text import dedupe_preserve_order, extract_domain

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Candidate:
    domain: str
    url: str
    title: Optional[str]
    snippet: Optional[str]


class DomainPipeline:
    def __init__(
        self,
        settings: Settings,
        serper_client: SerperClient,
        pagespeed_client: PageSpeedClient,
        webtech_client: WebTechClient,
        fetcher: Callable[[str, int, int, str], FetchResult] = fetch_html,
    ) -> None:
        self.settings = settings
        self.serper_client = serper_client
        self.pagespeed_client = pagespeed_client
        self.webtech_client = webtech_client
        self.fetcher = fetcher
        self.parser = PromptParser()
        self.validator = DomainValidator(min_score=settings.min_score)

    def run(self, prompt: str, max_results: Optional[int] = None) -> List[DomainResult]:
        spec = self.parser.parse(prompt)
        queries = self._build_queries(spec)
        candidates = self._search_candidates(queries)

        results: List[DomainResult] = []
        max_items = max_results or self.settings.max_results
        pagespeed_calls = 0

        for candidate in candidates:
            if len(results) >= max_items:
                break
            result, used_pagespeed = self._evaluate_candidate(spec, candidate, pagespeed_calls)
            if used_pagespeed:
                pagespeed_calls += 1
            results.append(result)

        return sorted(results, key=lambda item: item.score, reverse=True)

    def _build_queries(self, spec: PromptSpec) -> List[str]:
        query = f"web que sea y cumpla:({spec.raw_prompt})"
        return [query]

    def _search_candidates(self, queries: List[str]) -> List[Candidate]:
        all_results: List[Candidate] = []
        for query in queries:
            results = self.serper_client.search(
                query=query,
                num_results=self.settings.serper_num,
                gl=self.settings.serper_gl,
                hl=self.settings.serper_hl,
                timeout=self.settings.request_timeout,
            )
            all_results.extend(self._map_candidates(results))

        return self._dedupe_candidates(all_results)

    def _map_candidates(self, results: List[SerperSearchResult]) -> List[Candidate]:
        mapped = []
        for result in results:
            domain = extract_domain(result.link)
            if not domain:
                continue
            mapped.append(
                Candidate(
                    domain=domain,
                    url=result.link,
                    title=result.title,
                    snippet=result.snippet,
                )
            )
        return mapped

    def _dedupe_candidates(self, candidates: List[Candidate]) -> List[Candidate]:
        seen = set()
        unique: List[Candidate] = []
        for candidate in candidates:
            if candidate.domain in seen:
                continue
            seen.add(candidate.domain)
            unique.append(candidate)
        return unique

    def _evaluate_candidate(
        self, spec: PromptSpec, candidate: Candidate, pagespeed_calls: int
    ) -> tuple[DomainResult, bool]:
        fetch_result = self.fetcher(
            candidate.url,
            timeout=self.settings.request_timeout,
            max_bytes=self.settings.max_content_bytes,
            user_agent=self.settings.user_agent,
        )

        if not fetch_result.ok:
            fetch_result = self.fetcher(
                candidate.domain,
                timeout=self.settings.request_timeout,
                max_bytes=self.settings.max_content_bytes,
                user_agent=self.settings.user_agent,
            )

        if not fetch_result.ok:
            return DomainResult(
                domain=candidate.domain,
                url=candidate.url,
                title=candidate.title,
                snippet=candidate.snippet,
                score=0.0,
                matched=False,
                reasons=["fetch_failed"],
            ), False

        summary = extract_content_summary(fetch_result.text)
        content_signals = analyze_content(summary)

        technologies = self.webtech_client.detect(fetch_result.url, timeout=self.settings.request_timeout)
        site_type_signals = classify_site_types(summary.text, technologies)
        product_match = match_product_terms(summary.text, spec.product_terms)

        pagespeed_metrics: Optional[PageSpeedMetrics] = None
        used_pagespeed = False
        if spec.metrics.needs_pagespeed() and pagespeed_calls < self.settings.max_pagespeed_calls:
            try:
                pagespeed_metrics = self.pagespeed_client.analyze(
                    fetch_result.url, strategy=self.settings.pagespeed_strategy, timeout=self.settings.request_timeout
                )
                used_pagespeed = pagespeed_metrics is not None
            except Exception as exc:  # pragma: no cover - network driven
                logger.warning("PageSpeed failed for %s: %s", fetch_result.url, exc)

        validation = self.validator.validate(
            prompt=spec,
            content_signals=content_signals,
            site_type_signals=site_type_signals,
            product_match=product_match,
            pagespeed_metrics=pagespeed_metrics,
        )

        result = DomainResult(
            domain=candidate.domain,
            url=fetch_result.url,
            title=candidate.title or summary.title,
            snippet=candidate.snippet or summary.description,
            score=validation.score,
            matched=validation.matched,
            reasons=dedupe_preserve_order(validation.reasons),
            site_types=[signal.site_type for signal in site_type_signals],
            technologies=technologies,
            metrics=validation.metrics,
        )
        return result, used_pagespeed
