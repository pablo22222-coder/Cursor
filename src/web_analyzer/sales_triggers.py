"""
SalesTriggers — Extracción ligera de disparadores de venta para prospección.

Estrategia de herramientas (de menor a mayor coste):
  1. dnspython + python-whois  → DNS / MX / WHOIS (sin HTTP)
  2. requests + BeautifulSoup  → HTML estático (sin JS)
  3. Wappalyzergo subprocess   → Tech stack (30s timeout)
  4. Playwright                → Solo si los anteriores fallan (no usado aquí)

Salida: dict `sales_triggers` listo para adjuntarse a domain_info.
"""
from __future__ import annotations

import re
import socket
import ssl
import json
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# ── Timeouts ────────────────────────────────────────────────────────────────
HTTP_TIMEOUT       = 10   # requests.get
WAPPALYZER_TIMEOUT = 30   # subprocess (wappalyzergo)
SSL_TIMEOUT        = 8

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

# ── Helpers ──────────────────────────────────────────────────────────────────

def _get(url: str, timeout: int = HTTP_TIMEOUT) -> Optional[requests.Response]:
    try:
        return requests.get(
            url, timeout=timeout,
            headers={"User-Agent": _UA},
            allow_redirects=True,
        )
    except Exception:
        return None


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _domain_from_url(url: str) -> str:
    return urlparse(url).netloc.lstrip("www.") or url


# ═══════════════════════════════════════════════════════════════════════════
#  MÓDULO 1 — INFRAESTRUCTURA (WHOIS / DNS / SSL)
# ═══════════════════════════════════════════════════════════════════════════

def _infra(domain: str, url: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "domain_age_years":   None,
        "registered_date":    None,
        "mx_provider":        None,
        "ssl_valid":          None,
        "ssl_expires":        None,
        "ssl_days_remaining": None,
        "hosting_ip":         None,
        "hosting_provider":   None,
    }

    # ── WHOIS ─────────────────────────────────────────────────────────────
    try:
        import whois as _whois
        w = _whois.whois(domain)
        creation = w.creation_date
        if isinstance(creation, list):
            creation = creation[0]
        if creation:
            if isinstance(creation, str):
                creation = datetime.fromisoformat(creation)
            if creation.tzinfo is None:
                creation = creation.replace(tzinfo=timezone.utc)
            result["registered_date"] = creation.strftime("%Y-%m-%d")
            age = (datetime.now(timezone.utc) - creation).days / 365.25
            result["domain_age_years"] = round(age, 1)
    except Exception:
        pass

    # ── MX records → email provider ──────────────────────────────────────
    try:
        import dns.resolver
        answers = dns.resolver.resolve(domain, "MX", lifetime=5)
        mx_hosts = [str(r.exchange).lower() for r in answers]
        mx_str = " ".join(mx_hosts)
        if any("google" in m or "googlemail" in m for m in mx_hosts):
            result["mx_provider"] = "Google Workspace"
        elif any("outlook" in m or "microsoft" in m or "protection.outlook" in m for m in mx_hosts):
            result["mx_provider"] = "Microsoft 365"
        elif any("zoho" in m for m in mx_hosts):
            result["mx_provider"] = "Zoho Mail"
        elif mx_hosts:
            result["mx_provider"] = mx_hosts[0].rstrip(".")
    except Exception:
        pass

    # ── SSL ───────────────────────────────────────────────────────────────
    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(
            socket.create_connection((domain, 443), timeout=SSL_TIMEOUT),
            server_hostname=domain,
        ) as s:
            cert = s.getpeercert()
            not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
            not_after = not_after.replace(tzinfo=timezone.utc)
            days_left = (not_after - datetime.now(timezone.utc)).days
            result["ssl_valid"]          = days_left > 0
            result["ssl_expires"]        = not_after.strftime("%Y-%m-%d")
            result["ssl_days_remaining"] = days_left
    except Exception:
        pass

    # ── IP / Hosting ──────────────────────────────────────────────────────
    try:
        ip = socket.gethostbyname(domain)
        result["hosting_ip"] = ip
        # Identify provider via RDAP/IP ranges heuristic (lightweight)
        try:
            rdap = requests.get(
                f"https://rdap.arin.net/registry/ip/{ip}",
                timeout=4, headers={"User-Agent": _UA}
            )
            if rdap.ok:
                name = rdap.json().get("name", "").lower()
                _providers = {
                    "Amazon":      ["amazon", "aws", "ec2"],
                    "Cloudflare":  ["cloudflare"],
                    "Google":      ["google"],
                    "Microsoft":   ["microsoft", "azure"],
                    "DigitalOcean":["digitalocean"],
                    "OVH":         ["ovh"],
                    "Hetzner":     ["hetzner"],
                    "Vultr":       ["vultr"],
                }
                for provider, keys in _providers.items():
                    if any(k in name for k in keys):
                        result["hosting_provider"] = provider
                        break
                if not result["hosting_provider"]:
                    result["hosting_provider"] = rdap.json().get("name", "Desconocido")
        except Exception:
            pass
    except Exception:
        pass

    return result


