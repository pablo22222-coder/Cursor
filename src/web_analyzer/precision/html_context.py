"""
HTMLContext — Descarga el HTML con httpx (sin Playwright) y construye un
contexto estructurado en 3 capas + un resumen del body, listo para pasarse
a la IA en formato Markdown.

Reglas duras (modo precisión):
  · Fetch con httpx, timeout 10s, NO se usan navegadores headless.
  · Limpieza con BeautifulSoup + parser lxml.
  · Toda la fase tiene un timeout total de 20s. Si se agota se devuelve un
    HTMLContext "incomplete" con lo que haya — el resto del pipeline decide.

Capa 1 — Identidad y metadatos
Capa 2 — Estructura de negocio
Capa 3 — Señales semánticas
+ Body (resumen limpio, ≤3000 chars)
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

try:
    import httpx  # type: ignore
    _HTTPX_AVAILABLE = True
except ImportError:  # pragma: no cover
    _HTTPX_AVAILABLE = False

from bs4 import BeautifulSoup


# ─────────────────────────────────────────────────────────────────────
#  Constantes
# ─────────────────────────────────────────────────────────────────────

# Timeout HTTP de la descarga (segundos).
FETCH_TIMEOUT_SECONDS = 10
# Timeout total de la fase (descarga + extracción + render markdown).
TOTAL_TIMEOUT_SECONDS = 20

# User-Agent realista para no parecer un scraper a los firewalls básicos.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)

# CTA — palabras clave que, si aparecen en el texto de un <a>, lo convierten
# en una llamada a la acción.
CTA_KEYWORDS = (
    "comprar", "contratar", "descargar", "empezar", "registrar",
    "contactar", "solicitar", "probar", "ver", "acceder",
)

# Tags que nunca aportan señal de negocio y entorpecen la extracción del body.
NOISE_TAGS = (
    "script", "style", "nav", "footer", "header", "aside",
    "form", "noscript", "iframe",
)

# Expresión para colapsar espacios.
_WS_RE = re.compile(r"\s+")


# ─────────────────────────────────────────────────────────────────────
#  Dataclass de salida
# ─────────────────────────────────────────────────────────────────────

@dataclass
class HTMLContext:
    """
    Contexto estructurado que se envía a la IA. Las listas vacías y los
    strings vacíos están permitidos (el LLM ya entiende ese formato).
    """
    url: str
    domain: str
    success: bool = False
    error: Optional[str] = None
    fetch_time_ms: float = 0.0
    extraction_time_ms: float = 0.0
    status_code: Optional[int] = None
    final_url: Optional[str] = None
    html_length: int = 0

    # Capa 1 — identidad
    lang: str = ""
    title: str = ""
    meta_description: str = ""
    og_type: str = ""
    og_description: str = ""

    # Capa 2 — estructura de negocio
    nav_links: List[str] = field(default_factory=list)
    h1: List[str] = field(default_factory=list)
    h2: List[str] = field(default_factory=list)

    # Capa 3 — señales semánticas
    schema_types: List[str] = field(default_factory=list)
    cta_texts: List[str] = field(default_factory=list)
    footer_text: str = ""

    # Cuerpo limpio
    body_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "domain": self.domain,
            "success": self.success,
            "error": self.error,
            "fetch_time_ms": round(self.fetch_time_ms, 1),
            "extraction_time_ms": round(self.extraction_time_ms, 1),
            "status_code": self.status_code,
            "final_url": self.final_url,
            "html_length": self.html_length,
            "lang": self.lang,
            "title": self.title,
            "meta_description": self.meta_description,
            "og_type": self.og_type,
            "og_description": self.og_description,
            "nav_links": self.nav_links,
            "h1": self.h1,
            "h2": self.h2,
            "schema_types": self.schema_types,
            "cta_texts": self.cta_texts,
            "footer_text": self.footer_text,
            "body_text": self.body_text,
        }


# ─────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────

def _safe_attr(tag, name: str, default: str = "") -> str:
    """Lectura defensiva: nunca crashea si tag o atributo no existen."""
    if tag is None:
        return default
    try:
        value = tag.get(name, default)
    except Exception:
        return default
    if isinstance(value, list):
        value = " ".join(str(v) for v in value)
    return (value or default).strip()


def _meta_content(soup: BeautifulSoup, **filters) -> str:
    """Obtiene el atributo content de un <meta> filtrando por atributos.

    Los kwargs se pasan a BS4 como diccionario `attrs` para evitar el
    conflicto con el primer argumento posicional `name` (el del tag).
    Ejemplo: ``_meta_content(soup, name="description")`` busca el
    primer ``<meta name="description" content="...">``.
    """
    try:
        tag = soup.find("meta", attrs=dict(filters))
    except Exception:
        return ""
    return _safe_attr(tag, "content", "")


def _extract_schema_types(soup: BeautifulSoup) -> List[str]:
    """Lee todos los <script type='application/ld+json'> y devuelve los @type."""
    types: List[str] = []
    seen: set = set()

    def _push(t: Any):
        if isinstance(t, str):
            t = t.strip()
            if t and t not in seen:
                seen.add(t)
                types.append(t)
        elif isinstance(t, list):
            for x in t:
                _push(x)

    def _walk(obj: Any):
        if isinstance(obj, dict):
            if "@type" in obj:
                _push(obj["@type"])
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for v in obj:
                _walk(v)

    try:
        scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    except Exception:
        scripts = []

    for s in scripts:
        raw = s.string or s.get_text() or ""
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            # JSON-LD a menudo lleva comentarios o trailing commas.
            cleaned = re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL)
            cleaned = cleaned.strip().rstrip(";")
            try:
                data = json.loads(cleaned)
            except Exception:
                continue
        _walk(data)

    return types


def _extract_cta_texts(soup: BeautifulSoup, limit: int = 10) -> List[str]:
    """Botones + <a> cuyo texto contiene palabras de acción."""
    out: List[str] = []
    seen: set = set()

    def _add(text: str):
        text = (text or "").strip()
        if not text or len(text) > 80:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(text)

    try:
        for btn in soup.find_all("button"):
            _add(btn.get_text(" ", strip=True))
            if len(out) >= limit:
                return out
    except Exception:
        pass

    try:
        for a in soup.find_all("a"):
            if len(out) >= limit:
                return out
            txt = a.get_text(" ", strip=True)
            if not txt:
                continue
            low = txt.lower()
            if any(kw in low for kw in CTA_KEYWORDS):
                _add(txt)
    except Exception:
        pass

    return out[:limit]


def _extract_nav_links(soup: BeautifulSoup, limit: int = 15) -> List[str]:
    """Textos de enlaces dentro de <nav>, deduplicados y limitados."""
    out: List[str] = []
    seen: set = set()
    try:
        for nav in soup.find_all("nav"):
            for a in nav.find_all("a"):
                txt = a.get_text(" ", strip=True)
                if not txt or len(txt) > 60:
                    continue
                key = txt.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(txt)
                if len(out) >= limit:
                    return out
    except Exception:
        pass
    return out[:limit]


def _extract_footer_text(soup: BeautifulSoup, max_chars: int = 500) -> str:
    """Texto plano del primer <footer>, recortado."""
    try:
        footer = soup.find("footer")
    except Exception:
        return ""
    if footer is None:
        return ""
    try:
        text = footer.get_text(separator=" ", strip=True)
    except Exception:
        return ""
    text = _WS_RE.sub(" ", text or "").strip()
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0]
    return text


def extract_clean_body(soup: BeautifulSoup, max_chars: int = 3000) -> str:
    """
    Limpia el HTML eliminando ruido y devuelve el texto principal recortado.

    Pasos:
      1. .decompose() de NOISE_TAGS sobre una copia (BS soporta decompose
         in-place; aceptamos mutar el árbol porque ya tenemos lo que
         necesitábamos de las capas anteriores antes de llamar aquí).
      2. Busca contenido en <main> > <article> > <body>.
      3. get_text con separador, colapso de espacios, recorte.
    """
    try:
        for tag_name in NOISE_TAGS:
            for tag in soup.find_all(tag_name):
                try:
                    tag.decompose()
                except Exception:
                    pass
    except Exception:
        pass

    container = None
    for selector in ("main", "article", "body"):
        try:
            container = soup.find(selector)
        except Exception:
            container = None
        if container is not None:
            break

    if container is None:
        return ""

    try:
        text = container.get_text(separator=" ", strip=True)
    except Exception:
        return ""
    text = _WS_RE.sub(" ", text or "").strip()
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0]
    return text


# ─────────────────────────────────────────────────────────────────────
#  Fetch
# ─────────────────────────────────────────────────────────────────────

def _fetch_html(url: str, timeout: float) -> Dict[str, Any]:
    """
    Descarga el HTML con httpx, sin navegador. Devuelve un dict con:
      html, status_code, final_url, error.
    Nunca lanza excepción al exterior.
    """
    if not _HTTPX_AVAILABLE:
        return {
            "html": "", "status_code": None, "final_url": None,
            "error": "httpx_no_disponible",
        }

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    }
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers=headers,
            http2=False,  # Mantenemos h1 para máxima compatibilidad
        ) as client:
            resp = client.get(url)
            content_type = resp.headers.get("content-type", "")
            html = resp.text if "html" in content_type or not content_type else ""
            return {
                "html": html or "",
                "status_code": resp.status_code,
                "final_url": str(resp.url) if resp.url else url,
                "error": None,
            }
    except httpx.TimeoutException:
        return {"html": "", "status_code": None, "final_url": None, "error": "timeout"}
    except httpx.RequestError as exc:
        return {
            "html": "", "status_code": None, "final_url": None,
            "error": f"request_error:{type(exc).__name__}",
        }
    except Exception as exc:  # pragma: no cover — defensivo
        return {
            "html": "", "status_code": None, "final_url": None,
            "error": f"unexpected:{type(exc).__name__}",
        }


# ─────────────────────────────────────────────────────────────────────
#  API pública
# ─────────────────────────────────────────────────────────────────────

def build_context(
    url: str,
    *,
    fetch_timeout: float = FETCH_TIMEOUT_SECONDS,
    total_timeout: float = TOTAL_TIMEOUT_SECONDS,
    html: Optional[str] = None,
) -> HTMLContext:
    """
    Construye el HTMLContext completo a partir de la URL.

    Args:
        url: URL absoluta.
        fetch_timeout: timeout HTTP (segundos).
        total_timeout: timeout total de toda la fase (segundos).
        html: Si ya tienes el HTML descargado, pásalo y se salta el fetch.
              Útil para tests y para reusar HTML en distintas etapas.

    Returns:
        HTMLContext. El campo .success indica si la extracción fue
        completa; en caso contrario .error explica el motivo.
    """
    started = time.monotonic()

    # Normalizar URL
    if not url:
        return HTMLContext(url="", domain="", error="empty_url")
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    parsed = urlparse(url)
    domain = (parsed.netloc or "").lower()
    if domain.startswith("www."):
        domain = domain[4:]

    ctx = HTMLContext(url=url, domain=domain, final_url=url)

    # ── 1. Fetch ───────────────────────────────────────────────────────
    if html is None:
        # No malgastes más tiempo del que queda en total_timeout.
        remaining = total_timeout - (time.monotonic() - started)
        effective_fetch_timeout = max(1.0, min(fetch_timeout, remaining - 1.0))
        t0 = time.monotonic()
        fetched = _fetch_html(url, effective_fetch_timeout)
        ctx.fetch_time_ms = (time.monotonic() - t0) * 1000

        ctx.status_code = fetched.get("status_code")
        ctx.final_url = fetched.get("final_url") or url
        if fetched.get("error"):
            ctx.error = fetched["error"]
            return ctx
        html = fetched.get("html") or ""

    ctx.html_length = len(html)

    if not html:
        ctx.error = ctx.error or "empty_html"
        return ctx

    # ── 2. Parseo + extracción de capas ────────────────────────────────
    if (time.monotonic() - started) > total_timeout:
        ctx.error = "total_timeout_after_fetch"
        return ctx

    t0 = time.monotonic()
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as exc:  # pragma: no cover
            ctx.error = f"parser_error:{type(exc).__name__}"
            return ctx

    # Capa 1 — identidad
    try:
        html_tag = soup.find("html")
        ctx.lang = _safe_attr(html_tag, "lang", "")
    except Exception:
        ctx.lang = ""

    try:
        title_tag = soup.find("title")
        ctx.title = (title_tag.get_text(" ", strip=True) if title_tag else "")[:300]
    except Exception:
        ctx.title = ""

    ctx.meta_description = _meta_content(soup, name="description")[:500]
    ctx.og_type = _meta_content(soup, property="og:type")[:80]
    ctx.og_description = _meta_content(soup, property="og:description")[:500]

    # Capa 2 — estructura de negocio
    ctx.nav_links = _extract_nav_links(soup, limit=15)
    try:
        ctx.h1 = [h.get_text(" ", strip=True) for h in soup.find_all("h1") if h.get_text(strip=True)]
    except Exception:
        ctx.h1 = []
    try:
        ctx.h2 = [h.get_text(" ", strip=True) for h in soup.find_all("h2") if h.get_text(strip=True)]
    except Exception:
        ctx.h2 = []

    # Capa 3 — señales semánticas
    ctx.schema_types = _extract_schema_types(soup)
    ctx.cta_texts = _extract_cta_texts(soup, limit=10)
    ctx.footer_text = _extract_footer_text(soup, max_chars=500)

    # Body (mutates soup eliminando ruido — se hace al final para no perder datos).
    ctx.body_text = extract_clean_body(soup, max_chars=3000)

    ctx.extraction_time_ms = (time.monotonic() - t0) * 1000

    # Comprobar timeout total
    if (time.monotonic() - started) > total_timeout:
        ctx.error = "total_timeout_after_extraction"
        # Devolvemos lo que tengamos; el caller decide.
        ctx.success = False
        return ctx

    ctx.success = True
    return ctx


def render_markdown(ctx: HTMLContext) -> str:
    """
    Devuelve el contexto en el formato Markdown estructurado que se
    le pasa a la IA. Sigue exactamente la plantilla pedida.
    """
    nav = ", ".join(ctx.nav_links) if ctx.nav_links else "—"
    h1 = ", ".join(ctx.h1) if ctx.h1 else "—"
    h2 = ", ".join(ctx.h2) if ctx.h2 else "—"
    schemas = ", ".join(ctx.schema_types) if ctx.schema_types else "—"
    ctas = ", ".join(ctx.cta_texts) if ctx.cta_texts else "—"
    footer = ctx.footer_text or "—"
    body = ctx.body_text or "—"

    md = (
        "[CONTEXTO DEL SITIO WEB]\n"
        f"DOMINIO: {ctx.domain}\n"
        f"IDIOMA: {ctx.lang or '—'}\n"
        f"TÍTULO: {ctx.title or '—'}\n"
        f"DESCRIPCIÓN META: {ctx.meta_description or '—'}\n"
        f"OG TYPE: {ctx.og_type or '—'}\n"
        f"OG DESC: {ctx.og_description or '—'}\n"
        "\n"
        "[ESTRUCTURA DE NEGOCIO]\n"
        f"SECCIONES PRINCIPALES: {nav}\n"
        f"H1 (Propuesta): {h1}\n"
        f"H2 (Detalles): {h2}\n"
        "\n"
        "[SEÑALES SEMÁNTICAS]\n"
        f"TIPO DE ENTIDAD (SCHEMA): {schemas}\n"
        f"LLAMADAS A LA ACCIÓN: {ctas}\n"
        f"FOOTER (DATOS LEGALES/SECTOR): {footer}\n"
        "\n"
        "[CUERPO DE TEXTO (RESUMEN)]\n"
        f"{body}\n"
    )
    return md


__all__ = [
    "HTMLContext",
    "build_context",
    "render_markdown",
    "extract_clean_body",
    "FETCH_TIMEOUT_SECONDS",
    "TOTAL_TIMEOUT_SECONDS",
]
