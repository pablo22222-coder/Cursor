"""
PageSpeedTargeted — wrapper sobre PageSpeed Insights enfocado a las
categorías que la IA decide que son relevantes para el prompt.

Diferencias con PageSpeedAnalyzer:
  · El timeout total por dominio es de 50s (configurable).
  · El llamador pasa una lista `categories` (subset de:
        performance, seo, accessibility, best_practices,
        core_web_vitals, security, mobile, third_party,
        structured_data, images, javascript_quality)
    y solo se devuelven los datos de esas categorías. Si la lista está
    vacía o contiene "ALL" se devuelven todas.
  · Si la API falla, está caída o no hay créditos, NO se levanta
    excepción: se devuelve un dict con `available=False` para que el
    pipeline siga adelante sin PageSpeed.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import requests

from src.web_analyzer.pagespeed_analyzer import PageSpeedAnalyzer


PAGESPEED_TIMEOUT_SECONDS = 50


_ALL_CATEGORIES = (
    "performance", "seo", "accessibility", "best_practices",
    "core_web_vitals", "security", "mobile",
    "third_party", "structured_data", "images", "javascript_quality",
)


# Audits que extraemos por categoría — claves del JSON de Lighthouse.
_AUDITS_BY_CATEGORY: Dict[str, List[str]] = {
    "performance": [
        "first-contentful-paint", "largest-contentful-paint",
        "cumulative-layout-shift", "total-blocking-time",
        "speed-index", "interactive", "server-response-time",
    ],
    "core_web_vitals": [
        "largest-contentful-paint", "cumulative-layout-shift",
        "interaction-to-next-paint", "first-contentful-paint",
        "server-response-time",
    ],
    "seo": [
        "meta-description", "document-title", "robots-txt",
        "canonical", "hreflang", "structured-data",
        "viewport", "font-size", "tap-targets", "crawlable-anchors",
        "is-crawlable", "link-text", "http-status-code",
    ],
    "accessibility": [
        "color-contrast", "image-alt", "label", "aria-allowed-attr",
        "aria-required-attr", "aria-required-children",
        "aria-required-parent", "button-name", "document-title",
        "html-has-lang", "html-lang-valid", "heading-order",
        "link-name", "form-field-multiple-labels",
    ],
    "best_practices": [
        "is-on-https", "uses-http2", "no-vulnerable-libraries",
        "errors-in-console", "deprecations", "no-document-write",
        "image-aspect-ratio", "valid-source-maps",
    ],
    "security": [
        "is-on-https", "no-vulnerable-libraries",
        "uses-http2", "csp-xss",
    ],
    "mobile": [
        "viewport", "tap-targets", "font-size",
    ],
    "third_party": ["third-party-summary", "third-party-facades"],
    "structured_data": ["structured-data"],
    "images": [
        "uses-optimized-images", "uses-webp-images",
        "uses-responsive-images", "offscreen-images",
        "image-aspect-ratio", "image-size-responsive",
    ],
    "javascript_quality": [
        "unused-javascript", "duplicated-javascript",
        "no-unload-listeners", "no-vulnerable-libraries",
        "render-blocking-resources",
    ],
}


def _normalize_categories(cats: Optional[List[str]]) -> List[str]:
    if not cats:
        return list(_ALL_CATEGORIES)
    out: List[str] = []
    for c in cats:
        if not c:
            continue
        c = c.strip().lower().replace("-", "_").replace(" ", "_")
        if c == "all":
            return list(_ALL_CATEGORIES)
        # Aceptar sinónimos comunes
        if c in ("seo_score", "seo"):
            c = "seo"
        if c in ("performance_score", "performance", "speed", "core_web_vitals_score"):
            if c == "performance":
                c = "performance"
            else:
                c = "core_web_vitals" if "core" in c else "performance"
        if c in ("a11y", "accessibility"):
            c = "accessibility"
        if c in ("bp", "best_practices", "bestpractices"):
            c = "best_practices"
        if c in _ALL_CATEGORIES and c not in out:
            out.append(c)
    return out or list(_ALL_CATEGORIES)


def _audit_summary(audit: Dict[str, Any]) -> Dict[str, Any]:
    """Extrae los campos útiles de un audit Lighthouse."""
    if not isinstance(audit, dict):
        return {"value": None, "score": None}
    return {
        "title": audit.get("title"),
        "description": (audit.get("description") or "")[:300],
        "score": audit.get("score"),
        "displayValue": audit.get("displayValue"),
        "numericValue": audit.get("numericValue"),
        "numericUnit": audit.get("numericUnit"),
    }


def _extract_third_party(audits: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Resumen de third-party-summary listo para el LLM."""
    summary_audit = audits.get("third-party-summary") or {}
    items = ((summary_audit.get("details") or {}).get("items") or [])
    out: List[Dict[str, Any]] = []
    for it in items[:30]:
        out.append({
            "entity": (it.get("entity") or {}).get("text") if isinstance(it.get("entity"), dict)
                      else str(it.get("entity") or ""),
            "transferSize": it.get("transferSize"),
            "blockingTime": it.get("blockingTime"),
            "mainThreadTime": it.get("mainThreadTime"),
        })
    return out


