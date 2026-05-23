"""
Routing prompts for Phase 2 (precision mode).

Dos decisiones independientes que se piden a la IA al mismo tiempo que
se interpreta el prompt del usuario:

  1. tech_scanner_decision  → ¿debemos activar Wappalyzer + DNA?
  2. pagespeed_decision     → ¿debemos activar PageSpeed Insights?

Ambas se ejecutan en paralelo y producen un dict con los campos que el
pipeline necesita para configurar la Fase 2. Si la IA falla, se devuelve
un default seguro (no activar; el flujo sigue sin Fase 2 técnica).

NOTA: estos prompts se envían vía AIManager, así que cualquier provider
de la cadena (Groq, Cerebras, SambaNova, Gemini, WebLLM) recibirá el
mismo prompt para tomar la misma decisión.
"""
from __future__ import annotations

import json
import re
import threading
from typing import Any, Dict, List, Optional

from src.services.ai_manager import complete_for_task
from src.services.task_chains import TASK_PROMPT_ANALYSIS


# ─────────────────────────────────────────────────────────────────────
#  PROMPT — Tech Stack Scanner Router
# ─────────────────────────────────────────────────────────────────────

_TECH_ROUTER_SYSTEM = """\
You are a routing intelligence for a web analysis pipeline. Your job is to
decide whether the user's prompt requires activating the Tech Stack
Scanner phase. Take into account efficiency: never activate it when it
brings no value, and always activate it when it is the only way to
satisfy the prompt.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TOOL IDENTITY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Name:    Tech Stack Scanner
Purpose: Autonomous technical evidence extractor. Given a URL, it
         downloads the page ONCE and runs a multi-engine analysis to
         produce a structured Findings JSON — neutral, with no
         judgments — designed to be consumed by a downstream AI agent.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ENGINE 1 — WAPPALYZER (signature database, 1500+ technologies)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Matches the page against a continuously maintained database of known
technology fingerprints. Returns technology name + detected version.

Detectable categories:
  CMS            → WordPress, Shopify, Wix, Webflow, Squarespace, Ghost
  CRM            → HubSpot, Salesforce, Zoho, Pipedrive
  Analytics      → Google Analytics 4, Hotjar, Mixpanel, Amplitude, Clarity
  SEO            → Yoast SEO, RankMath, SEMrush widgets
  Email/Marketing→ Mailchimp, Klaviyo, ActiveCampaign, Brevo, Drip
  Ecommerce      → WooCommerce, Magento, PrestaShop, BigCommerce
  CDN / Hosting  → Cloudflare, Fastly, Vercel, Netlify, WP Engine, Kinsta
  Payments       → Stripe, PayPal, Redsys
  Live Chat      → Intercom, Drift, Tidio, Zendesk
  Tag Managers   → Google Tag Manager, Segment
  Advertising    → Facebook Pixel, Google Ads, TikTok Pixel
  Security       → reCAPTCHA, Cloudflare Bot Management
  A/B Testing    → Optimizely, VWO
  JS Frameworks  → React, Vue, Angular, Next.js, Nuxt

Strength:  Fast, precise, versioned results for well-known platforms.
Weakness:  Blind to technologies not in its database, and to tools that
           load dynamically or leave no named script trace.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ENGINE 2 — DEEP DNA EXTRACTOR (raw HTML analysis, 6 dimensions)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Operates independently of any signature database. Scans 6 structural
dimensions of the raw HTML. Local processing, ~10ms.

  Dim 1 · External Script Map (src of <script>) → CDN-hosted SDKs.
  Dim 2 · Iframe Map (src of <iframe>) → embedded widgets, payment forms,
          live chat windows, scheduling tools, maps.
  Dim 3 · Inline JavaScript (text of <script> without src) → SDK
          initializations and global variable assignments
          (window.X, var X, gtag(, fbq(, hj(, _hsq, dataLayer, ...).
  Dim 4 · HTML Comment Scraper (<!-- ... -->) → CMS plugin signatures,
          page builder versions, SEO tools.
  Dim 5 · Form Action Deep Search (action of <form>, fallback data-*)
          → email platforms, CRMs and payment processors integrated via
          form submission.
  Dim 6 · Social Profile Discovery (cleaned <a href>) → official social
          media profiles (instagram.com, facebook.com, linkedin.com,
          twitter.com, x.com, youtube.com, tiktok.com), filtering out
          share / intent links.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HARD LIMITATIONS — what the scanner CANNOT do
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✗ Access pages requiring login, authentication or session cookies
  ✗ Analyze mobile apps, PDFs, or non-HTML content
  ✗ Detect technologies with zero HTML trace (pure server-side)
  ✗ Bypass Cloudflare or bot-protection systems blocking automated requests
  ✗ Evaluate visual design, copy quality, or business model
  ✗ Assess trustworthiness, reputation, or content quality
  ✗ Access subpages, dashboards, or admin panels not in the provided URL
  ✗ Find contact emails, phone numbers, prices, or any non-technical content

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DECISION RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ACTIVATE if the prompt:
    ✓ Mentions a specific technology, platform, or service by name
    ✓ Asks to verify whether a site uses or lacks a specific tool
    ✓ Requires filtering sites by their CMS, CRM, analytics, or stack
    ✓ Asks about integrations, plugins, SDKs, or third-party services
    ✓ Needs to identify the hosting, CDN, or infrastructure of a site
    ✓ Asks about payment processors, chat tools, or marketing platforms
    ✓ Needs to detect tracking pixels or advertising tools
    ✓ Asks to find or verify official social media profiles of a business
    ✓ Needs technical stack data as a filter before extracting contacts

DO NOT ACTIVATE if the prompt:
    ✗ Only asks for a contact email with no technology or stack condition
    ✗ Asks about content, niche, topic, or industry of a website
    ✗ Asks for business information (location, team, prices, services)
    ✗ Is a general question not tied to a specific URL or domain
    ✗ Asks to evaluate quality, sentiment, or credibility of content
    ✗ Requires only information not present in the HTML layer

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TARGET TECHNOLOGIES — when use_scanner is true, you MUST also extract
the list of technologies, platforms or categories that need to be
verified on the target sites. Use OFFICIAL or canonical names so they
match Wappalyzer's database (e.g. "Stripe", "Klaviyo", "WordPress",
"Google Analytics", "Shopify"). When the user mentions a category
instead of a specific tool, use the category name in lowercase
("crm", "cms", "analytics", "live_chat", "email_marketing",
"payment", "ecommerce"). Use ["ALL"] only when the user asks for
"all the technologies" or "the full stack" of a site.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RESPONSE FORMAT — respond ONLY with this JSON, no text before or after
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
  "use_scanner": true | false,
  "confidence": "high" | "medium" | "low",
  "reason": "one sentence explaining the decision",
  "extractable": true | false,
  "relevant_dimensions": ["wappalyzer", "scripts", "iframes", "inline_js",
                          "comments", "forms", "social_profiles"],
  "target_techs": ["Klaviyo", "Stripe", "CMS"],
  "limitation_note": "only present if extractable is false"
}
The field relevant_dimensions must list only the engines and DNA
dimensions that are directly useful for this specific prompt. The
target_techs field MUST be present and:
  · be an empty list [] when use_scanner is false,
  · contain canonical names of platforms / categories when use_scanner is true,
  · contain ["ALL"] only if the user explicitly wants the full stack.
"""

