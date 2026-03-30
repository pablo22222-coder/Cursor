"""
SalesTriggers — Extracción completa de disparadores de venta.

Prioridad de herramientas (de menor a mayor coste de recursos):
  1. dnspython          → DNS / MX records (sin HTTP)
  2. python-whois       → WHOIS (sin HTTP)
  3. socket / ssl       → IP, hosting, SSL cert (sin HTTP adicional)
  4. requests + BS4     → HTML estático (sin JS)
  5. wappalyzergo       → Tech stack (subprocess, 30s timeout)
  (Playwright NO se usa en este módulo)

Todos los sub-módulos son independientes y resistentes a fallos.
Si algo no se puede obtener el campo queda en None/False/[].
"""
from __future__ import annotations

import concurrent.futures
import json
import re
import socket
import ssl
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# ── Timeouts ────────────────────────────────────────────────────────────────
HTTP_TIMEOUT       = 10   # requests.get por defecto
BLOG_HTTP_TIMEOUT  = 6    # requests al blog
SSL_TIMEOUT        = 8
WAPPALYZER_TIMEOUT = 30   # subprocess wappalyzergo
RDAP_TIMEOUT       = 4

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)


# ── Helpers básicos ──────────────────────────────────────────────────────────

def _get(url: str, timeout: int = HTTP_TIMEOUT) -> Optional[requests.Response]:
    try:
        return requests.get(
            url, timeout=timeout,
            headers={"User-Agent": _UA, "Accept-Language": "es-ES,es;q=0.9,en;q=0.8"},
            allow_redirects=True,
        )
    except Exception:
        return None


def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def _domain(url: str) -> str:
    parsed = urlparse(url)
    return (parsed.netloc or url).lstrip("www.")


# ═══════════════════════════════════════════════════════════════════════════
#  MÓDULO 0 — WAPPALYZER COMPLETO (CMS, Pagos, Analytics, UI, Chat)
# ═══════════════════════════════════════════════════════════════════════════

# Categorías ampliadas — incluye todo lo pedido
_WAP_CATEGORIES: Dict[str, List[str]] = {
    "cms": [
        "WordPress","Drupal","Joomla","Wix","Squarespace","Webflow",
        "Ghost","Contentful","Shopify","Prestashop","Magento","OpenCart",
        "BigCommerce","WooCommerce","Sitecore","Umbraco","Typo3",
    ],
    "payment": [
        "Stripe","PayPal","Klarna","Redsys","Bizum","Braintree",
        "Authorize.Net","Square","2Checkout","Mollie","Adyen",
        "Mercado Pago","PayU",
    ],
    "analytics": [
        "Google Analytics","Hotjar","Mixpanel","Segment","Amplitude",
        "Heap","Matomo","Clicky","Woopra","Piwik","Clarity",
        "FullStory","Lucky Orange",
    ],
    "ui_framework": [
        "Bootstrap","Tailwind CSS","Foundation","Bulma","Materialize",
        "Ant Design","Chakra UI","MUI","Semantic UI","jQuery UI",
    ],
    "chat_widget": [
        "Intercom","Zendesk","Drift","Crisp","Tidio","Tawk.to",
        "LiveChat","Freshdesk","HubSpot Chat","Olark","Userlike",
    ],
    "ecommerce": [
        "Shopify","WooCommerce","Magento","PrestaShop","BigCommerce",
        "OpenCart","Wix eCommerce","Squarespace Commerce",
    ],
    "crm": [
        "HubSpot","Salesforce","Zoho","Pipedrive","ActiveCampaign",
        "Freshsales","Monday","Copper",
    ],
    "email_marketing": [
        "Mailchimp","Klaviyo","ActiveCampaign","Brevo","ConvertKit",
        "GetResponse","SendGrid","Campaign Monitor","Drip","Omnisend",
    ],
}