# ═══════════════════════════════════════════════════════════════════════════
#  MÓDULO 2 — MARKETING (Sales Triggers)
# ═══════════════════════════════════════════════════════════════════════════

# Patterns
_PIXEL_PATTERNS = {
    "meta_pixel":    re.compile(r"connect\.facebook\.net|fbq\s*\(|facebook\.com/tr", re.I),
    "tiktok_pixel":  re.compile(r"analytics\.tiktok\.com|ttq\s*\(|tiktok\.com/i18n", re.I),
    "google_ads":    re.compile(r"googleadservices\.com|gtag\s*\(|AW-\d{9,}", re.I),
    "google_tag_mgr":re.compile(r"googletagmanager\.com/gtm\.js|GTM-[A-Z0-9]+", re.I),
}
_SUPPORT_PATTERNS = {
    "whatsapp":  re.compile(r"wa\.me/|whatsapp\.com|api\.whatsapp", re.I),
    "zendesk":   re.compile(r"zendesk\.com|zopim\.com|zE\s*\(", re.I),
    "intercom":  re.compile(r"intercom\.io|intercomSettings|Intercom\s*\(", re.I),
    "tidio":     re.compile(r"code\.tidio\.co|Tawk", re.I),
    "crisp":     re.compile(r"client\.crisp\.chat", re.I),
    "drift":     re.compile(r"js\.driftt\.com", re.I),
}
_EMAIL_MKT_PATTERNS = {
    "mailchimp":      re.compile(r"mailchimp\.com|mc\.us\d+\.list-manage", re.I),
    "klaviyo":        re.compile(r"klaviyo\.com|_learnq\s*\(", re.I),
    "activecampaign": re.compile(r"activehosted\.com|activecampaign\.com", re.I),
    "brevo":          re.compile(r"brevo\.com|sendinblue\.com", re.I),
    "convertkit":     re.compile(r"convertkit\.com", re.I),
}
_POPUP_PATTERNS = re.compile(
    r"optinmonster|privy\.com|popupsmart|sumo\.com|wishpond|hellobar|"
    r"wheelio|spin-a-sale|jscrambler|picreel", re.I
)
_LEAD_MAGNET_KW = [
    "suscribirse", "suscribete", "subscribe", "newsletter",
    "descarga gratis", "free download", "ebook", "lead magnet",
    "regístrate", "sign up", "get started", "gratis",
]

def _marketing(html: str, url: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "pixels":         {},
        "support_widgets":[],
        "email_marketing":[],
        "has_popups":     False,
        "lead_magnets":   [],
    }

    # Pixels
    for name, pattern in _PIXEL_PATTERNS.items():
        result["pixels"][name] = bool(pattern.search(html))

    # Support widgets
    for name, pattern in _SUPPORT_PATTERNS.items():
        if pattern.search(html):
            result["support_widgets"].append(name)

    # Email marketing
    for name, pattern in _EMAIL_MKT_PATTERNS.items():
        if pattern.search(html):
            result["email_marketing"].append(name)

    # Popups
    result["has_popups"] = bool(_POPUP_PATTERNS.search(html))

    # Lead magnets: look for keywords + form links
    soup = _soup(html)
    html_lower = html.lower()
    found_magnets = []
    for kw in _LEAD_MAGNET_KW:
        if kw in html_lower:
            # Try to find a nearby link
            for a in soup.find_all("a", href=True):
                if kw in (a.get_text() or "").lower():
                    href = a["href"]
                    full = urljoin(url, href) if not href.startswith("http") else href
                    if full not in found_magnets:
                        found_magnets.append(full)
            if not found_magnets:
                found_magnets.append(kw)  # keyword as placeholder
            break
    result["lead_magnets"] = found_magnets[:3]

    return result


# ═══════════════════════════════════════════════════════════════════════════
#  MÓDULO 3 — SEO & CONTENIDO
# ═══════════════════════════════════════════════════════════════════════════

