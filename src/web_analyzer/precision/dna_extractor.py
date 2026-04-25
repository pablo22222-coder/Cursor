"""
DNA Extractor — Inspección profunda del HTML para detectar tecnologías
mediante huellas físicas que Wappalyzer suele ignorar.

Independiente de cualquier base de datos: se basa exclusivamente en la
extracción de patrones del DOM y del texto inline.

6 dimensiones:
  1. Scripts & assets externos (atributo src de <script>)
  2. Iframes embebidos (src de <iframe>)
  3. Variables globales / inicializadores (texto inline de <script>)
  4. Firmas en comentarios HTML (<!-- ... -->)
  5. Destinos de formularios (action de <form>, fallback data-*)
  6. Perfiles sociales (<a href> de redes sociales, sin enlaces de "share")

Modo "match dirigido":
  - Si target_techs == ["ALL"] o vacío → reporta TODOS los hallazgos.
  - Si target_techs es una lista concreta → solo reporta evidencias que
    coincidan (case-insensitive) con esos nombres.

Salida: dict estructurado con `evidence_found` (filtrado), `social_profiles`,
y `raw_footprint` (todos los dominios de terceros únicos).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urlparse

from bs4 import BeautifulSoup


# ─────────────────────────────────────────────────────────────────────
#  Constantes
# ─────────────────────────────────────────────────────────────────────

SOCIAL_DOMAINS = {
    "instagram.com", "facebook.com", "linkedin.com",
    "twitter.com", "x.com", "youtube.com", "tiktok.com",
}

# URLs de "share" o "intent" que NO son perfiles oficiales.
_SHARE_PATTERNS = (
    "share?", "/share/", "share=", "sharer.php", "/intent/",
    "intent/tweet", "intent=tweet", "/dialog/share", "/sharer/",
)

# Patrones inline JS que delatan SDKs o trackers cuando se inicializan.
_INLINE_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("dataLayer",            re.compile(r"\b(window\.)?dataLayer\s*=", re.IGNORECASE)),
    ("gtag",                 re.compile(r"\bgtag\s*\(", re.IGNORECASE)),
    ("fbq",                  re.compile(r"\bfbq\s*\(", re.IGNORECASE)),
    ("_hsq (HubSpot)",       re.compile(r"\b_hsq\s*\.?\s*push", re.IGNORECASE)),
    ("hj (Hotjar)",          re.compile(r"\bhj\s*\(", re.IGNORECASE)),
    ("ga()",                 re.compile(r"\bga\s*\(\s*['\"]create['\"]", re.IGNORECASE)),
    ("Google Tag Manager",   re.compile(r"GTM-[A-Z0-9]+", re.IGNORECASE)),
    ("Klaviyo (_learnq)",    re.compile(r"\b_learnq\b", re.IGNORECASE)),
    ("Intercom",             re.compile(r"\bIntercom\s*\(", re.IGNORECASE)),
    ("Drift",                re.compile(r"\bdrift\.\w+\s*\(", re.IGNORECASE)),
    ("Segment (analytics.js)",re.compile(r"\banalytics\.load\s*\(", re.IGNORECASE)),
    ("Mixpanel",             re.compile(r"\bmixpanel\.\w+\s*\(", re.IGNORECASE)),
    ("Stripe (Stripe())",    re.compile(r"\bStripe\s*\(\s*['\"]pk_", re.IGNORECASE)),
    ("Shopify",              re.compile(r"\bShopify\.\w+", re.IGNORECASE)),
    ("WordPress wp-",        re.compile(r"\bwp[-_](?:emoji|content|includes|admin)\b", re.IGNORECASE)),
    ("Tidio",                re.compile(r"\bTidio[A-Za-z]*\b", re.IGNORECASE)),
    ("Crisp",                re.compile(r"\b\$crisp\b", re.IGNORECASE)),
    ("LinkedIn Insight",     re.compile(r"\b_linkedin_partner_id\b", re.IGNORECASE)),
    ("TikTok Pixel (ttq)",   re.compile(r"\bttq\.\w+\s*\(", re.IGNORECASE)),
    ("Pinterest tag",        re.compile(r"\bpintrk\s*\(", re.IGNORECASE)),
    ("Microsoft Clarity",    re.compile(r"\bclarity\s*\(", re.IGNORECASE)),
)

# Firmas típicas en comentarios HTML.
_COMMENT_SIGNATURES: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("Yoast SEO",            re.compile(r"\bYoast\s*SEO\b", re.IGNORECASE)),
    ("RankMath",             re.compile(r"\bRank[\s-]?Math\b", re.IGNORECASE)),
    ("Elementor",            re.compile(r"\bElementor(?:\s*Pro)?\b", re.IGNORECASE)),
    ("WPBakery",             re.compile(r"\bWPBakery\b", re.IGNORECASE)),
    ("WP Rocket",            re.compile(r"\bWP[\s-]?Rocket\b", re.IGNORECASE)),
    ("WordPress",            re.compile(r"\bWordPress\b", re.IGNORECASE)),
    ("Joomla",               re.compile(r"\bJoomla\b", re.IGNORECASE)),
    ("Drupal",               re.compile(r"\bDrupal\b", re.IGNORECASE)),
    ("Shopify",              re.compile(r"\bShopify\b", re.IGNORECASE)),
    ("Wix",                  re.compile(r"\bWix\.com\b", re.IGNORECASE)),
    ("Squarespace",          re.compile(r"\bSquarespace\b", re.IGNORECASE)),
    ("HubSpot",              re.compile(r"\bHubSpot\b", re.IGNORECASE)),
    ("Mailchimp",            re.compile(r"\bMailchimp\b", re.IGNORECASE)),
    ("Klaviyo",              re.compile(r"\bKlaviyo\b", re.IGNORECASE)),
    ("Stripe",               re.compile(r"\bStripe\b", re.IGNORECASE)),
    ("PayPal",               re.compile(r"\bPayPal\b", re.IGNORECASE)),
    ("Google Tag Manager",   re.compile(r"\bGoogle\s+Tag\s+Manager\b", re.IGNORECASE)),
    ("Google Analytics",     re.compile(r"\bGoogle\s+Analytics\b|\bgtag\.js\b", re.IGNORECASE)),
)

# Mapping de dominios de terceros conocidos → tecnología canónica
_DOMAIN_TO_TECH: Dict[str, str] = {
    # Mailchimp
    "list-manage.com": "Mailchimp", "chimpstatic.com": "Mailchimp",
    "mailchimp.com": "Mailchimp",
    # Klaviyo
    "klaviyo.com": "Klaviyo", "static.klaviyo.com": "Klaviyo",
    # HubSpot
    "hubspot.com": "HubSpot", "hs-scripts.com": "HubSpot",
    "hs-banner.com": "HubSpot", "hsforms.net": "HubSpot",
    "hs-analytics.net": "HubSpot",
    # Stripe / PayPal / payments
    "stripe.com": "Stripe", "js.stripe.com": "Stripe",
    "paypal.com": "PayPal", "paypalobjects.com": "PayPal",
    # Calendly / Zapier
    "calendly.com": "Calendly", "hooks.zapier.com": "Zapier",
    # Google
    "googletagmanager.com": "Google Tag Manager",
    "google-analytics.com": "Google Analytics",
    "googleadservices.com": "Google Ads",
    "doubleclick.net": "Google Ads (DoubleClick)",
    # Facebook / Meta
    "facebook.net": "Facebook Pixel", "connect.facebook.net": "Facebook Pixel",
    # Hotjar / Mixpanel / Segment / Amplitude
    "hotjar.com": "Hotjar",
    "mixpanel.com": "Mixpanel", "cdn.mxpnl.com": "Mixpanel",
    "segment.com": "Segment", "segment.io": "Segment",
    "amplitude.com": "Amplitude",
    # Chats
    "intercom.io": "Intercom", "intercomcdn.com": "Intercom",
    "drift.com": "Drift", "driftt.com": "Drift",
    "crisp.chat": "Crisp", "crisp.im": "Crisp",
    "tidio.co": "Tidio",
    "zendesk.com": "Zendesk", "zdassets.com": "Zendesk",
    # CDN / hosting
    "cloudflare.com": "Cloudflare", "cdn.cloudflare.com": "Cloudflare",
    "vercel.app": "Vercel", "netlify.app": "Netlify",
    # Shopify ecosystem
    "shopify.com": "Shopify", "shopifycdn.com": "Shopify",
    "myshopify.com": "Shopify",
    # WordPress
    "wp.com": "WordPress.com", "wordpress.com": "WordPress.com",
    # ActiveCampaign / Brevo / ConvertKit
    "activecampaign.com": "ActiveCampaign",
    "brevo.com": "Brevo", "sendinblue.com": "Brevo",
    "convertkit.com": "ConvertKit",
    # Recaptcha
    "recaptcha.net": "reCAPTCHA", "google.com/recaptcha": "reCAPTCHA",
    # TikTok / LinkedIn / Pinterest
    "tiktok.com": "TikTok",
    "ads-twitter.com": "Twitter Ads",
    "static.ads-twitter.com": "Twitter Ads",
    "snap.licdn.com": "LinkedIn Insight",
    "px.ads.linkedin.com": "LinkedIn Insight",
    "ct.pinterest.com": "Pinterest Tag",
}


# ─────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────

def _root_domain(url_or_host: str) -> str:
    """Devuelve el dominio raíz limpio (sin esquema, sin path, sin www, lower)."""
    if not url_or_host:
        return ""
    s = url_or_host.strip()
    if "://" in s:
        try:
            s = urlparse(s).netloc or s
        except Exception:
            pass
    s = s.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    s = s.lower()
    if s.startswith("www."):
        s = s[4:]
    # Limpiar puerto
    if ":" in s:
        s = s.split(":", 1)[0]
    # Quitar parámetros tipo ?ver=
    s = s.split(";", 1)[0]
    return s.strip()


def _is_same_origin(host: str, base_domain: str) -> bool:
    """True si host pertenece al mismo dominio base que el sitio analizado."""
    if not host or not base_domain:
        return False
    host = host.lower()
    base_domain = base_domain.lower()
    return host == base_domain or host.endswith("." + base_domain)


def _normalize_target(t: str) -> str:
    return (t or "").strip().lower()


def _matches_target(text: str, target: str) -> bool:
    """Match case-insensitive — substring."""
    if not target:
        return False
    return target.lower() in (text or "").lower()


def _tech_name_for_domain(host: str) -> Optional[str]:
    """Si `host` (o un sufijo) está en _DOMAIN_TO_TECH, devuelve la tech."""
    if not host:
        return None
    host = host.lower()
    if host in _DOMAIN_TO_TECH:
        return _DOMAIN_TO_TECH[host]
    # Comprobar sufijos: "static.hotjar.com" → "hotjar.com"
    for known, tech in _DOMAIN_TO_TECH.items():
        if host.endswith("." + known) or host == known:
            return tech
    return None


# ─────────────────────────────────────────────────────────────────────
#  Extracción por dimensión
# ─────────────────────────────────────────────────────────────────────

def _scan_scripts(soup: BeautifulSoup, base_domain: str) -> List[Dict[str, str]]:
    """Dim 1: src de <script>. Devuelve evidencias con host raíz + URL completa."""
    out: List[Dict[str, str]] = []
    seen: Set[str] = set()
    try:
        for tag in soup.find_all("script"):
            src = tag.get("src")
            if not src:
                continue
            src = str(src).strip()
            host = _root_domain(src)
            if not host or _is_same_origin(host, base_domain):
                continue
            key = src.split("?", 1)[0]
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "host": host,
                "url": src,
                "tech": _tech_name_for_domain(host) or "",
            })
    except Exception:
        pass
    return out


def _scan_iframes(soup: BeautifulSoup, base_domain: str) -> List[Dict[str, str]]:
    """Dim 2: src de <iframe>."""
    out: List[Dict[str, str]] = []
    seen: Set[str] = set()
    try:
        for tag in soup.find_all("iframe"):
            src = tag.get("src")
            if not src:
                continue
            src = str(src).strip()
            host = _root_domain(src)
            if not host or _is_same_origin(host, base_domain):
                continue
            key = src.split("?", 1)[0]
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "host": host,
                "url": src,
                "tech": _tech_name_for_domain(host) or "",
            })
    except Exception:
        pass
    return out


def _scan_inline_js(soup: BeautifulSoup) -> List[Dict[str, str]]:
    """Dim 3: variables globales e inicializadores en <script> sin src."""
    out: List[Dict[str, str]] = []
    seen: Set[str] = set()
    try:
        for tag in soup.find_all("script"):
            if tag.get("src"):
                continue
            text = tag.string or tag.get_text() or ""
            if not text or len(text) > 80_000:  # Cap defensivo por bloque
                # Aún si es enorme, mirar primeros 80k caracteres por seguridad.
                text = text[:80_000]
            for label, pattern in _INLINE_PATTERNS:
                m = pattern.search(text)
                if not m:
                    continue
                snippet = text[max(0, m.start() - 20): m.start() + 120].strip()
                key = (label, snippet[:60])
                if key in seen:
                    continue
                seen.add(key)
                out.append({
                    "global": label,
                    "snippet": snippet,
                })
    except Exception:
        pass
    return out


def _scan_html_comments(html: str) -> List[Dict[str, str]]:
    """Dim 4: firmas en comentarios HTML."""
    out: List[Dict[str, str]] = []
    seen: Set[str] = set()
    try:
        comments = re.findall(r"<!--(.*?)-->", html, flags=re.DOTALL)
    except Exception:
        comments = []
    for c in comments:
        snippet = (c or "").strip()
        if not snippet or len(snippet) > 500:
            snippet = snippet[:500]
        for label, pattern in _COMMENT_SIGNATURES:
            if pattern.search(snippet):
                key = (label, snippet[:80])
                if key in seen:
                    continue
                seen.add(key)
                out.append({
                    "tech": label,
                    "snippet": snippet,
                })
    return out


def _scan_form_actions(soup: BeautifulSoup, base_domain: str) -> List[Dict[str, str]]:
    """Dim 5: action de <form> (con fallback a data-* atributos)."""
    out: List[Dict[str, str]] = []
    seen: Set[str] = set()
    try:
        for form in soup.find_all("form"):
            action = form.get("action") or ""
            if not action:
                # Fallback a data-* atributos
                for attr_name, attr_val in (form.attrs or {}).items():
                    if not attr_name.startswith("data-"):
                        continue
                    val = attr_val if isinstance(attr_val, str) else " ".join(
                        attr_val if isinstance(attr_val, list) else []
                    )
                    if isinstance(val, str) and ("://" in val):
                        action = val
                        break
            action = str(action).strip()
            if not action or "://" not in action:
                continue
            host = _root_domain(action)
            if not host or _is_same_origin(host, base_domain):
                continue
            key = action.split("?", 1)[0]
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "host": host,
                "action": action,
                "tech": _tech_name_for_domain(host) or "",
            })
    except Exception:
        pass
    return out


def _scan_social_profiles(soup: BeautifulSoup) -> List[Dict[str, str]]:
    """Dim 6: <a href> a redes sociales (perfiles, no links de share)."""
    out: List[Dict[str, str]] = []
    seen: Set[str] = set()
    try:
        for a in soup.find_all("a"):
            href = a.get("href") or ""
            if not href:
                continue
            href = str(href).strip()
            host = _root_domain(href)
            if not host:
                continue
            # ¿Es una red social oficial?
            social_match = None
            for social in SOCIAL_DOMAINS:
                if host == social or host.endswith("." + social):
                    social_match = social
                    break
            if not social_match:
                continue
            low = href.lower()
            if any(p in low for p in _SHARE_PATTERNS):
                continue
            # Path no vacío y no es la home pelada
            try:
                parsed = urlparse(href)
                path = (parsed.path or "/").strip("/")
            except Exception:
                path = ""
            if not path:
                # /home pelada de la red social → no es perfil
                continue
            if href in seen:
                continue
            seen.add(href)
            out.append({
                "platform": social_match.replace(".com", ""),
                "url": href,
            })
    except Exception:
        pass
    return out


# ─────────────────────────────────────────────────────────────────────
#  API pública
# ─────────────────────────────────────────────────────────────────────

def run_dna(
    html: str,
    base_url: str,
    *,
    target_techs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Ejecuta el escáner ADN sobre el HTML descargado.

    Args:
        html: HTML completo (string).
        base_url: URL del sitio analizado (se usa para detectar same-origin).
        target_techs: Lista de tecnologías objetivo. Si está vacía o
            contiene "ALL" se reporta todo.

    Returns:
        dict con la siguiente forma::
            {
              "dna_status": "success" | "skipped" | "error",
              "evidence_found": {
                  "scripts":   [...],
                  "iframes":   [...],
                  "globals":   [...],
                  "comments":  [...],
                  "forms":     [...],
              },
              "social_profiles": [...],
              "raw_footprint": [hosts únicos],
              "matched_targets": {tech: [evidencias asociadas]}  # solo en match dirigido
            }
    """
    base_domain = _root_domain(base_url)
    targets_norm: List[str] = []
    report_all = False
    if not target_techs:
        report_all = True
    else:
        normalized = [_normalize_target(t) for t in target_techs if t]
        if any(t == "all" for t in normalized):
            report_all = True
        else:
            targets_norm = [t for t in normalized if t]
            if not targets_norm:
                report_all = True

    if not html:
        return {
            "dna_status": "skipped",
            "reason": "empty_html",
            "evidence_found": {"scripts": [], "iframes": [], "globals": [],
                                "comments": [], "forms": []},
            "social_profiles": [],
            "raw_footprint": [],
            "matched_targets": {},
        }

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as exc:
            return {
                "dna_status": "error",
                "reason": f"parser_error:{type(exc).__name__}",
                "evidence_found": {"scripts": [], "iframes": [], "globals": [],
                                    "comments": [], "forms": []},
                "social_profiles": [],
                "raw_footprint": [],
                "matched_targets": {},
            }

    raw_scripts = _scan_scripts(soup, base_domain)
    raw_iframes = _scan_iframes(soup, base_domain)
    raw_globals = _scan_inline_js(soup)
    raw_comments = _scan_html_comments(html)
    raw_forms = _scan_form_actions(soup, base_domain)
    raw_social = _scan_social_profiles(soup)

    # Footprint: hosts únicos de scripts/iframes/forms.
    footprint: Set[str] = set()
    for ev in raw_scripts + raw_iframes + raw_forms:
        h = ev.get("host")
        if h:
            footprint.add(h)

    # ─── Match dirigido ───
    def _matches_any(text: str) -> Optional[str]:
        if report_all:
            return "*"
        for t in targets_norm:
            if _matches_target(text, t):
                return t
        return None

    matched_targets: Dict[str, List[Dict[str, Any]]] = {}

    def _push_match(target: str, ev: Dict[str, Any]):
        if target == "*":
            return  # solo registramos los matches dirigidos
        matched_targets.setdefault(target, []).append(ev)

    def _filter_dim(items: Iterable[Dict[str, Any]], text_keys: Tuple[str, ...]) -> List[Dict[str, Any]]:
        kept: List[Dict[str, Any]] = []
        for it in items:
            blob = " ".join(str(it.get(k, "")) for k in text_keys)
            target = _matches_any(blob)
            if target is None:
                continue
            kept.append(it)
            if target != "*":
                _push_match(target, it)
        return kept

    scripts_kept = _filter_dim(raw_scripts, ("host", "url", "tech"))
    iframes_kept = _filter_dim(raw_iframes, ("host", "url", "tech"))
    globals_kept = _filter_dim(raw_globals, ("global", "snippet"))
    comments_kept = _filter_dim(raw_comments, ("tech", "snippet"))
    forms_kept = _filter_dim(raw_forms, ("host", "action", "tech"))

    # Sociales: si hay match dirigido, solo se filtran los sociales si
    # el target menciona explícitamente la palabra "social" o el nombre
    # de una red social. En el modo "ALL" se devuelven todos.
    if report_all:
        social_kept = raw_social
    else:
        social_keywords = (
            "social", "linkedin", "instagram", "facebook",
            "twitter", "x.com", "youtube", "tiktok", "social_profiles",
        )
        if any(kw in " ".join(targets_norm) for kw in social_keywords):
            social_kept = raw_social
        else:
            social_kept = []

    return {
        "dna_status": "success",
        "evidence_found": {
            "scripts":  scripts_kept,
            "iframes":  iframes_kept,
            "globals":  globals_kept,
            "comments": comments_kept,
            "forms":    forms_kept,
        },
        "social_profiles": social_kept,
        "raw_footprint": sorted(footprint),
        "matched_targets": matched_targets,
        "mode": "all" if report_all else "targeted",
        "targets": targets_norm,
    }


__all__ = ["run_dna", "SOCIAL_DOMAINS"]