def _categorize_tech(name: str) -> List[str]:
    """Devuelve qué categorías contienen esta tecnología."""
    n = name.lower()
    cats = []
    for cat, techs in _WAP_CATEGORIES.items():
        if any(t.lower() in n or n in t.lower() for t in techs):
            cats.append(cat)
    return cats


def _run_wappalyzer(url: str) -> Dict[str, Any]:
    """
    Ejecuta wappalyzergo con timeout de 30s.
    Devuelve categorías con lista de tecnologías detectadas.
    """
    base: Dict[str, Any] = {
        "available": False,
        "all_techs": [],
        "cms": [], "payment": [], "analytics": [],
        "ui_framework": [], "chat_widget": [],
        "ecommerce": [], "crm": [], "email_marketing": [],
        "raw": [],
    }
    try:
        proc = subprocess.run(
            ["wappalyzergo", "-url", url, "-json"],
            capture_output=True, text=True,
            timeout=WAPPALYZER_TIMEOUT,
        )
        if not proc.stdout.strip():
            return base

        data = json.loads(proc.stdout)
        if isinstance(data, list):
            techs = data
        elif isinstance(data, dict):
            techs = list(data.keys())
        else:
            return base

        base["available"] = True
        base["all_techs"] = techs[:20]
        base["raw"] = techs

        for t in techs:
            for cat in _categorize_tech(t):
                if t not in base[cat]:
                    base[cat].append(t)

    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError, Exception):
        pass

    return base


# ═══════════════════════════════════════════════════════════════════════════
#  MÓDULO 1 — INFRAESTRUCTURA (WHOIS / DNS / SSL / IP)
# ═══════════════════════════════════════════════════════════════════════════

