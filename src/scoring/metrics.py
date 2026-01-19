from __future__ import annotations

from typing import Optional

from scoring.rules import CONTENT_WEIGHT, METRICS_WEIGHT, PRODUCT_WEIGHT, SITE_TYPE_WEIGHT


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def compute_score(
    site_type_score: float,
    product_score: float,
    content_score: float,
    metrics_score: Optional[float],
) -> float:
    site_type_score = clamp(site_type_score)
    product_score = clamp(product_score)
    content_score = clamp(content_score)
    metrics_score = clamp(metrics_score or 0.0)

    weighted = (
        site_type_score * SITE_TYPE_WEIGHT
        + product_score * PRODUCT_WEIGHT
        + content_score * CONTENT_WEIGHT
        + metrics_score * METRICS_WEIGHT
    )
    return round(weighted * 100, 2)
