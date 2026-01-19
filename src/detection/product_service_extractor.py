from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from utils.text import keyword_score, normalize_text


@dataclass(frozen=True)
class ProductMatch:
    matched_terms: List[str] = field(default_factory=list)
    score: float = 0.0


def match_product_terms(text: str, product_terms: List[str]) -> ProductMatch:
    if not product_terms:
        return ProductMatch()
    normalized = normalize_text(text)
    matched = [term for term in product_terms if term in normalized]
    score = keyword_score(text, product_terms)
    return ProductMatch(matched_terms=matched, score=score)