def _infra(domain: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "domain_age_years":   None,
        "registered_date":    None,
        "registrar":          None,
        "mx_provider":        None,
        "mx_raw":             None,
        "ssl_valid":          None,
        "ssl_expires":        None,
        "ssl_days_remaining": None,
        "ssl_issuer":         None,
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
                for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%Y-%m-%dT%H:%M:%SZ"):
                    try:
                        creation = datetime.strptime(creation[:20], fmt); break
                    except Exception:
                        pass
            if hasattr(creation, 'tzinfo'):
                if creation.tzinfo is None:
                    creation = creation.replace(tzinfo=timezone.utc)
                result["registered_date"] = creation.strftime("%Y-%m-%d")
                age = (datetime.now(timezone.utc) - creation).days / 365.25
                result["domain_age_years"] = round(age, 1)
        if hasattr(w, 'registrar') and w.registrar:
            result["registrar"] = str(w.registrar)[:60]
    except Exception:
        pass

    # ── MX → email provider ───────────────────────────────────────────────
    try:
        import dns.resolver
        answers = dns.resolver.resolve(domain, "MX", lifetime=5)
        mx_list = sorted(answers, key=lambda r: r.preference)
        mx_hosts = [str(r.exchange).lower().rstrip(".") for r in mx_list]
        result["mx_raw"] = mx_hosts[:3]
        joined = " ".join(mx_hosts)
        if any("google" in m or "googlemail" in m for m in mx_hosts):
            result["mx_provider"] = "Google Workspace"
        elif any(k in joined for k in ["outlook", "microsoft", "protection.outlook"]):
            result["mx_provider"] = "Microsoft 365"
        elif any("zoho" in m for m in mx_hosts):
            result["mx_provider"] = "Zoho Mail"
        elif any("mimecast" in m for m in mx_hosts):
            result["mx_provider"] = "Mimecast"
        elif any("protonmail" in m or "proton" in m for m in mx_hosts):
            result["mx_provider"] = "ProtonMail"
        elif mx_hosts:
            result["mx_provider"] = mx_hosts[0]
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
            issuer = dict(x[0] for x in cert.get("issuer", []))
            result["ssl_issuer"] = issuer.get("organizationName", issuer.get("O", None))
    except Exception:
        pass

    # ── IP / Hosting ──────────────────────────────────────────────────────
    try:
        ip = socket.gethostbyname(domain)
        result["hosting_ip"] = ip
        _known = {
            "Amazon AWS":    ["16.","18.","52.","54.","3.","35."],
            "Cloudflare":    ["104.16.","104.17.","104.18.","104.19.","104.20.","104.21.",
                              "172.64.","172.65.","172.66.","172.67.","172.68.","172.69.",
                              "198.41."],
            "Google Cloud":  ["34.","35.","104.154.","104.196.","130.211."],
            "Microsoft Azure":["13.","20.","40.","52.174.","52.232."],
            "DigitalOcean":  ["104.236.","159.65.","178.62.","198.199."],
            "OVH":           ["51.","54.36.","91.121.","137.74."],
            "Hetzner":       ["5.9.","23.88.","49.12.","78.46.","88.99.","95.216."],
            "Vercel":        ["76.76.21.","76.223."],
            "Netlify":       ["75.2.","99.83."],
        }
        for provider, prefixes in _known.items():
            if any(ip.startswith(p) for p in prefixes):
                result["hosting_provider"] = provider
                break
        if not result["hosting_provider"]:
            # Fallback to RDAP
            try:
                rdap = requests.get(
                    f"https://rdap.arin.net/registry/ip/{ip}",
                    timeout=RDAP_TIMEOUT, headers={"User-Agent": _UA}
                )
                if rdap.ok:
                    data = rdap.json()
                    result["hosting_provider"] = data.get("name") or data.get("handle", "Desconocido")
            except Exception:
                pass
    except Exception:
        pass

    return result


# ═══════════════════════════════════════════════════════════════════════════
#  MÓDULO 2 — MARKETING SIGNALS (Píxeles, Lead Magnets, Soporte, Email Mkt)
# ═══════════════════════════════════════════════════════════════════════════

_PIXEL_RE = {
    "Meta Pixel":      re.compile(r"connect\.facebook\.net|fbq\s*\(|facebook\.com/tr\b|FB_PIXEL", re.I),
    "TikTok Pixel":    re.compile(r"analytics\.tiktok\.com|ttq\s*\(|tiktok\.com/i18n/pixel", re.I),
    "Google Ads":      re.compile(r"googleadservices\.com/pagead|AW-\d{7,}|google_conversion", re.I),
    "Google Tag Mgr":  re.compile(r"googletagmanager\.com/gtm\.js|GTM-[A-Z0-9]+", re.I),
    "LinkedIn Insight":re.compile(r"snap\.licdn\.com|linkedin\.com/px", re.I),
    "Pinterest":       re.compile(r"pintrk\s*\(|assets\.pinterest\.com", re.I),
}
_SUPPORT_RE = {
    "WhatsApp":   re.compile(r"wa\.me/\d+|api\.whatsapp\.com/send|whatsapp-button", re.I),
    "Zendesk":    re.compile(r"zendesk\.com|zopim\.com|zE\s*\(", re.I),
    "Intercom":   re.compile(r"widget\.intercom\.io|intercomSettings|Intercom\s*\(", re.I),
    "Tidio":      re.compile(r"code\.tidio\.co", re.I),
    "Tawk.to":    re.compile(r"embed\.tawk\.to|Tawk_API", re.I),
    "Crisp":      re.compile(r"client\.crisp\.chat", re.I),
    "Drift":      re.compile(r"js\.driftt\.com", re.I),
    "LiveChat":   re.compile(r"livechatinc\.com|__lc\.license", re.I),
}
_EMAIL_MKT_RE = {
    "Mailchimp":       re.compile(r"mailchimp\.com|list-manage\.com|mc\.js", re.I),
    "Klaviyo":         re.compile(r"klaviyo\.com|_learnq\s*\(|klaviyoForms", re.I),
    "ActiveCampaign":  re.compile(r"activehosted\.com|trackcmp\.net", re.I),
    "Brevo":           re.compile(r"brevo\.com|sendinblue\.com", re.I),
    "ConvertKit":      re.compile(r"convertkit\.com|ck\.js", re.I),
    "HubSpot Email":   re.compile(r"js\.hs-scripts\.com|hbspt\s*\.", re.I),
    "Drip":            re.compile(r"getdrip\.com|_dcq\s*=", re.I),
}
_POPUP_RE = re.compile(
    r"optinmonster|privy\.com|popupsmart|sumo\.com|wishpond|hellobar|"
    r"wheelio|spin-a-sale|picreel|poptin|popup-maker|icegram", re.I
)
_LEAD_KW = [
    "suscribirse", "suscríbete", "subscribe", "newsletter", "descarga gratis",
    "free download", "ebook", "guía gratis", "regístrate", "sign up",
    "obtén gratis", "descargar", "get started", "acceso gratuito",
]


def _marketing(html: str, url: str, soup: BeautifulSoup) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "pixels":          {},    # {name: True/False}
        "missing_pixels":  [],    # píxeles no detectados (para alerta)
        "support_widgets": [],
        "email_marketing": [],
        "has_popups":      False,
        "lead_magnets":    [],    # lista de URLs o keywords
        "forms_found":     0,
    }
    html_l = html.lower()

    # ── Píxeles ───────────────────────────────────────────────────────────
    for name, pat in _PIXEL_RE.items():
        detected = bool(pat.search(html))
        result["pixels"][name] = detected
        if not detected:
            result["missing_pixels"].append(name)

    # ── Support widgets ───────────────────────────────────────────────────
    for name, pat in _SUPPORT_RE.items():
        if pat.search(html):
            result["support_widgets"].append(name)

    # ── Email marketing ───────────────────────────────────────────────────
    for name, pat in _EMAIL_MKT_RE.items():
        if pat.search(html):
            result["email_marketing"].append(name)

    # ── Popups ────────────────────────────────────────────────────────────
    result["has_popups"] = bool(_POPUP_RE.search(html))

    # ── Lead magnets — forms + keywords ──────────────────────────────────
    forms = soup.find_all("form")
    result["forms_found"] = len(forms)
    magnets: List[str] = []

    # Form actions as lead magnet links
    for form in forms:
        action = form.get("action", "")
        if action and action not in ("#", ""):
            full = urljoin(url, action) if not action.startswith("http") else action
            if full not in magnets:
                magnets.append(full)

    # Keyword links in the page
    for kw in _LEAD_KW:
        if kw in html_l:
            for a in soup.find_all("a", href=True):
                text = (a.get_text() or "").lower()
                if kw in text or any(kw in (a.get("href") or "").lower() for _ in [1]):
                    href = a["href"]
                    full = urljoin(url, href) if not href.startswith("http") else href
                    if full not in magnets and not full.endswith(("#", "javascript:void(0)")):
                        magnets.append(full)
            if not magnets:
                magnets.append(f"keyword: {kw}")

    result["lead_magnets"] = magnets[:5]
    return result


