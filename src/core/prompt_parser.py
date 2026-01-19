from __future__ import annotations

import re
from typing import List

from models.prompt_spec import PromptMetrics, PromptSpec
from utils.text import dedupe_preserve_order, normalize_text


SITE_TYPE_KEYWORDS = {
    "ecommerce": ["ecommerce", "tienda", "shop", "store"],
    "saas": ["saas", "software", "plataforma"],
    "agency": ["agencia", "agency", "marketing"],
    "dropshipping": ["dropshipping", "drop shipping"],
    "marketplace": ["marketplace", "market place"],
    "directory": ["directorio", "directory"],
}

METRICS_KEYWORDS = {
    "pagespeed": ["pagespeed", "core web vitals", "page speed"],
    "seo": ["seo"],
    "accessibility": ["accessibility", "accesibilidad"],
    "best_practices": ["best practices", "buenas practicas"],
    "mobile_friendly": ["mobile friendly", "responsive", "movil"],
}

STOP_PHRASES = [" con ", " que ", " sin ", " y ", " para ", " for ", " of "]


class PromptParser:
    def parse(self, prompt: str) -> PromptSpec:
        normalized = normalize_text(prompt)
        site_types = self._detect_site_types(normalized)
        product_terms = self._extract_product_terms(normalized, site_types)
        metrics = self._extract_metrics(normalized)
        include_keywords = dedupe_preserve_order(site_types + product_terms)

        return PromptSpec(
            raw_prompt=prompt,
            site_types=site_types,
            product_terms=product_terms,
            qualifiers=[],
            include_keywords=include_keywords,
            exclude_keywords=[],
            metrics=metrics,
        )

    def _detect_site_types(self, normalized: str) -> List[str]:
        detected = []
        for site_type, keywords in SITE_TYPE_KEYWORDS.items():
            if any(keyword in normalized for keyword in keywords):
                detected.append(site_type)
        return dedupe_preserve_order(detected)

    def _extract_product_terms(self, normalized: str, site_types: List[str]) -> List[str]:
        product_phrases = []
        for site_type in site_types:
            keywords = SITE_TYPE_KEYWORDS.get(site_type, [])
            for keyword in keywords:
                phrase = self._phrase_after_keyword(normalized, keyword)
                if phrase:
                    product_phrases.append(phrase)
        if not product_phrases:
            return []

        terms: List[str] = []
        for phrase in product_phrases:
            cleaned = phrase.strip()
            if cleaned:
                terms.append(cleaned)
                terms.extend(cleaned.split())
        return dedupe_preserve_order(terms)

    def _phrase_after_keyword(self, normalized: str, keyword: str) -> str:
        pattern = rf"{re.escape(keyword)}\s+(?:de|para|of|for)\s+([^.,;]+)"
        match = re.search(pattern, normalized)
        if not match:
            return ""
        phrase = match.group(1)
        for stop in STOP_PHRASES:
            if stop in phrase:
                phrase = phrase.split(stop)[0]
        return phrase.strip()

    def _extract_metrics(self, normalized: str) -> PromptMetrics:
        require_pagespeed = False
        load_speed = None
        seo_min = None
        accessibility_min = None
        best_practices_min = None
        mobile_friendly = None

        if any(word in normalized for word in ["lento", "lenta", "slow", "carga lenta"]):
            require_pagespeed = True
            load_speed = "slow"
        if any(word in normalized for word in ["rapido", "rapida", "fast", "carga rapida"]):
            require_pagespeed = True
            load_speed = "fast"

        if any(keyword in normalized for keyword in METRICS_KEYWORDS["pagespeed"]):
            require_pagespeed = True

        if any(keyword in normalized for keyword in METRICS_KEYWORDS["seo"]):
            require_pagespeed = True
            seo_min = 60.0

        if any(keyword in normalized for keyword in METRICS_KEYWORDS["accessibility"]):
            require_pagespeed = True
            accessibility_min = 60.0

        if any(keyword in normalized for keyword in METRICS_KEYWORDS["best_practices"]):
            require_pagespeed = True
            best_practices_min = 60.0

        if any(keyword in normalized for keyword in METRICS_KEYWORDS["mobile_friendly"]):
            require_pagespeed = True
            mobile_friendly = True

        return PromptMetrics(
            require_pagespeed=require_pagespeed,
            performance_min=None,
            performance_max=None,
            seo_min=seo_min,
            accessibility_min=accessibility_min,
            best_practices_min=best_practices_min,
            mobile_friendly=mobile_friendly,
            load_speed=load_speed,
        )
