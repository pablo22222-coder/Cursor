from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from utils.text import normalize_text


SITE_TYPE_KEYWORDS: Dict[str, List[str]] = {
    "ecommerce": ["cart", "checkout", "add to cart", "product", "shop", "store", "buy"],
    "saas": ["pricing", "free trial", "subscription", "platform", "software"],
    "agency": ["agency", "services", "clients", "case studies", "portfolio"],
    "marketplace": ["marketplace", "vendors", "sell on", "listings"],
    "directory": ["directory", "listings", "browse", "categories"],
    "blog": ["blog", "post", "author", "newsletter", "subscribe"],
}

TECH_TYPE_MAP = {
    "Shopify": "ecommerce",
    "WooCommerce": "ecommerce",
    "Magento": "ecommerce",
    "BigCommerce": "ecommerce",
    "PrestaShop": "ecommerce",
    "Stripe": "saas",
    "Webflow": "agency",
}


@dataclass(frozen=True)
class SiteTypeSignal:
    site_type: str
    score: float
    evidence: List[str] = field(default_factory=list)


def classify_site_types(text: str, technologies: List[str]) -> List[SiteTypeSignal]:
    normalized = normalize_text(text)
    signals: List[SiteTypeSignal] = []

    for site_type, keywords in SITE_TYPE_KEYWORDS.items():
        hits = [keyword for keyword in keywords if keyword in normalized]
        keyword_score = len(hits) / max(len(keywords), 1)

        tech_hits = [tech for tech in technologies if TECH_TYPE_MAP.get(tech) == site_type]
        tech_score = min(len(tech_hits), 3) / 3

        score = round((keyword_score * 0.7) + (tech_score * 0.3), 3)
        if score > 0:
            signals.append(
                SiteTypeSignal(
                    site_type=site_type,
                    score=score,
                    evidence=[*hits, *tech_hits],
                )
            )

    return sorted(signals, key=lambda item: item.score, reverse=True)