# ═══════════════════════════════════════════════════════════════════════════
#  MÓDULO 3 — SEO & CONTENIDO
# ═══════════════════════════════════════════════════════════════════════════

_BLOG_PATHS = ["/blog", "/noticias", "/news", "/articulos", "/posts",
               "/actualidad", "/recursos", "/insights", "/journal"]
_DATE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}|"          # ISO
    r"\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|"  # dd/mm/yyyy
    r"\d{1,2}\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
    r"septiembre|octubre|noviembre|diciembre|"
    r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{2,4})",
    re.I
)


def _seo(soup: BeautifulSoup, url: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "h1":                  None,
        "h1_all":              [],
        "meta_title":          None,
        "meta_description":    None,
        "missing_title":       True,
        "missing_description": True,
        "canonical":           None,
        "og_title":            None,
        "og_description":      None,
        "blog_url":            None,
        "last_post_date":      None,
        "last_post_url":       None,
        "last_post_title":     None,
    }

    # H1 (all + first)
    h1_tags = soup.find_all("h1")
    if h1_tags:
        result["h1"] = h1_tags[0].get_text(strip=True)[:150]
        result["h1_all"] = [h.get_text(strip=True)[:80] for h in h1_tags[:3]]

    # Title
    title = soup.find("title")
    if title and title.get_text(strip=True):
        result["meta_title"] = title.get_text(strip=True)[:150]
        result["missing_title"] = False

    # Meta description
    for attr in [{"name": re.compile(r"^description$", re.I)},
                 {"property": "og:description"}]:
        tag = soup.find("meta", attrs=attr)
        if tag and tag.get("content", "").strip():
            result["meta_description"] = tag["content"].strip()[:250]
            result["missing_description"] = False
            break

    # Canonical
    canon = soup.find("link", rel="canonical")
    if canon:
        result["canonical"] = canon.get("href")

    # OG tags
    og_t = soup.find("meta", property="og:title")
    if og_t: result["og_title"] = (og_t.get("content") or "")[:150]
    og_d = soup.find("meta", property="og:description")
    if og_d: result["og_description"] = (og_d.get("content") or "")[:250]

    # Blog detection
    for path in _BLOG_PATHS:
        resp = _get(urljoin(url, path), timeout=BLOG_HTTP_TIMEOUT)
        if resp and resp.ok and len(resp.text) > 300:
            result["blog_url"] = urljoin(url, path)
            bsoup = _soup(resp.text)

            # Look for article/post links with dates
            articles = bsoup.find_all(["article", "div"], limit=30)
            for art in articles:
                date_match = _DATE_RE.search(art.get_text())
                if date_match:
                    result["last_post_date"] = date_match.group(1)
                    a_tag = art.find("a", href=True)
                    if a_tag:
                        href = a_tag["href"]
                        result["last_post_url"] = urljoin(url, href) if not href.startswith("http") else href
                        result["last_post_title"] = a_tag.get_text(strip=True)[:100]
                    break

            # Also try <time> tags
            if not result["last_post_date"]:
                time_tag = bsoup.find("time")
                if time_tag:
                    result["last_post_date"] = (
                        time_tag.get("datetime") or time_tag.get_text(strip=True)
                    )[:20]
            break

    return result