def _seo(soup: BeautifulSoup, url: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "h1":              None,
        "meta_title":      None,
        "meta_description":None,
        "missing_title":   False,
        "missing_description": False,
        "blog_url":        None,
        "last_post_date":  None,
        "last_post_url":   None,
    }

    # H1
    h1 = soup.find("h1")
    result["h1"] = h1.get_text(strip=True)[:120] if h1 else None

    # Meta
    title_tag = soup.find("title")
    result["meta_title"] = title_tag.get_text(strip=True)[:120] if title_tag else None
    result["missing_title"] = not bool(result["meta_title"])

    desc = soup.find("meta", attrs={"name": re.compile(r"description", re.I)})
    if desc:
        result["meta_description"] = (desc.get("content") or "")[:200]
    result["missing_description"] = not bool(result["meta_description"])

    # Blog detection
    for path in ["/blog", "/noticias", "/news", "/articulos", "/posts"]:
        blog_url = urljoin(url, path)
        resp = _get(blog_url, timeout=6)
        if resp and resp.ok and len(resp.text) > 500:
            result["blog_url"] = blog_url
            # Try to extract last post date from the blog page
            bsoup = _soup(resp.text)
            for tag in bsoup.find_all(["time", "span", "p"], limit=20):
                text = tag.get_text(strip=True)
                m = re.search(r"(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}|\d{4}[/\-\.]\d{1,2}[/\-\.]\d{1,2})", text)
                if m:
                    result["last_post_date"] = m.group(1)
                    # Try to find the post link
                    parent_a = tag.find_parent("a")
                    if parent_a and parent_a.get("href"):
                        href = parent_a["href"]
                        result["last_post_url"] = urljoin(url, href) if not href.startswith("http") else href
                    break
            break

    return result


# ═══════════════════════════════════════════════════════════════════════════
#  MÓDULO 4 — OUTREACH (Social + Language)
# ═══════════════════════════════════════════════════════════════════════════

_SOCIAL_RE = {
    "linkedin":  re.compile(r"https?://(?:www\.)?linkedin\.com/(?:company|in)/[^\s\"'<>]+", re.I),
    "instagram": re.compile(r"https?://(?:www\.)?instagram\.com/[^\s\"'<>]+", re.I),
    "facebook":  re.compile(r"https?://(?:www\.)?facebook\.com/[^\s\"'<>]+", re.I),
    "twitter":   re.compile(r"https?://(?:www\.)?(?:twitter|x)\.com/[^\s\"'<>]+", re.I),
}

def _outreach(html: str, soup: BeautifulSoup) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "language": None,
        "social_links": {},
    }

    # Language from <html lang>
    html_tag = soup.find("html")
    if html_tag:
        lang = (html_tag.get("lang") or "").split("-")[0].lower()
        result["language"] = lang or None

    # Social links
    for platform, pattern in _SOCIAL_RE.items():
        matches = pattern.findall(html)
        clean = [
            m.rstrip(".,;)\"'") for m in matches
            if "share" not in m.lower() and "sharer" not in m.lower()
        ]
        if clean:
            result["social_links"][platform] = clean[0]

    return result


# ═══════════════════════════════════════════════════════════════════════════
#  MÓDULO 5 — LEGAL & ESCALA (sitemap + ads.txt)
# ═══════════════════════════════════════════════════════════════════════════

def _legal_scale(url: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "sitemap_url_count": None,
        "has_ads_txt":       False,
    }

    # Sitemap
    for path in ["/sitemap.xml", "/sitemap_index.xml", "/sitemap/"]:
        resp = _get(urljoin(url, path), timeout=8)
        if resp and resp.ok and "xml" in resp.headers.get("Content-Type", ""):
            urls = re.findall(r"<loc>([^<]+)</loc>", resp.text)
            result["sitemap_url_count"] = len(urls)
            break

    # ads.txt
    resp = _get(urljoin(url, "/ads.txt"), timeout=5)
    result["has_ads_txt"] = bool(resp and resp.ok and len(resp.text) > 10)

    return result


# ═══════════════════════════════════════════════════════════════════════════
#  MÓDULO 6 — E-COMMERCE AVANZADO (reviews check)
# ═══════════════════════════════════════════════════════════════════════════

_REVIEW_PATTERNS = {
    "trustpilot":  re.compile(r"trustpilot\.com|widget\.trustpilot", re.I),
    "yotpo":       re.compile(r"yotpo\.com|staticw2\.yotpo", re.I),
    "judge_me":    re.compile(r"judge\.me|judgeme", re.I),
    "stamped":     re.compile(r"stamped\.io", re.I),
    "loox":        re.compile(r"loox\.io", re.I),
    "schema_review": re.compile(r'"@type"\s*:\s*"Review"', re.I),
}

