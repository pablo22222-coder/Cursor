from __future__ import annotations

import re
from typing import Iterable, List
from urllib.parse import urlparse


WHITESPACE_RE = re.compile(r"\s+")
PUNCT_RE = re.compile(r"[^\w\s-]")


def normalize_text(text: str) -> str:
    if not text:
        return ""
    lowered = text.lower()
    cleaned = PUNCT_RE.sub(" ", lowered)
    return WHITESPACE_RE.sub(" ", cleaned).strip()


def tokenize(text: str) -> List[str]:
    return [token for token in normalize_text(text).split(" ") if token]


def extract_domain(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc or parsed.path
    host = host.split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def dedupe_preserve_order(items: Iterable[str]) -> List[str]:
    seen = set()
    output = []
    for item in items:
        if item not in seen:
            seen.add(item)
            output.append(item)
    return output


def contains_any(text: str, keywords: Iterable[str]) -> bool:
    normalized = normalize_text(text)
    return any(keyword in normalized for keyword in keywords)


def keyword_score(text: str, keywords: Iterable[str]) -> float:
    normalized = normalize_text(text)
    keyword_list = list(keywords)
    if not keyword_list:
        return 0.0
    hits = sum(1 for keyword in keyword_list if keyword in normalized)
    return hits / max(len(keyword_list), 1)