def _extract_structured_data(audits: Dict[str, Any]) -> Dict[str, Any]:
    sd = audits.get("structured-data") or {}
    return {
        "score": sd.get("score"),
        "displayValue": sd.get("displayValue"),
        "passed": (sd.get("score") == 1) if sd.get("score") is not None else None,
    }


def _build_block(audits: Dict[str, Any], category: str) -> Dict[str, Any]:
    """Genera el bloque JSON para una categoría usando _AUDITS_BY_CATEGORY."""
    if category == "third_party":
        return {"items": _extract_third_party(audits)}
    if category == "structured_data":
        return {"json_ld": _extract_structured_data(audits)}

    items: Dict[str, Dict[str, Any]] = {}
    for key in _AUDITS_BY_CATEGORY.get(category, []):
        if key in audits:
            items[key] = _audit_summary(audits[key])
    return items


def _category_score(categories_obj: Dict[str, Any], category: str) -> Optional[float]:
    """Devuelve el score 0-100 para una categoría Lighthouse, o None."""
    mapping = {
        "performance": "performance",
        "seo": "seo",
        "accessibility": "accessibility",
        "best_practices": "best-practices",
    }
    key = mapping.get(category)
    if not key or key not in categories_obj:
        return None
    score = categories_obj[key].get("score")
    if score is None:
        return None
    return round(float(score) * 100, 1)


def _crux_metrics(crux: Dict[str, Any]) -> Dict[str, Any]:
    """Extrae los Core Web Vitals desde loadingExperience (CrUX)."""
    if not crux:
        return {}
    out: Dict[str, Any] = {"overall_category": crux.get("overall_category")}
    metrics = crux.get("metrics") or {}
    name_map = {
        "LARGEST_CONTENTFUL_PAINT_MS": "lcp_ms",
        "FIRST_CONTENTFUL_PAINT_MS": "fcp_ms",
        "CUMULATIVE_LAYOUT_SHIFT_SCORE": "cls",
        "INTERACTION_TO_NEXT_PAINT": "inp_ms",
        "EXPERIMENTAL_TIME_TO_FIRST_BYTE": "ttfb_ms",
    }
    for k, v in metrics.items():
        if not isinstance(v, dict):
            continue
        out[name_map.get(k, k.lower())] = {
            "percentile": v.get("percentile"),
            "category": v.get("category"),
        }
    return out


# ─────────────────────────────────────────────────────────────────────
#  API pública
# ─────────────────────────────────────────────────────────────────────