# ═══════════════════════════════════════════════════════════════════════════
#  MÓDULO 4 — OUTREACH (Redes Sociales + Idioma)
# ═══════════════════════════════════════════════════════════════════════════

_SOCIAL_RE = {
    "LinkedIn":  re.compile(r'href=["\']https?://(?:www\.)?linkedin\.com/(?:company|in|school)/([^/"\'?\s]+)', re.I),
    "Instagram": re.compile(r'href=["\']https?://(?:www\.)?instagram\.com/([^/"\'?\s]+)', re.I),
    "Facebook":  re.compile(r'href=["\']https?://(?:www\.)?facebook\.com/([^/"\'?\s]+)', re.I),
    "Twitter/X": re.compile(r'href=["\']https?://(?:www\.)?(?:twitter|x)\.com/([^/"\'?\s]+)', re.I),
    "YouTube":   re.compile(r'href=["\']https?://(?:www\.)?youtube\.com/(?:c/|channel/|@)?([^/"\'?\s]+)', re.I),
    "TikTok":    re.compile(r'href=["\']https?://(?:www\.)?tiktok\.com/@([^/"\'?\s]+)', re.I),
}
_SOCIAL_SKIP = re.compile(
    r"share|sharer|intent/tweet|intent/post|shareArticle|"
    r"share\?|sharing|share/|/share|/like|/reaction", re.I
)


