from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SerperSearchResult:
    title: Optional[str]
    link: str
    snippet: Optional[str]


class SerperClient:
    def __init__(self, api_key: str, endpoint: str) -> None:
        self.api_key = api_key
        self.endpoint = endpoint

    def search(self, query: str, num_results: int, gl: str, hl: str, timeout: int) -> List[SerperSearchResult]:
        if not self.api_key:
            raise ValueError("SERPER_API_KEY is required to perform search")

        payload = {"q": query, "num": num_results, "gl": gl, "hl": hl}
        headers = {"X-API-KEY": self.api_key, "Content-Type": "application/json"}
        logger.info("Serper search: %s", query)
        response = requests.post(
            self.endpoint, headers=headers, json=payload, timeout=timeout
        )
        response.raise_for_status()
        data = response.json()
        results = []
        for item in data.get("organic", []):
            link = item.get("link")
            if not link:
                continue
            results.append(
                SerperSearchResult(
                    title=item.get("title"),
                    link=link,
                    snippet=item.get("snippet"),
                )
            )
        return results
