"""
Quick Alive Check — comprobación ultra-rápida de que un dominio está vivo
y no roto, pensada para el modo rápido del extractor.

Es una versión ligera de la Fase 2 del modo precisión:
  · No usa Playwright, ni navegadores, ni Wappalyzer, ni PageSpeed, ni IA.
  · Un único request HTTP con httpx (timeout corto).
  · Comprobaciones triviales sobre el HTML para detectar dominios muertos,
    parqueados, redirigidos a páginas de error o templates vacíos.

Cada worker llama a `is_alive(url)` antes de pasar a la Fase 3. Si el
dominio falla la comprobación, el worker lo descarta y pide otro de la
cola; si la pasa, sigue a la extracción de contactos como siempre.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

try:
    import httpx  # type: ignore
    _HTTPX_AVAILABLE = True
except ImportError:  # pragma: no cover
    _HTTPX_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────
#  Constantes
# ─────────────────────────────────────────────────────────────────────

# Timeout HTTP del check (segundos). Pensado para ser MUY rápido.
QUICK_CHECK_TIMEOUT = 6
# Tamaño mínimo de HTML que consideramos "vivo". Por debajo son
# normalmente errores de servidor o respuestas vacías.
MIN_BODY_BYTES = 1024
# Máximo de bytes que descargamos para la comprobación.
MAX_BYTES = 200_000

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)

# Patrones de dominios parqueados / placeholders / errores típicos.
# Si aparecen en el HTML el dominio está roto a efectos prácticos.
_PARKING_PATTERNS = (
    re.compile(r"\bdomain\s+is\s+for\s+sale\b", re.IGNORECASE),
    re.compile(r"\bbuy\s+this\s+domain\b", re.IGNORECASE),
    re.compile(r"\bthis\s+domain\s+is\s+parked\b", re.IGNORECASE),
    re.compile(r"\bdominio\s+(?:en\s+venta|aparcado)\b", re.IGNORECASE),
    re.compile(r"\bsedoparking\.com\b", re.IGNORECASE),
    re.compile(r"\bgodaddy\s+parked\b", re.IGNORECASE),
    re.compile(r"\bdan\.com\b", re.IGNORECASE),
    re.compile(r"\bregister\.com\b.*\bparked\b", re.IGNORECASE),
    re.compile(r"\baccount\s+suspended\b", re.IGNORECASE),
    re.compile(r"\bsuspendedpage\.cgi\b", re.IGNORECASE),
    re.compile(r"\bdefault\s+parallels\s+plesk\s+page\b", re.IGNORECASE),
    re.compile(r"\bnginx.*welcome\b", re.IGNORECASE),
    re.compile(r"\bapache.*default\s+page\b", re.IGNORECASE),
    re.compile(r"<title>\s*it\s+works!\s*</title>", re.IGNORECASE),
    re.compile(r"<title>\s*welcome\s+to\s+nginx", re.IGNORECASE),
)

# Paginas claramente "sin nada útil" — strings que aparecen casi en exclusiva
# en errores genéricos del navegador o del servidor.
_BROKEN_HINTS = (
    re.compile(r"\b403\s+forbidden\b", re.IGNORECASE),
    re.compile(r"\b404\s+not\s+found\b", re.IGNORECASE),
    re.compile(r"\b500\s+internal\s+server\s+error\b", re.IGNORECASE),
    re.compile(r"\b502\s+bad\s+gateway\b", re.IGNORECASE),
    re.compile(r"\b503\s+service\s+unavailable\b", re.IGNORECASE),
    re.compile(r"\bcoming\s+soon\b", re.IGNORECASE),
    re.compile(r"\bsite\s+is\s+down\b", re.IGNORECASE),
    re.compile(r"\bsitio\s+en\s+construcción\b", re.IGNORECASE),
)


# ─────────────────────────────────────────────────────────────────────
#  Dataclass de resultado
# ─────────────────────────────────────────────────────────────────────

@dataclass
class QuickCheckResult:
    """Resultado de la comprobación rápida."""
    url: str
    alive: bool = False
    reason: str = ""
    status_code: Optional[int] = None
    final_url: Optional[str] = None
    elapsed_ms: float = 0.0
    html_length: int = 0

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "alive": self.alive,
            "reason": self.reason,
            "status_code": self.status_code,
            "final_url": self.final_url,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "html_length": self.html_length,
        }


# ─────────────────────────────────────────────────────────────────────
#  Implementación
# ─────────────────────────────────────────────────────────────────────

def _is_obvious_parking_or_error(html: str) -> Optional[str]:
    """
    Devuelve un motivo de rechazo si el HTML pinta a parking o error,
    o None si el HTML parece normal. Comprueba solo los primeros 50KB
    para no perder tiempo en payloads enormes.
    """
    if not html:
        return "empty_html"
    sample = html[:50_000]

    for pattern in _PARKING_PATTERNS:
        if pattern.search(sample):
            return "parking_or_placeholder"

    # Solo aplicamos los hints "rotos" si el HTML es además muy pequeño,
    # para no descartar webs reales que mencionan "404 not found" en
    # contenido legítimo.
    if len(sample) < 4000:
        for pattern in _BROKEN_HINTS:
            if pattern.search(sample):
                return "broken_or_placeholder"

    return None


def _has_meaningful_body(html: str) -> bool:
    """
    Heurística mínima: que tenga al menos un <title>, <h1> o un <body>
    con contenido textual de más de 200 caracteres.
    """
    if not html:
        return False
    sample = html[:80_000]
    has_title = bool(re.search(r"<title[^>]*>\s*\S", sample, re.IGNORECASE))
    has_h1 = bool(re.search(r"<h1[^>]*>", sample, re.IGNORECASE))
    if has_title or has_h1:
        return True
    # Body con texto relevante
    body_match = re.search(r"<body[^>]*>([\s\S]*?)</body>", sample, re.IGNORECASE)
    if body_match:
        text = re.sub(r"<[^>]+>", " ", body_match.group(1))
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 200:
            return True
    return False


def is_alive(
    url: str,
    *,
    timeout: float = QUICK_CHECK_TIMEOUT,
    min_bytes: int = MIN_BODY_BYTES,
) -> QuickCheckResult:
    """
    Comprueba si la URL responde y devuelve algo útil. No carga JS ni
    parsea con BS4 — solo HTTP + regex ligera. Ideal para el modo
    rápido: descartar dominios muertos antes de gastar tiempo extrayendo
    contactos.

    Args:
        url: URL absoluta o dominio (se le pone https:// si falta).
        timeout: timeout HTTP en segundos.
        min_bytes: tamaño mínimo de HTML aceptado.

    Returns:
        QuickCheckResult con `alive=True` si todo OK; en caso contrario
        `alive=False` y `reason` explica el motivo.
    """
    started = time.monotonic()
    if not url:
        return QuickCheckResult(url="", alive=False, reason="empty_url")

    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    if not _HTTPX_AVAILABLE:
        # Sin httpx no podemos hacer la comprobación. Resultado conservador:
        # consideramos vivo (deja pasar) para no bloquear el modo rápido.
        return QuickCheckResult(
            url=url, alive=True, reason="httpx_unavailable",
            elapsed_ms=(time.monotonic() - started) * 1000,
        )

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    }

    final_url = url
    status_code: Optional[int] = None
    html_text = ""

    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers=headers,
            http2=False,
        ) as client:
            try:
                resp = client.get(url)
            except httpx.RemoteProtocolError:
                # Algunos servidores rechazan GET sin más; reintentamos sin keep-alive.
                resp = client.get(url, headers={**headers, "Connection": "close"})

            status_code = resp.status_code
            final_url = str(resp.url) if resp.url else url

            if status_code is None or status_code >= 400:
                return QuickCheckResult(
                    url=url, alive=False, reason=f"http_{status_code}",
                    status_code=status_code, final_url=final_url,
                    elapsed_ms=(time.monotonic() - started) * 1000,
                )

            content_type = resp.headers.get("content-type", "").lower()
            # Si el servidor devuelve algo que no es HTML (PDF, json…) lo
            # descartamos: no vamos a poder extraer nada con scrapers HTML.
            if content_type and "html" not in content_type and "text" not in content_type:
                return QuickCheckResult(
                    url=url, alive=False, reason=f"non_html_content:{content_type[:40]}",
                    status_code=status_code, final_url=final_url,
                    elapsed_ms=(time.monotonic() - started) * 1000,
                )

            # Truncamos por si la respuesta es enorme.
            html_text = (resp.text or "")[:MAX_BYTES]

    except httpx.TimeoutException:
        return QuickCheckResult(
            url=url, alive=False, reason="timeout",
            elapsed_ms=(time.monotonic() - started) * 1000,
        )
    except httpx.RequestError as exc:
        return QuickCheckResult(
            url=url, alive=False, reason=f"request_error:{type(exc).__name__}",
            elapsed_ms=(time.monotonic() - started) * 1000,
        )
    except Exception as exc:  # pragma: no cover — defensivo
        return QuickCheckResult(
            url=url, alive=False, reason=f"unexpected:{type(exc).__name__}",
            elapsed_ms=(time.monotonic() - started) * 1000,
        )

    elapsed_ms = (time.monotonic() - started) * 1000
    html_length = len(html_text)

    if html_length < min_bytes:
        return QuickCheckResult(
            url=url, alive=False, reason=f"empty_or_tiny_html ({html_length}B)",
            status_code=status_code, final_url=final_url,
            elapsed_ms=elapsed_ms, html_length=html_length,
        )

    parking_reason = _is_obvious_parking_or_error(html_text)
    if parking_reason:
        return QuickCheckResult(
            url=url, alive=False, reason=parking_reason,
            status_code=status_code, final_url=final_url,
            elapsed_ms=elapsed_ms, html_length=html_length,
        )

    if not _has_meaningful_body(html_text):
        return QuickCheckResult(
            url=url, alive=False, reason="no_meaningful_body",
            status_code=status_code, final_url=final_url,
            elapsed_ms=elapsed_ms, html_length=html_length,
        )

    return QuickCheckResult(
        url=url, alive=True, reason="ok",
        status_code=status_code, final_url=final_url,
        elapsed_ms=elapsed_ms, html_length=html_length,
    )


__all__ = [
    "is_alive",
    "QuickCheckResult",
    "QUICK_CHECK_TIMEOUT",
    "MIN_BODY_BYTES",
]