def _outreach(html: str, soup: BeautifulSoup) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "language":     None,
        "social_links": {},
    }

    # Language
    html_tag = soup.find("html")
    if html_tag:
        lang = (html_tag.get("lang") or "").split("-")[0].lower().strip()
        result["language"] = lang or None
    # Fallback: meta content-language
    if not result["language"]:
        cl = soup.find("meta", attrs={"http-equiv": re.compile(r"content-language", re.I)})
        if cl:
            result["language"] = (cl.get("content") or "").split("-")[0].lower()

    # Social links — scan full HTML then prioritise footer
    footer = soup.find("footer")
    scan_html = str(footer) if footer else html

    for platform, pat in _SOCIAL_RE.items():
        matches = pat.findall(scan_html)
        for handle in matches:
            if _SOCIAL_SKIP.search(handle):
                continue
            if platform == "LinkedIn":
                link = f"https://linkedin.com/company/{handle}"
            elif platform == "Instagram":
                link = f"https://instagram.com/{handle}"
            elif platform == "Facebook":
                link = f"https://facebook.com/{handle}"
            elif platform in ("Twitter/X",):
                link = f"https://x.com/{handle}"
            elif platform == "YouTube":
                link = f"https://youtube.com/{handle}"
            elif platform == "TikTok":
                link = f"https://tiktok.com/@{handle}"
            else:
                link = handle
            result["social_links"][platform] = link
            break

    # If footer didn't yield results, scan full page as fallback
    if not result["social_links"] and footer:
        for platform, pat in _SOCIAL_RE.items():
            matches = pat.findall(html)
            for handle in matches:
                if _SOCIAL_SKIP.search(handle):
                    continue
                if platform not in result["social_links"]:
                    result["social_links"][platform] = f"https://{platform.lower().split('/')[0]}.com/{handle}"
                break

    return result


# ═══════════════════════════════════════════════════════════════════════════
#  MÓDULO 5 — LEGAL & ESCALA (Sitemap + ads.txt)
# ═══════════════════════════════════════════════════════════════════════════

def _legal_scale(url: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "sitemap_url_count": None,
        "sitemap_url":       None,
        "has_ads_txt":       False,
        "ads_txt_url":       None,
        "robots_txt":        False,
    }

    # Sitemap
    for path in ["/sitemap.xml", "/sitemap_index.xml", "/sitemap/", "/wp-sitemap.xml"]:
        full = urljoin(url, path)
        resp = _get(full, timeout=8)
        if resp and resp.ok:
            ct = resp.headers.get("Content-Type", "")
            if "xml" in ct or resp.text.strip().startswith("<"):
                urls = re.findall(r"<loc>([^<]+)</loc>", resp.text)
                if urls:
                    result["sitemap_url_count"] = len(urls)
                    result["sitemap_url"] = full
                    break

    # ads.txt
    full_ads = urljoin(url, "/ads.txt")
    resp_ads = _get(full_ads, timeout=5)
    if resp_ads and resp_ads.ok and len(resp_ads.text) > 10:
        result["has_ads_txt"] = True
        result["ads_txt_url"] = full_ads

    # robots.txt
    resp_robots = _get(urljoin(url, "/robots.txt"), timeout=5)
    result["robots_txt"] = bool(resp_robots and resp_robots.ok and len(resp_robots.text) > 5)

    return result


# ═══════════════════════════════════════════════════════════════════════════
#  MÓDULO 6 — E-COMMERCE AVANZADO (Reviews)
# ═══════════════════════════════════════════════════════════════════════════