def _ecommerce_reviews(html: str, soup: BeautifulSoup, tech_profile: Optional[Dict]) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "is_ecommerce_platform": False,
        "platform":              None,
        "has_reviews":           False,
        "review_platform":       None,
        "sample_review":         None,
        "upsell_opportunity":    False,
    }

    # Detect platform
    all_techs = []
    if tech_profile:
        all_techs = [t.lower() for t in (tech_profile.get("all_techs") or [])]
    html_lower = html.lower()

    if any("shopify" in t for t in all_techs) or "shopify" in html_lower:
        result["is_ecommerce_platform"] = True
        result["platform"] = "Shopify"
    elif any("woocommerce" in t for t in all_techs) or "woocommerce" in html_lower:
        result["is_ecommerce_platform"] = True
        result["platform"] = "WooCommerce"

    if not result["is_ecommerce_platform"]:
        return result

    # Check for reviews
    for platform, pattern in _REVIEW_PATTERNS.items():
        if pattern.search(html):
            result["has_reviews"] = True
            result["review_platform"] = platform
            break

    # Extract sample review text from schema
    if not result["has_reviews"]:
        result["upsell_opportunity"] = True  # No reviews = sales opportunity

    # Try to extract a sample review from schema or DOM
    if result["has_reviews"]:
        try:
            for script in soup.find_all("script", type="application/ld+json"):
                data = json.loads(script.string or "")
                reviews = []
                if isinstance(data, dict):
                    if data.get("@type") == "Review":
                        reviews = [data]
                    elif "review" in data:
                        reviews = data["review"] if isinstance(data["review"], list) else [data["review"]]
                if reviews:
                    r = reviews[0]
                    body = r.get("reviewBody") or r.get("description") or ""
                    if body:
                        result["sample_review"] = body[:200]
                    break
        except Exception:
            pass

    return result


# ═══════════════════════════════════════════════════════════════════════════
#  ALERTAS
# ═══════════════════════════════════════════════════════════════════════════

def _compute_alerts(infra: Dict, marketing: Dict, ecommerce: Dict) -> List[str]:
    alerts: List[str] = []

    # SSL expiring soon
    days = infra.get("ssl_days_remaining")
    if days is not None:
        if days <= 0:
            alerts.append("🔴 PRIORIDAD ALTA — SSL expirado")
        elif days <= 30:
            alerts.append(f"🟠 PRIORIDAD ALTA — SSL expira en {days} días")

    # No pixel
    pixels = marketing.get("pixels", {})
    has_any_pixel = any(pixels.values())
    if not has_any_pixel:
        alerts.append("🟡 PRIORIDAD ALTA — Sin píxeles de retargeting detectados")

    # Ecommerce without reviews
    if ecommerce.get("upsell_opportunity"):
        alerts.append(f"💡 Oportunidad — {ecommerce.get('platform')} sin sistema de reviews (servicio extra a ofrecer)")

    return alerts


# ═══════════════════════════════════════════════════════════════════════════
#  FUNCIÓN PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════

def analyze_sales_triggers(url: str, tech_profile: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Extrae todos los disparadores de venta de una URL.
    Usa herramientas ligeras (requests, BeautifulSoup, DNS, WHOIS, SSL).
    No usa Playwright.

    Args:
        url:          URL base del dominio
        tech_profile: dict de tech_profile de Wappalyzer (si ya se ejecutó)

    Returns:
        dict con todas las secciones: infra, marketing, seo, outreach,
        legal_scale, ecommerce, alerts
    """
    domain = _domain_from_url(url)
    t0 = time.monotonic()

    # ── Fetch HTML home (único request pesado) ───────────────────────────
    resp = _get(url)
    html = resp.text if (resp and resp.ok) else ""
    soup = _soup(html) if html else BeautifulSoup("", "lxml")

    # ── Módulos paralelos (todos sobre el mismo HTML) ────────────────────
    infra       = _infra(domain, url)
    marketing   = _marketing(html, url)
    seo         = _seo(soup, url)
    outreach    = _outreach(html, soup)
    legal       = _legal_scale(url)
    ecommerce   = _ecommerce_reviews(html, soup, tech_profile)
    alerts      = _compute_alerts(infra, marketing, ecommerce)

    elapsed = round(time.monotonic() - t0, 2)
    print(f"[SalesTriggers] {domain} analizado en {elapsed}s — {len(alerts)} alertas")

    return {
        "infra":        infra,
        "marketing":    marketing,
        "seo":          seo,
        "outreach":     outreach,
        "legal_scale":  legal,
        "ecommerce":    ecommerce,
        "alerts":       alerts,
        "elapsed_s":    elapsed,
    }