def run_pagespeed(
    url: str,
    *,
    categories: Optional[List[str]] = None,
    strategy: str = "mobile",
    timeout: float = PAGESPEED_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """
    Llama a PageSpeed Insights API y devuelve un JSON organizado por
    categorías con la información solicitada.

    Args:
        url: URL del dominio.
        categories: Lista de categorías a devolver (subset de _ALL_CATEGORIES).
                    None / vacía / "ALL" → todas.
        strategy: "mobile" | "desktop".
        timeout: timeout HTTP (segundos), por defecto 50.

    Returns:
        Dict con el siguiente formato::

            {
              "available": True | False,
              "ran": True | False,
              "elapsed_ms": ...,
              "strategy": "mobile",
              "categories_requested": [...],
              "scores": {                # 0-100 por categoría Lighthouse
                  "performance": ..., "seo": ..., ...
              },
              "core_web_vitals": {...},  # CrUX field data si está disponible
              "blocks": {                # uno por categoría pedida
                  "<categoria>": {...}
              },
              "error": null | "string",
              "fallback_reason": null | "no_api_key" | "http_error" | "timeout" | ...
            }
    """
    requested = _normalize_categories(categories)

    base = {
        "available": False,
        "ran": False,
        "strategy": strategy,
        "categories_requested": requested,
        "scores": {},
        "core_web_vitals": {},
        "blocks": {},
        "error": None,
        "fallback_reason": None,
        "elapsed_ms": 0.0,
    }

    analyzer = PageSpeedAnalyzer()
    if not analyzer.api_key:
        base["fallback_reason"] = "no_api_key"
        base["error"] = "PageSpeed API key not configured"
        return base

    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    # Mapeo de nuestras categorías → categorías que admite la API.
    # Si solo nos piden una de las "scoreables", podemos limitar `category`.
    api_categories: List[str] = []
    if any(c in requested for c in ("performance", "core_web_vitals", "third_party",
                                     "images", "javascript_quality", "mobile",
                                     "structured_data")):
        api_categories.append("performance")
    if "seo" in requested:
        api_categories.append("seo")
    if "accessibility" in requested:
        api_categories.append("accessibility")
    if "best_practices" in requested or "security" in requested:
        api_categories.append("best-practices")
    if not api_categories:
        api_categories = ["performance"]

    params = {
        "url": url,
        "key": analyzer.api_key,
        "strategy": strategy,
        "category": api_categories,
    }

    started = time.monotonic()
    try:
        resp = requests.get(analyzer.base_url, params=params, timeout=timeout)
    except requests.Timeout:
        base["fallback_reason"] = "timeout"
        base["error"] = f"Timeout ({timeout}s)"
        base["elapsed_ms"] = round((time.monotonic() - started) * 1000, 1)
        return base
    except requests.RequestException as exc:
        base["fallback_reason"] = "request_error"
        base["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        base["elapsed_ms"] = round((time.monotonic() - started) * 1000, 1)
        return base
    except Exception as exc:  # pragma: no cover — defensivo
        base["fallback_reason"] = "unexpected"
        base["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        base["elapsed_ms"] = round((time.monotonic() - started) * 1000, 1)
        return base

    base["elapsed_ms"] = round((time.monotonic() - started) * 1000, 1)

    if resp.status_code != 200:
        # Tratar 429 / 5xx / 403 (sin créditos) como NO disponible y seguir.
        base["fallback_reason"] = f"http_{resp.status_code}"
        base["error"] = f"HTTP {resp.status_code}: {resp.text[:200]}"
        return base

    try:
        data = resp.json()
    except ValueError:
        base["fallback_reason"] = "invalid_json"
        base["error"] = "Respuesta no es JSON válido"
        return base

    lighthouse = data.get("lighthouseResult", {}) or {}
    audits = lighthouse.get("audits", {}) or {}
    categories_obj = lighthouse.get("categories", {}) or {}

    # Scores por categoría Lighthouse
    base["scores"] = {
        "performance":     _category_score(categories_obj, "performance"),
        "seo":             _category_score(categories_obj, "seo"),
        "accessibility":   _category_score(categories_obj, "accessibility"),
        "best_practices":  _category_score(categories_obj, "best_practices"),
    }

    # CrUX field data
    base["core_web_vitals"] = _crux_metrics(data.get("loadingExperience") or {})

    # Bloques por categoría pedida
    blocks: Dict[str, Any] = {}
    for cat in requested:
        try:
            blocks[cat] = _build_block(audits, cat)
        except Exception as exc:
            blocks[cat] = {"_error": f"{type(exc).__name__}: {str(exc)[:80]}"}
    base["blocks"] = blocks

    base["available"] = True
    base["ran"] = True
    return base


__all__ = ["run_pagespeed", "PAGESPEED_TIMEOUT_SECONDS"]
