from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class PromptMetrics:
    require_pagespeed: bool = False
    performance_min: Optional[float] = None
    performance_max: Optional[float] = None
    seo_min: Optional[float] = None
    accessibility_min: Optional[float] = None
    best_practices_min: Optional[float] = None
    mobile_friendly: Optional[bool] = None
    load_speed: Optional[str] = None  # "fast" or "slow"

    def needs_pagespeed(self) -> bool:
        return self.require_pagespeed or any(
            metric is not None
            for metric in (
                self.performance_min,
                self.performance_max,
                self.seo_min,
                self.accessibility_min,
                self.best_practices_min,
                self.mobile_friendly,
                self.load_speed,
            )
        )


@dataclass(frozen=True)
class PromptSpec:
    raw_prompt: str
    site_types: List[str] = field(default_factory=list)
    product_terms: List[str] = field(default_factory=list)
    qualifiers: List[str] = field(default_factory=list)
    include_keywords: List[str] = field(default_factory=list)
    exclude_keywords: List[str] = field(default_factory=list)
    metrics: PromptMetrics = field(default_factory=PromptMetrics)