_TECH_ROUTER_USER_TEMPLATE = """\
USER PROMPT:
\"\"\"{prompt}\"\"\"

Decide whether the Tech Stack Scanner phase should run. Respond with the
exact JSON described in the system prompt — no extra text, no markdown
fences, no explanations outside the JSON.
"""


# ─────────────────────────────────────────────────────────────────────
#  PROMPT — PageSpeed Insights Router
# ─────────────────────────────────────────────────────────────────────

_PAGESPEED_ROUTER_SYSTEM = """\
You are a routing intelligence for a web analysis pipeline. You must
decide whether running Google PageSpeed Insights is profitable for the
user's prompt. Activate PageSpeed ONLY when the user's prompt contains
requirements that can ONLY be satisfied by its technical audits.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ENGINE 3 — PAGESPEED INSIGHTS API (Google, free tier)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Powered by two independent data sources run in parallel:
  · Lighthouse (lab simulation, controlled Google environment)
  · CrUX — Chrome User Experience Report (28-day field data)

This engine provides data that neither Wappalyzer nor the DNA extractor
can produce: scored quality signals, real-user behavioral data and
infrastructure-level diagnostics.

CATEGORIES IT CAN AUDIT:
  performance        → Lighthouse performance score (0-100), Core Web
                       Vitals (LCP, INP, CLS, FCP, TTFB).
  seo                → meta description, robots.txt, canonical URL,
                       hreflang, viewport, font sizes, tap targets,
                       structured data validity, indexability.
  accessibility      → WCAG audits: color contrast, ARIA, alt text,
                       keyboard navigation, form labels, heading order.
  best_practices     → HTTPS enforcement, mixed content, vulnerable JS
                       libraries (CVE), console errors, deprecated APIs.
  core_web_vitals    → LCP, INP, CLS, FCP, TTFB from real users (CrUX).
  security           → HTTPS, vulnerable JS libraries, console errors.
  mobile             → mobile-only Lighthouse audits, viewport, touch.
  third_party        → list of third-party domains with transfer size,
                       blocking time and request count.
  structured_data    → JSON-LD validity / presence.
  images             → modern formats (WebP, AVIF), lazy loading, sizing.
  javascript_quality → unused JS, duplicated JS, render-blocking,
                       vulnerable libraries.

ACTIVATE PAGESPEED if the prompt mentions or implies any of:
  ✓ Speed, load time, performance, Core Web Vitals
  ✓ SEO technical quality (meta tags, canonical, indexability,
    structured data)
  ✓ Mobile optimization or mobile-first filtering
  ✓ Security (HTTPS enforcement, vulnerable libraries, console errors)
  ✓ Accessibility compliance (WCAG, ADA, screen readers)
  ✓ Third-party script overhead, "clean" / "lightweight" sites
  ✓ Server response speed or hosting quality inference (TTFB)
  ✓ Image optimization (WebP, lazy loading, sizing)
  ✓ Any "well optimized", "professional", "technically sound" qualifier

DO NOT ACTIVATE if the prompt only asks about:
  ✗ Which specific tools or platforms a site uses → that's Wappalyzer/DNA
  ✗ Contact data, social profiles or business content → not in PSI
  ✗ Topic or niche of the website → not in PSI

When use_pagespeed is true, you MUST also list the categories that need
to be audited (subset of the list above). If the user only mentions
"speed", just return ["performance", "core_web_vitals"]. If the user
mentions several aspects, return all relevant categories. Use the
canonical underscore names exactly as listed above.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RESPONSE FORMAT — respond ONLY with this JSON, no text before or after
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
  "use_pagespeed": true | false,
  "confidence": "high" | "medium" | "low",
  "reason": "one sentence explaining the decision",
  "categories": ["performance", "seo", "core_web_vitals", "..."]
}
"""

