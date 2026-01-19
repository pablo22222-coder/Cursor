from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    url: str
    status_code: Optional[int]
    ok: bool
    text: str
    content_type: Optional[str]
    error: Optional[str] = None


def ensure_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme:
        return url
    return f"https://{url}"


def fetch_html(
    url: str,
    timeout: int,
    max_bytes: int,
    user_agent: str,
) -> FetchResult:
    target = ensure_url(url)
    headers = {"User-Agent": user_agent}
    try:
        response = requests.get(
            target, headers=headers, timeout=timeout, allow_redirects=True, stream=True
        )
        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type:
            return FetchResult(
                url=response.url,
                status_code=response.status_code,
                ok=False,
                text="",
                content_type=content_type,
                error="non_html_content",
            )

        chunks = []
        collected = 0
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue
            chunks.append(chunk)
            collected += len(chunk)
            if collected >= max_bytes:
                break
        encoding = response.encoding or "utf-8"
        text = b"".join(chunks).decode(encoding, errors="ignore")
        return FetchResult(
            url=response.url,
            status_code=response.status_code,
            ok=response.ok,
            text=text,
            content_type=content_type,
        )
    except requests.RequestException as exc:
        logger.warning("Fetch failed for %s: %s", target, exc)
        return FetchResult(
            url=target,
            status_code=None,
            ok=False,
            text="",
            content_type=None,
            error=str(exc),
        )


def get_json(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 10,
) -> Dict[str, Any]:
    response = requests.get(url, headers=headers, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()
