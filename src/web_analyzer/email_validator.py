"""
EmailValidator - Selección del email "real" para un dominio.

Reglas de validación aplicadas al seleccionar el correo definitivo
del conjunto de emails encontrados durante la extracción:

1. Se prioriza SIEMPRE un email cuyo dominio (parte detrás de @) coincida
   con el dominio de la web que se está analizando. Si encontramos uno así,
   ese es el bueno y no se sigue buscando.

2. Si no hay match con el dominio propio, se acepta un email de un proveedor
   genérico (gmail.com, hotmail.com, live.com, outlook.com, icloud.com,
   me.com, yahoo.com, msn.com, aol.com) SIEMPRE que supere los filtros
   anti-basura:
     - No ser una cadena aleatoria de letras/números.
     - Tener 25 caracteres o menos antes del @.
     - No contener palabras prohibidas (noreply, test, sentry, ...).

3. Cualquier email cuyo dominio no sea ni el de la web ni uno de los
   proveedores genéricos se descarta automáticamente (es de otra web).

El resultado es el primer email que cumpla las reglas en el orden del input,
o None si no hay ninguno válido.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional, Tuple
from urllib.parse import urlparse


# Proveedores genéricos de email de persona real (gestionados por humanos).
GENERIC_EMAIL_PROVIDERS = {
    'gmail.com',
    'hotmail.com',
    'live.com',
    'outlook.com',
    'icloud.com',
    'me.com',
    'yahoo.com',
    'msn.com',
    'aol.com',
}

# Palabras prohibidas: si aparecen como substring en la parte anterior al @
# (local part), el email se descarta. Se comprueba en minúsculas.
FORBIDDEN_KEYWORDS = (
    'noreply', 'no-reply', 'no.reply', 'donotreply', 'do-not-reply',
    'no-responder', 'noresponder', 'automail', 'automated',
    'mailer-daemon', 'postmaster',
    'sentry', 'ingest', 'endpoint', 'status',
    'dev', 'developer', 'test', 'staging', 'sandbox', 'localhost',
    'example', 'crash', 'reports', 'logs',
    'wordpress', 'wix', 'shopify', 'aws', 'azure',
    'webmaster', 'hostmaster', 'root', 'daemon', 'ping', 'track',
    'bounce', 'security', 'newsletter', 'boletin',
    'notification', 'notifications', 'alerts', 'alerta',
    'marketing-outbound', 'promo', 'deals',
    'privacy', 'legal', 'abuse', 'spam',
    'captcha', 'verification', 'confirm',
)

# Longitud máxima de la parte local permitida en emails de proveedores genéricos.
MAX_LOCAL_PART_LENGTH = 25

# Regex para detectar cadenas "aleatorias" (hashes/UUID-like) en la parte local.
# - Un bloque sin separadores (. _ -) con >=10 caracteres que mezcle letras y
#   números se considera aleatorio.
# - Hex puro >=16 chars también se considera hash.
_RANDOM_HEX_RE = re.compile(r'^[0-9a-f]{16,}$', re.IGNORECASE)
_MIXED_ALNUM_RE = re.compile(r'^[a-z0-9]+$', re.IGNORECASE)


def _strip_www(domain: str) -> str:
    domain = domain.strip().lower()
    if domain.startswith('www.'):
        domain = domain[4:]
    return domain


def _site_root_domain(site_domain: str) -> str:
    """
    Normaliza el dominio del sitio. Acepta URL completa, dominio con www
    o dominio pelado. Devuelve la forma sin www ni esquema.
    """
    if not site_domain:
        return ''
    d = site_domain.strip()
    if '://' in d:
        try:
            d = urlparse(d).netloc or d
        except Exception:
            pass
    return _strip_www(d)


def _email_domain(email: str) -> str:
    try:
        return email.rsplit('@', 1)[1].strip().lower()
    except (IndexError, AttributeError):
        return ''


def _email_local(email: str) -> str:
    try:
        return email.rsplit('@', 1)[0].strip().lower()
    except (IndexError, AttributeError):
        return ''


def _domain_matches_site(email_domain: str, site_domain: str) -> bool:
    """
    True si el dominio del email coincide con el dominio del sitio
    (o es un subdominio del mismo).
    """
    if not email_domain or not site_domain:
        return False
    email_domain = _strip_www(email_domain)
    site_domain = _strip_www(site_domain)
    if email_domain == site_domain:
        return True
    # Subdominio: mail.empresa.com coincide con empresa.com
    if email_domain.endswith('.' + site_domain):
        return True
    # Caso contrario: la web puede venir como subdominio (p.ej. blog.empresa.com)
    # y el email estar en el dominio raíz empresa.com → también aceptamos.
    if site_domain.endswith('.' + email_domain):
        return True
    return False


def _looks_random(local: str) -> bool:
    """
    Heurística para detectar cadenas aleatorias de letras y/o números.
    Se considera aleatoria si:
      - No contiene separadores típicos (. _ -) Y
      - Tiene longitud >= 10 Y
      - Es todo letras+números Y mezcla ambos, O es hex largo.
    """
    if not local:
        return True
    # Con separadores asumimos que es un nombre real (juan.perez, maria_lopez)
    if any(sep in local for sep in ('.', '_', '-', '+')):
        return False
    if _RANDOM_HEX_RE.match(local):
        return True
    if len(local) < 10:
        return False
    if not _MIXED_ALNUM_RE.match(local):
        return False
    has_digit = any(c.isdigit() for c in local)
    has_letter = any(c.isalpha() for c in local)
    return has_digit and has_letter


def _has_forbidden_keyword(local: str) -> bool:
    low = local.lower()
    for kw in FORBIDDEN_KEYWORDS:
        if kw in low:
            return True
    return False


def is_basic_email(email: str) -> bool:
    """Formato mínimo: algo@algo.algo."""
    if not email or '@' not in email:
        return False
    local = _email_local(email)
    domain = _email_domain(email)
    if not local or not domain:
        return False
    if '.' not in domain:
        return False
    return True


def passes_generic_provider_filters(email: str) -> Tuple[bool, str]:
    """
    Aplica los filtros anti-basura para emails de proveedores genéricos.
    Devuelve (ok, motivo). Si ok=False, motivo explica el rechazo.
    """
    local = _email_local(email)
    if not local:
        return False, 'empty_local_part'
    if len(local) > MAX_LOCAL_PART_LENGTH:
        return False, f'local_part_too_long ({len(local)} > {MAX_LOCAL_PART_LENGTH})'
    if _has_forbidden_keyword(local):
        return False, 'forbidden_keyword'
    if _looks_random(local):
        return False, 'random_string'
    return True, 'ok'


def select_best_email(
    emails: Iterable[str],
    site_domain: str,
) -> Optional[str]:
    """
    Elige el mejor email de la lista dada para el dominio del sitio.

    Orden de preferencia:
      1. Un email cuyo dominio coincida con el dominio del sitio
         (o subdominio). El primero encontrado gana.
      2. Un email de proveedor genérico (gmail/outlook/...) que pase
         los filtros anti-basura. El primero encontrado gana.
      3. None si no hay ninguno válido.

    Cualquier email cuyo dominio no sea ni el del sitio ni un proveedor
    genérico se descarta (pertenece a otra web).
    """
    if not emails:
        return None

    site = _site_root_domain(site_domain)

    seen = set()
    unique_emails = []
    for e in emails:
        if not e:
            continue
        e_norm = e.strip().lower()
        if not is_basic_email(e_norm):
            continue
        if e_norm in seen:
            continue
        seen.add(e_norm)
        unique_emails.append(e_norm)

    # 1) Intentar match con el dominio del sitio
    if site:
        for e in unique_emails:
            if _domain_matches_site(_email_domain(e), site):
                return e

    # 2) Proveedores genéricos con filtros anti-basura
    for e in unique_emails:
        dom = _email_domain(e)
        if dom in GENERIC_EMAIL_PROVIDERS:
            ok, _reason = passes_generic_provider_filters(e)
            if ok:
                return e

    # 3) Ningún email válido
    return None


def filter_emails_for_domain(
    emails: Iterable[str],
    site_domain: str,
) -> list:
    """
    Devuelve la lista de emails válidos para el dominio del sitio,
    preservando el orden. Mismas reglas que select_best_email pero
    no se queda con el primero — útil para `all_emails`.
    """
    if not emails:
        return []

    site = _site_root_domain(site_domain)

    seen = set()
    result = []
    for e in emails:
        if not e:
            continue
        e_norm = e.strip().lower()
        if not is_basic_email(e_norm):
            continue
        if e_norm in seen:
            continue
        dom = _email_domain(e_norm)
        if site and _domain_matches_site(dom, site):
            seen.add(e_norm)
            result.append(e_norm)
            continue
        if dom in GENERIC_EMAIL_PROVIDERS:
            ok, _r = passes_generic_provider_filters(e_norm)
            if ok:
                seen.add(e_norm)
                result.append(e_norm)
            continue
        # Cualquier otro dominio se descarta (pertenece a otra web)
    return result


__all__ = [
    'GENERIC_EMAIL_PROVIDERS',
    'FORBIDDEN_KEYWORDS',
    'MAX_LOCAL_PART_LENGTH',
    'select_best_email',
    'filter_emails_for_domain',
    'is_basic_email',
    'passes_generic_provider_filters',
]
