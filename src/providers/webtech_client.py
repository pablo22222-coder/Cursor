from __future__ import annotations

import logging
from typing import List

logger = logging.getLogger(__name__)

try:
    from webtech import WebTech
except ImportError:  # pragma: no cover - optional dependency
    WebTech = None


class WebTechClient:
    def __init__(self) -> None:
        if WebTech is None:
            logger.warning("webtech is not installed; technology detection disabled.")
            self._client = None
        else:
            self._client = WebTech()

    def detect(self, url: str, timeout: int) -> List[str]:
        if self._client is None:
            return []
        try:
            results = self._client.start_from_url(url, timeout=timeout)
        except Exception as exc:  # pragma: no cover - network driven
            logger.warning("WebTech failed for %s: %s", url, exc)
            return []

        technologies = []
        for item in results:
            apps = item.get("apps", [])
            for app in apps:
                name = app.get("name")
                if name:
                    technologies.append(name)
        return sorted(set(technologies))
