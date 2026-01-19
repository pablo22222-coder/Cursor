from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class DomainResult:
    domain: str
    url: str
    title: Optional[str]
    snippet: Optional[str]
    score: float
    matched: bool
    reasons: List[str] = field(default_factory=list)
    site_types: List[str] = field(default_factory=list)
    technologies: List[str] = field(default_factory=list)
    metrics: Dict[str, Optional[float]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "domain": self.domain,
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "score": round(self.score, 2),
            "matched": self.matched,
            "reasons": self.reasons,
            "site_types": self.site_types,
            "technologies": self.technologies,
            "metrics": self.metrics,
        }