_REVIEW_PLATFORM_RE = {
    "Trustpilot":   re.compile(r"trustpilot\.com|widget\.trustpilot", re.I),
    "Yotpo":        re.compile(r"yotpo\.com|staticw2\.yotpo|yotpo-widget", re.I),
    "Judge.me":     re.compile(r"judge\.me|judgeme|jdgm", re.I),
    "Stamped.io":   re.compile(r"stamped\.io|stampedio", re.I),
    "Loox":         re.compile(r"loox\.io|loox-widget", re.I),
    "Okendo":       re.compile(r"okendo\.io", re.I),
    "Reviews.io":   re.compile(r"reviews\.io|reviewswidget", re.I),
    "Schema Review":re.compile(r'"@type"\s*:\s*"Review"', re.I),
}
_ECOM_PLATFORM_RE = {
    "Shopify":    re.compile(r"cdn\.shopify\.com|Shopify\.theme|myshopify\.com", re.I),
    "WooCommerce":re.compile(r"woocommerce|wc-product|add-to-cart.*woocommerce", re.I),
    "Magento":    re.compile(r"mage/cookies|Magento_|mage\.cookies", re.I),
    "PrestaShop": re.compile(r"prestashop|blockcart", re.I),
    "BigCommerce":re.compile(r"bigcommerce|bc-sf-filter", re.I),
}


def _ecommerce_reviews(html: str, soup: BeautifulSoup,
                       wap_profile: Optional[Dict]) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "is_ecommerce":       False,
        "platform":           None,
        "has_reviews":        False,
        "review_platform":    None,
        "sample_review":      None,
        "sample_rating":      None,
        "upsell_opportunity": False,
    }

    # Detect ecommerce platform: Wappalyzer first, then regex
    wap_ecom = (wap_profile or {}).get("ecommerce", [])
    if wap_ecom:
        result["is_ecommerce"] = True
        result["platform"] = wap_ecom[0]
    else:
        for plat, pat in _ECOM_PLATFORM_RE.items():
            if pat.search(html):
                result["is_ecommerce"] = True
                result["platform"] = plat
                break

    if not result["is_ecommerce"]:
        return result

    # Check for reviews
    for platform, pat in _REVIEW_PLATFORM_RE.items():
        if pat.search(html):
            result["has_reviews"] = True
            result["review_platform"] = platform
            break

    if not result["has_reviews"]:
        result["upsell_opportunity"] = True

    # Extract sample review from JSON-LD
    if result["has_reviews"]:
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                nodes = data if isinstance(data, list) else [data]
                for node in nodes:
                    revs = []
                    if isinstance(node, dict):
                        if node.get("@type") == "Review":
                            revs = [node]
                        elif "review" in node:
                            rv = node["review"]
                            revs = rv if isinstance(rv, list) else [rv]
                    for rev in revs:
                        body = rev.get("reviewBody") or rev.get("description") or ""
                        if body:
                            result["sample_review"] = body[:250]
                            rating = (rev.get("reviewRating") or {})
                            result["sample_rating"] = rating.get("ratingValue")
                            break
                if result["sample_review"]:
                    break
            except Exception:
                pass

    return result


# ═══════════════════════════════════════════════════════════════════════════
#  ALERTAS
# ═══════════════════════════════════════════════════════════════════════════

def _alerts(infra: Dict, marketing: Dict, ecommerce: Dict) -> List[str]:
    alerts: List[str] = []

    # SSL
    days = infra.get("ssl_days_remaining")
    if days is not None:
        if days <= 0:
            alerts.append("🔴 Prioridad de Contacto: ALTA — SSL expirado")
        elif days <= 14:
            alerts.append(f"🔴 Prioridad de Contacto: ALTA — SSL expira en {days} días")
        elif days <= 30:
            alerts.append(f"🟠 Prioridad de Contacto: ALTA — SSL expira pronto ({days} días)")
    elif infra.get("ssl_valid") is False:
        alerts.append("🔴 Prioridad de Contacto: ALTA — SSL inválido o ausente")

    # Píxeles faltantes
    missing = marketing.get("missing_pixels", [])
    key_missing = [p for p in missing if p in ("Meta Pixel", "Google Tag Mgr", "Google Ads")]
    if len(key_missing) == 3:
        alerts.append("🟡 Prioridad de Contacto: ALTA — Sin ningún píxel de retargeting")
    elif key_missing:
        alerts.append(f"🟡 Prioridad de Contacto: ALTA — Sin píxeles: {', '.join(key_missing)}")

    # Ecommerce sin reviews
    if ecommerce.get("upsell_opportunity"):
        plat = ecommerce.get("platform", "Ecommerce")
        alerts.append(f"💡 Oportunidad — {plat} sin sistema de reviews (servicio extra que puedes ofrecer)")

    # SEO gaps — se añaden en la función principal
    return alerts


