from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import List, Optional

from utils.text import normalize_text, tokenize


TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
DESCRIPTION_RE = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
    re.IGNORECASE | re.DOTALL,
)


TRANSACTIONAL_KEYWORDS = [
    "add to cart",
    "checkout",
    "buy",
    "pricing",
    "plans",
    "subscribe",
    "free trial",
]
INFORMATIONAL_KEYWORDS = [
    "what is",
    "definition",
    "guide",
    "blog",
    "news",
    "wikipedia",
    "learn more",
]
CONTACT_KEYWORDS = ["contact", "support", "email", "call us"]


class HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: List[str] = []
        self._ignore_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        if tag in {"script", "style", "noscript"}:
            self._ignore_depth += 1

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        if tag in {"script", "style", "noscript"} and self._ignore_depth > 0:
            self._ignore_depth -= 1

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        if self._ignore_depth == 0 and data.strip():
            self._chunks.append(data.strip())

    def text(self) -> str:
        return " ".join(self._chunks)


@dataclass(frozen=True)
class ContentSummary:
    title: Optional[str]
    description: Optional[str]
    text: str
    word_count: int


@dataclass(frozen=True)
class ContentSignals:
    transactional_score: float
    informational_score: float
    contact_score: float
    evidence: List[str] = field(default_factory=list)

    @property
    def is_transactional(self) -> bool:
        return self.transactional_score > self.informational_score


def extract_content_summary(html: str) -> ContentSummary:
    title_match = TITLE_RE.search(html)
    description_match = DESCRIPTION_RE.search(html)

    extractor = HTMLTextExtractor()
    extractor.feed(html)
    text = extractor.text()
    tokens = tokenize(text)

    return ContentSummary(
        title=title_match.group(1).strip() if title_match else None,
        description=description_match.group(1).strip() if description_match else None,
        text=text,
        word_count=len(tokens),
    )


def analyze_content(summary: ContentSummary) -> ContentSignals:
    normalized = normalize_text(summary.text)

    transactional_hits = [kw for kw in TRANSACTIONAL_KEYWORDS if kw in normalized]
    informational_hits = [kw for kw in INFORMATIONAL_KEYWORDS if kw in normalized]
    contact_hits = [kw for kw in CONTACT_KEYWORDS if kw in normalized]

    transactional_score = len(transactional_hits) / max(len(TRANSACTIONAL_KEYWORDS), 1)
    informational_score = len(informational_hits) / max(len(INFORMATIONAL_KEYWORDS), 1)
    contact_score = len(contact_hits) / max(len(CONTACT_KEYWORDS), 1)

    return ContentSignals(
        transactional_score=transactional_score,
        informational_score=informational_score,
        contact_score=contact_score,
        evidence=[*transactional_hits, *informational_hits, *contact_hits],
    )