_PAGESPEED_ROUTER_USER_TEMPLATE = """\
USER PROMPT:
\"\"\"{prompt}\"\"\"

Decide whether PageSpeed Insights should run. Respond with the exact
JSON described in the system prompt — no extra text, no markdown fences.
"""


# ─────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────

def _safe_json_parse(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                return None
    return None


def _normalize_dimensions(raw: Any) -> List[str]:
    valid = {"wappalyzer", "scripts", "iframes", "inline_js",
             "comments", "forms", "social_profiles"}
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for d in raw:
        if not isinstance(d, str):
            continue
        d = d.strip().lower()
        if d in valid and d not in out:
            out.append(d)
    return out


def _normalize_target_techs(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for t in raw:
        if not isinstance(t, str):
            continue
        t = t.strip()
        if not t:
            continue
        if t not in out:
            out.append(t)
    return out


def _normalize_pagespeed_categories(raw: Any) -> List[str]:
    valid = {
        "performance", "seo", "accessibility", "best_practices",
        "core_web_vitals", "security", "mobile", "third_party",
        "structured_data", "images", "javascript_quality",
    }
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for c in raw:
        if not isinstance(c, str):
            continue
        c = c.strip().lower().replace("-", "_").replace(" ", "_")
        if c in valid and c not in out:
            out.append(c)
    return out


def _normalize_confidence(value: Any) -> str:
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("high", "medium", "low"):
            return v
    return "low"


# ─────────────────────────────────────────────────────────────────────
#  API pública
# ─────────────────────────────────────────────────────────────────────

def decide_tech_scanner(user_prompt: str) -> Dict[str, Any]:
    """Decide si activar el Tech Stack Scanner. Defaults seguros si IA falla."""
    default = {
        "use_scanner": False,
        "confidence": "low",
        "reason": "router_unavailable",
        "extractable": True,
        "relevant_dimensions": [],
        "target_techs": [],
        "provider": "default",
    }
    if not user_prompt or not user_prompt.strip():
        return default

    try:
        msg = _TECH_ROUTER_USER_TEMPLATE.format(prompt=user_prompt[:1500])
        # Cadena TASK_PROMPT_ANALYSIS:
        #   Groq 70B → SambaNova 405B → Gemini Flash → User Own
        resp = complete_for_task(
            TASK_PROMPT_ANALYSIS,
            prompt=msg,
            system_prompt=_TECH_ROUTER_SYSTEM,
            json_mode=True,
        )
    except Exception as exc:  # pragma: no cover — defensivo
        default["reason"] = f"router_error:{type(exc).__name__}"
        return default

    if not resp.success or not resp.text.strip():
        return default

    data = _safe_json_parse(resp.text)
    if not isinstance(data, dict):
        return default

    use = bool(data.get("use_scanner"))
    return {
        "use_scanner":         use,
        "confidence":          _normalize_confidence(data.get("confidence")),
        "reason":              str(data.get("reason") or "")[:300],
        "extractable":         bool(data.get("extractable", True)),
        "relevant_dimensions": _normalize_dimensions(data.get("relevant_dimensions")),
        "target_techs":        _normalize_target_techs(data.get("target_techs")) if use else [],
        "provider":            getattr(resp, "provider", "unknown"),
    }


def decide_pagespeed(user_prompt: str) -> Dict[str, Any]:
    """Decide si activar PageSpeed. Defaults seguros si IA falla."""
    default = {
        "use_pagespeed": False,
        "confidence": "low",
        "reason": "router_unavailable",
        "categories": [],
        "provider": "default",
    }
    if not user_prompt or not user_prompt.strip():
        return default

    try:
        msg = _PAGESPEED_ROUTER_USER_TEMPLATE.format(prompt=user_prompt[:1500])
        # Cadena TASK_PROMPT_ANALYSIS (mismo orden que el router de tech)
        resp = complete_for_task(
            TASK_PROMPT_ANALYSIS,
            prompt=msg,
            system_prompt=_PAGESPEED_ROUTER_SYSTEM,
            json_mode=True,
        )
    except Exception as exc:  # pragma: no cover — defensivo
        default["reason"] = f"router_error:{type(exc).__name__}"
        return default

    if not resp.success or not resp.text.strip():
        return default

    data = _safe_json_parse(resp.text)
    if not isinstance(data, dict):
        return default

    use = bool(data.get("use_pagespeed"))
    return {
        "use_pagespeed": use,
        "confidence":    _normalize_confidence(data.get("confidence")),
        "reason":        str(data.get("reason") or "")[:300],
        "categories":    _normalize_pagespeed_categories(data.get("categories")) if use else [],
        "provider":      getattr(resp, "provider", "unknown"),
    }


def decide_routing_parallel(user_prompt: str) -> Dict[str, Dict[str, Any]]:
    """Lanza ambas decisiones en paralelo (dos threads). Devuelve un dict."""
    out: Dict[str, Dict[str, Any]] = {}

    def _t1():
        out["tech"] = decide_tech_scanner(user_prompt)

    def _t2():
        out["pagespeed"] = decide_pagespeed(user_prompt)

    th1 = threading.Thread(target=_t1, daemon=True)
    th2 = threading.Thread(target=_t2, daemon=True)
    th1.start(); th2.start()
    # 25 segundos de margen — los providers individuales tienen su propio timeout.
    th1.join(timeout=25)
    th2.join(timeout=25)
    if "tech" not in out:
        out["tech"] = {"use_scanner": False, "confidence": "low",
                       "reason": "router_thread_timeout", "extractable": True,
                       "relevant_dimensions": [], "target_techs": [],
                       "provider": "default"}
    if "pagespeed" not in out:
        out["pagespeed"] = {"use_pagespeed": False, "confidence": "low",
                            "reason": "router_thread_timeout",
                            "categories": [], "provider": "default"}
    return out


__all__ = [
    "decide_tech_scanner",
    "decide_pagespeed",
    "decide_routing_parallel",
]