# ═══════════════════════════════════════════════════════════════════════════
#  FUNCIÓN PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════

def analyze_sales_triggers(url: str, tech_profile: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Extrae todos los disparadores de venta de una URL.

    Prioriza herramientas ligeras (DNS, WHOIS, SSL, requests+BS4, wappalyzergo).
    NO usa Playwright.

    Args:
        url:          URL base del dominio
        tech_profile: tech_profile de Wappalyzer del pipeline (si ya se ejecutó
                      como Fase 2). Si se proporciona, se usa para categorías
                      en lugar de volver a ejecutar wappalyzergo.
    Returns:
        dict con todas las secciones + alerts
    """
    domain = _domain(url)
    t0 = time.monotonic()

    # ── Fetch home HTML (único request principal) ────────────────────────
    resp = _get(url)
    html = resp.text if (resp and resp.ok) else ""
    soup = _soup(html)

    # ── Wappalyzer (solo si no tenemos tech_profile del pipeline) ─────────
    if tech_profile and tech_profile.get("all_techs"):
        # Reuse and re-categorize from existing profile
        wap = {
            "available":      True,
            "all_techs":      tech_profile.get("all_techs", []),
            "cms":            tech_profile.get("cms", []),
            "payment":        [],
            "analytics":      tech_profile.get("analytics", []),
            "ui_framework":   [],
            "chat_widget":    tech_profile.get("chat", []),
            "ecommerce":      tech_profile.get("ecommerce", []),
            "crm":            tech_profile.get("crm", []),
            "email_marketing":tech_profile.get("email", []),
            "raw":            tech_profile.get("all_techs", []),
        }
        # Fill payment and ui_framework by re-categorizing
        for t in wap["all_techs"]:
            for cat in _categorize_tech(t):
                if cat in ("payment", "ui_framework") and t not in wap[cat]:
                    wap[cat].append(t)
    else:
        wap = _run_wappalyzer(url)

    # ── Run all modules (concurrently where safe) ────────────────────────
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        f_infra  = ex.submit(_infra, domain)
        f_legal  = ex.submit(_legal_scale, url)
        # marketing, seo, outreach need html/soup — run after fetch
        f_mkt    = ex.submit(_marketing, html, url, soup)
        f_seo    = ex.submit(_seo, soup, url)

    infra   = f_infra.result()
    legal   = f_legal.result()
    mkt     = f_mkt.result()
    seo     = f_seo.result()
    out     = _outreach(html, soup)
    ecom    = _ecommerce_reviews(html, soup, wap)

    # SEO alerts
    seo_alerts: List[str] = []
    if seo.get("missing_title"):
        seo_alerts.append("⚠️ Falta meta title (SEO)")
    if seo.get("missing_description"):
        seo_alerts.append("⚠️ Falta meta description (SEO)")

    alert_list = _alerts(infra, mkt, ecom) + seo_alerts

    elapsed = round(time.monotonic() - t0, 2)
    print(f"[SalesTriggers] {domain} — {elapsed}s — {len(alert_list)} alertas")

    return {
        "wappalyzer":   wap,
        "infra":        infra,
        "marketing":    mkt,
        "seo":          seo,
        "outreach":     out,
        "legal_scale":  legal,
        "ecommerce":    ecom,
        "alerts":       alert_list,
        "elapsed_s":    elapsed,
    }
