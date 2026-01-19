from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional

import requests

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PageSpeedMetrics:
    performance: Optional[float] = None
    seo: Optional[float] = None
    accessibility: Optional[float] = None
    best_practices: Optional[float] = None
    lcp: Optional[float] = None
    cls: Optional[float] = None
    tti: Optional[float] = None

    def to_dict(self) -> Dict[str, Optional[float]]:
        return {
            "performance": self.performance,
            "seo": self.seo,
            "accessibility": self.accessibility,
            "best_practices": self.best_practices,
            "lcp": self.lcp,
            "cls": self.cls,
            "tti": self.tti,
        }


class PageSpeedClient:
    def __init__(self, api_key: str, endpoint: str = None) -> None:
        self.api_key = api_key
        self.endpoint = (
            endpoint or "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
        )

    def analyze(self, url: str, strategy: str, timeout: int) -> PageSpeedMetrics:
        if not self.api_key:
            raise ValueError("PAGESPEED_API_KEY is required to analyze metrics")

        params = {"url": url, "key": self.api_key, "strategy": strategy}
        logger.info("PageSpeed analyze: %s", url)
        response = requests.get(self.endpoint, params=params, timeout=timeout)
        response.raise_for_status()
        data = response.json()

        lighthouse = data.get("lighthouseResult", {})
        categories = lighthouse.get("categories", {})

        def score(category: str) -> Optional[float]:
            value = categories.get(category, {}).get("score")
            if value is None:
                return None
            return round(value * 100, 2)

        audits = lighthouse.get("audits", {})

        def numeric(audit_id: str) -> Optional[float]:
            value = audits.get(audit_id, {}).get("numericValue")
            if value is None:
                return None
            return round(float(value), 2)

        return PageSpeedMetrics(
            performance=score("performance"),
            seo=score("seo"),
            accessibility=score("accessibility"),
            best_practices=score("best-practices"),
            lcp=numeric("largest-contentful-paint"),
            cls=numeric("cumulative-layout-shift"),
            tti=numeric("interactive"),
        )
