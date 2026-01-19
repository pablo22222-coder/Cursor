from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    serper_api_key: str
    pagespeed_api_key: str
    serper_endpoint: str
    pagespeed_endpoint: str
    serper_gl: str
    serper_hl: str
    serper_num: int
    request_timeout: int
    max_content_bytes: int
    max_results: int
    max_pagespeed_calls: int
    pagespeed_strategy: str
    min_score: float
    user_agent: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            serper_api_key=os.getenv("SERPER_API_KEY", "").strip(),
            pagespeed_api_key=os.getenv("PAGESPEED_API_KEY", "").strip(),
            serper_endpoint=os.getenv("SERPER_ENDPOINT", "https://google.serper.dev/search"),
            pagespeed_endpoint=os.getenv(
                "PAGESPEED_ENDPOINT", "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
            ),
            serper_gl=os.getenv("SERPER_GL", "es"),
            serper_hl=os.getenv("SERPER_HL", "es"),
            serper_num=int(os.getenv("SERPER_NUM", "10")),
            request_timeout=int(os.getenv("REQUEST_TIMEOUT", "10")),
            max_content_bytes=int(os.getenv("MAX_CONTENT_BYTES", "120000")),
            max_results=int(os.getenv("MAX_RESULTS", "20")),
            max_pagespeed_calls=int(os.getenv("MAX_PAGESPEED_CALLS", "5")),
            pagespeed_strategy=os.getenv("PAGESPEED_STRATEGY", "mobile"),
            min_score=float(os.getenv("MIN_SCORE", "60")),
            user_agent=os.getenv(
                "USER_AGENT",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            ),
        )
