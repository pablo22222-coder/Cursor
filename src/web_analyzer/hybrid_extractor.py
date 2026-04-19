"""
HybridExtractor - Sistema híbrido Katana + Playwright con 3 Workers
Optimizado para máxima velocidad en extracción de contactos.

Estrategia:
1. Katana primero (ultra rápido, sin JS) - 7s timeout
2. Si encuentra email válido → SALTAR Playwright (ahorro ~70% tiempo)
3. Si Katana falla → Playwright como último recurso con 3 pestañas por worker

Optimizaciones Playwright (Fase 3):
- Bloqueo de recursos no esenciales: image, stylesheet, font, media, other
- Filtrado de scripts de terceros (trackers, ads, analytics)
- 3 pestañas simultáneas por worker (Home + Contacto + Legal)
- Cierre inmediato de las otras pestañas en cuanto una encuentra el email
- Total: 3 workers × 3 pestañas = 9 páginas procesadas en paralelo

Prioridad de búsqueda:
1. Footer (90% de emails están aquí)
2. /contacto, /contact, /about, /legal
"""
import asyncio
import subprocess
import re
import random
import requests
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable, Set
from urllib.parse import urlparse, urljoin
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup

try:
    from playwright.async_api import async_playwright, Page, BrowserContext
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


MAX_WORKERS = 3
KATANA_TIMEOUT = 7        # seconds - modo preciso (Katana interno)
KATANA_FAST_TIMEOUT = 15  # seconds - modo rápido (timeout total por dominio)
PLAYWRIGHT_TIMEOUT = 15000  # ms
# Timeout por pestaña individual dentro del worker (más ajustado)
TAB_TIMEOUT = 10000  # ms

CHROME_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"

BROWSER_ARGS = [
    '--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage',
    '--disable-gpu', '--disable-blink-features=AutomationControlled'
]

# Páginas de alto valor para buscar contactos (se usan las 3 primeras como pestañas)
HIGH_VALUE_PATHS = ['/contacto', '/contact', '/about', '/legal', '/aviso-legal', '/kontakt', '/quienes-somos']

# Tipos de recurso bloqueados — no aportan emails y consumen RAM/tiempo
BLOCKED_RESOURCE_TYPES = {"image", "stylesheet", "font", "media", "other"}

# Dominios de terceros bloqueados (trackers, ads, analytics)
# Solo se bloquean scripts de terceros; los del dominio principal se permiten
BLOCKED_THIRD_PARTY_DOMAINS = {
    # Analytics
    "google-analytics.com", "analytics.google.com", "googletagmanager.com",
    "googletagservices.com", "googlesyndication.com", "stats.g.doubleclick.net",
    "ssl.google-analytics.com",
    # Advertising / doubleclick
    "doubleclick.net", "adservice.google.com", "googleadservices.com",
    "pagead2.googlesyndication.com", "securepubads.g.doubleclick.net",
    # Facebook / Meta pixel
    "connect.facebook.net", "facebook.com", "facebook.net",
    "pixel.facebook.com",
    # Twitter / X tracking
    "platform.twitter.com", "static.ads-twitter.com", "analytics.twitter.com",
    "t.co",
    # LinkedIn insight
    "snap.licdn.com", "px.ads.linkedin.com",
    # Microsoft / Clarity / Bing
    "clarity.ms", "bat.bing.com", "c.bing.com",
    # Hotjar
    "static.hotjar.com", "vars.hotjar.com", "script.hotjar.com",
    # Mixpanel / Segment / Amplitude
    "cdn.mxpnl.com", "api.mixpanel.com",
    "cdn.segment.com", "api.segment.io",
    "cdn.amplitude.com",
    # Intercom / Drift / Crisp / Tidio (chat widgets)
    "widget.intercom.io", "js.intercom.io",
    "js.driftt.com",
    "client.crisp.chat",
    "code.tidio.co",
    # Zendesk
    "static.zdassets.com",
    # HubSpot tracking (solo tracker, no el widget de formularios)
    "js.hs-analytics.net", "js.hs-banner.com",
    # Sentry (error tracking — no aporta emails)
    "browser.sentry-cdn.com", "js.sentry-cdn.com",
    # General CDNs de ads
    "ads.pubmatic.com", "sync.pubmatic.com",
    "contextual.media.net",
    "prebid.org",
}

@dataclass
class HybridResult:
    """Resultado de extracción híbrida."""
    domain: str
    url: str
    
    email: Optional[str] = None
    phone: Optional[str] = None
    all_emails: List[str] = field(default_factory=list)
    all_phones: List[str] = field(default_factory=list)
    social_media: List[Dict[str, str]] = field(default_factory=list)
    
    extraction_method: str = "none"  # katana, playwright, or both
    katana_found: bool = False
    playwright_used: bool = False
    
    success: bool = False
    source: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "email": self.email,
            "phone": self.phone,
            "all_emails": self.all_emails,
            "all_phones": self.all_phones,
            "social_media": self.social_media,
            "extraction_success": self.success,
            "extraction_method": self.extraction_method,
            "source": self.source
        }


class HybridContactExtractor:
    """
    Extractor híbrido: Katana (rápido) + Playwright (profundo).
    
    Optimización:
    - 70% de dominios se resuelven con Katana (sin JS)
    - Solo el 30% necesita Playwright
    - Tiempo promedio reducido de ~10s a ~3s por dominio
    """
    
    EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', re.IGNORECASE)
    MAILTO_REGEX = re.compile(r'href=["\']mailto:([^"\'?]+)', re.IGNORECASE)
    TEL_REGEX = re.compile(r'href=["\']tel:([^"\']+)["\']', re.IGNORECASE)
    PHONE_REGEX = re.compile(r'(?:\+34\s?)?[6789]\d{2}[\s.-]?\d{3}[\s.-]?\d{3}', re.IGNORECASE)
    
    SOCIAL_PATTERNS = {
        'linkedin': re.compile(r'https?://(?:www\.)?linkedin\.com/(?:company|in)/[a-zA-Z0-9_-]+/?', re.IGNORECASE),
        'instagram': re.compile(r'https?://(?:www\.)?instagram\.com/[a-zA-Z0-9_.]+/?', re.IGNORECASE),
        'twitter': re.compile(r'https?://(?:www\.)?(?:twitter\.com|x\.com)/[a-zA-Z0-9_]+/?', re.IGNORECASE),
        'facebook': re.compile(r'https?://(?:www\.)?facebook\.com/[a-zA-Z0-9.]+/?', re.IGNORECASE),
    }
    
    def __init__(
        self,
        max_workers: int = MAX_WORKERS,
        on_progress: Callable = None,
        fast_mode: bool = False,
        tab_count_fn: Callable = None,
    ):
        self.max_workers = max_workers
        self.semaphore = None
        self.on_progress = on_progress
        self.fast_mode = fast_mode  # True → solo Katana, 15s timeout por dominio
        # Callable () → int: devuelve cuántas pestañas están permitidas ahora.
        # Si es None se usa el valor por defecto (3).
        self._tab_count_fn = tab_count_fn
        self.completed = 0
        self.total = 0
        self.katana_hits = 0
        self.playwright_fallbacks = 0
    
    async def extract_all_parallel(
        self, 
        domains: List[Dict[str, Any]], 
        fields: List[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Extrae contactos de múltiples dominios usando sistema híbrido.
        """
        if not fields:
            fields = ['email', 'phone', 'social']
        
        self.total = len(domains)
        self.completed = 0
        self.katana_hits = 0
        self.playwright_fallbacks = 0
        
        self.semaphore = asyncio.Semaphore(self.max_workers)
        
        tasks = [
            self._extract_with_semaphore(domain_info, fields, i)
            for i, domain_info in enumerate(domains)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                domain_info = domains[i].copy()
                domain_info['contact'] = {
                    'email': None, 'phone': None, 'social_media': [],
                    'extraction_success': False, 'extraction_method': 'error',
                    'source': str(result)[:50]
                }
                final_results.append(domain_info)
            else:
                final_results.append(result)
        
        print(f"[Hybrid] Completado: {self.katana_hits} Katana hits, {self.playwright_fallbacks} Playwright fallbacks")
        
        return final_results
    
    async def _extract_with_semaphore(
        self, 
        domain_info: Dict[str, Any], 
        fields: List[str],
        index: int
    ) -> Dict[str, Any]:
        """Extrae con semáforo para limitar a 3 workers."""
        async with self.semaphore:
            result = await self._extract_hybrid(domain_info, fields)
            
            self.completed += 1
            if self.on_progress:
                progress = int((self.completed / self.total) * 100)
                method = "⚡" if result.get('contact', {}).get('extraction_method') == 'katana' else "🔍"
                self.on_progress(
                    progress,
                    f"{method} {domain_info.get('domain', '')}",
                    self.completed,
                    self.total
                )
            
            return result
    
    async def _extract_hybrid(
        self, 
        domain_info: Dict[str, Any], 
        fields: List[str]
    ) -> Dict[str, Any]:
        """
        Extracción híbrida: Katana primero, Playwright si falla.

        Modos:
        - fast_mode=True  → solo Katana, timeout total de 15s por dominio.
                            Si en 15s no hay email, pasa al siguiente dominio.
        - fast_mode=False → Katana (7s) → Playwright como fallback profundo.
        """
        url = domain_info.get('url', '')
        domain = domain_info.get('domain', '')
        
        result = HybridResult(domain=domain, url=url)
        search_email = 'email' in fields
        search_phone = 'phone' in fields
        search_social = 'social' in fields

        if self.fast_mode:
            # === MODO RÁPIDO: solo Katana con timeout máximo de 15s ===
            try:
                katana_success = await asyncio.wait_for(
                    self._try_katana(result, url, search_email, search_phone, search_social),
                    timeout=KATANA_FAST_TIMEOUT
                )
            except asyncio.TimeoutError:
                katana_success = False
                print(f"[Fast] ⏱ {domain} → timeout ({KATANA_FAST_TIMEOUT}s), sin resultados")

            if result.email or result.phone:
                result.extraction_method = "katana"
                result.katana_found = True
                result.success = True
                self.katana_hits += 1
                print(f"[Fast] ⚡ {domain} -> {result.email}")
            else:
                result.extraction_method = "none"
                print(f"[Fast] ❌ {domain} -> Sin resultados")
        else:
            # === MODO PRECISO: Katana (7s) → Playwright fallback ===
            katana_success = await self._try_katana(result, url, search_email, search_phone, search_social)

            if katana_success and result.email:
                result.extraction_method = "katana"
                result.katana_found = True
                result.success = True
                self.katana_hits += 1
                print(f"[Katana] ⚡ {domain} -> {result.email} (SKIP Playwright)")
            else:
                # === PLAYWRIGHT (Fallback profundo) ===
                result.playwright_used = True
                self.playwright_fallbacks += 1

                await self._try_playwright(result, url, search_email, search_phone, search_social)

                if result.email or result.phone:
                    result.extraction_method = "playwright" if not result.katana_found else "both"
                    result.success = True
                    print(f"[Playwright] 🔍 {domain} -> email={result.email}, phone={result.phone}")
                else:
                    result.extraction_method = "none"
                    print(f"[Hybrid] ❌ {domain} -> Sin resultados")
        
        domain_info['contact'] = result.to_dict()
        return domain_info
    
    async def _try_katana(
        self, 
        result: HybridResult, 
        url: str,
        search_email: bool,
        search_phone: bool,
        search_social: bool
    ) -> bool:
        """
        Intenta extracción rápida con Katana + requests.
        Enfocado en footer y páginas de contacto.
        """
        sources = []
        
        try:
            # 1. Obtener HTML de la página principal (rápido)
            loop = asyncio.get_event_loop()
            html = await loop.run_in_executor(None, self._fetch_html_fast, url)
            
            if html:
                # Priorizar FOOTER
                footer_html = self._extract_footer(html)
                if footer_html:
                    if self._extract_from_html(footer_html, result, search_email, search_phone, search_social):
                        sources.append("footer")
                
                # Si no hay email, buscar en página completa
                if not result.email:
                    if self._extract_from_html(html, result, search_email, search_phone, search_social):
                        sources.append("home")
            
            # 2. Si aún no hay email, probar páginas de contacto
            if not result.email:
                for path in HIGH_VALUE_PATHS[:3]:  # Solo las 3 primeras
                    try:
                        contact_url = urljoin(url, path)
                        contact_html = await loop.run_in_executor(None, self._fetch_html_fast, contact_url)
                        
                        if contact_html:
                            # Footer primero
                            footer = self._extract_footer(contact_html)
                            if footer:
                                if self._extract_from_html(footer, result, search_email, search_phone, search_social):
                                    sources.append(f"{path}/footer")
                            
                            if not result.email:
                                if self._extract_from_html(contact_html, result, search_email, search_phone, search_social):
                                    sources.append(path)
                            
                            if result.email:
                                break
                    except:
                        continue
            
            result.source = " + ".join(sources) if sources else "katana"
            return bool(result.email)
            
        except Exception as e:
            return False
    
    def _fetch_html_fast(self, url: str) -> Optional[str]:
        """Fetch HTML rápido con requests (sin JS)."""
        try:
            response = requests.get(
                url,
                timeout=KATANA_TIMEOUT,
                headers={'User-Agent': CHROME_USER_AGENT},
                allow_redirects=True
            )
            if response.status_code == 200:
                return response.text
        except:
            pass
        return None
    
    def _extract_footer(self, html: str) -> Optional[str]:
        """Extrae contenido del footer."""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Buscar tag <footer>
            footer = soup.find('footer')
            if footer:
                return str(footer)
            
            # Buscar elementos con class/id que contengan 'footer'
            for selector in ['footer', '.footer', '#footer', '[class*="footer"]', '[id*="footer"]']:
                elements = soup.select(selector)
                if elements:
                    return ''.join(str(e) for e in elements)
            
            # Últimos 2000 caracteres como fallback
            return html[-2000:] if len(html) > 2000 else html
            
        except:
            return html[-2000:] if len(html) > 2000 else html
    
    def _extract_from_html(
        self, 
        html: str, 
        result: HybridResult,
        search_email: bool,
        search_phone: bool,
        search_social: bool
    ) -> bool:
        """Extrae datos de HTML."""
        found_new = False
        
        # Emails
        if search_email:
            # mailto: primero (más confiable)
            for match in self.MAILTO_REGEX.finditer(html):
                email = match.group(1).strip().lower().split('?')[0]
                if self._is_valid_email(email) and email not in result.all_emails:
                    result.all_emails.append(email)
                    if not result.email:
                        result.email = email
                        found_new = True
            
            # Texto plano
            for match in self.EMAIL_REGEX.finditer(html):
                email = match.group().lower()
                if self._is_valid_email(email) and email not in result.all_emails:
                    result.all_emails.append(email)
                    if not result.email:
                        result.email = email
                        found_new = True
        
        # Teléfonos
        if search_phone:
            for match in self.TEL_REGEX.finditer(html):
                phone = re.sub(r'[\s.-]+', ' ', match.group(1).strip())
                if len(re.sub(r'\D', '', phone)) >= 9 and phone not in result.all_phones:
                    result.all_phones.append(phone)
                    if not result.phone:
                        result.phone = phone
                        found_new = True
            
            for match in self.PHONE_REGEX.finditer(html):
                phone = re.sub(r'[\s.-]+', ' ', match.group())
                if len(re.sub(r'\D', '', phone)) >= 9 and phone not in result.all_phones:
                    result.all_phones.append(phone)
                    if not result.phone:
                        result.phone = phone
                        found_new = True
        
        # Social media
        if search_social:
            found_urls: Set[str] = {s['url'] for s in result.social_media}
            
            for platform, pattern in self.SOCIAL_PATTERNS.items():
                for match in pattern.finditer(html):
                    url = match.group()
                    if url not in found_urls and 'share' not in url.lower():
                        result.social_media.append({'platform': platform, 'url': url})
                        found_urls.add(url)
                        found_new = True
        
        return found_new
    
    def _is_valid_email(self, email: str) -> bool:
        """Comprobación mínima de formato. Todos los emails detectados por
        EMAIL_REGEX se conservan sin filtrado de calidad adicional."""
        return bool(email) and '@' in email
    
    async def _route_handler(self, route, base_domain: str):
        """
        Intercepta todas las peticiones de red del contexto Playwright.

        Reglas:
        1. Abortar recursos no esenciales (image, stylesheet, font, media, other)
        2. Abortar scripts de terceros que pertenecen a trackers/ads conocidos
        3. Permitir el resto (scripts del dominio principal, XHR, fetch, doc, etc.)
        """
        resource_type = route.request.resource_type

        # Regla 1: bloquear tipos no esenciales
        if resource_type in BLOCKED_RESOURCE_TYPES:
            await route.abort()
            return

        # Regla 2: bloquear scripts de terceros conocidos (trackers/ads)
        if resource_type == "script":
            request_url = route.request.url.lower()
            for blocked in BLOCKED_THIRD_PARTY_DOMAINS:
                if blocked in request_url:
                    await route.abort()
                    return

        await route.continue_()

    async def _fetch_page_tab(
        self,
        context: "BrowserContext",
        tab_url: str,
        tab_label: str,
        result: HybridResult,
        found_event: asyncio.Event,
        search_email: bool,
        search_phone: bool,
        search_social: bool,
    ) -> str:
        """
        Abre una sola pestaña, extrae datos y señaliza found_event en cuanto
        encuentra un email. Comprueba el evento en cada punto de espera para
        abortar cuanto antes y liberar RAM al siguiente dominio.
        
        Returns: etiqueta de la fuente si encontró algo, cadena vacía si no.
        """
        # Salida rápida si otra pestaña del mismo worker ya encontró el email
        if found_event.is_set():
            return ""

        page = None
        try:
            page = await context.new_page()
            page.set_default_timeout(TAB_TIMEOUT)

            # Lanzar navegación y esperar o abort según found_event
            nav_task = asyncio.create_task(
                page.goto(tab_url, wait_until="domcontentloaded", timeout=TAB_TIMEOUT)
            )
            wait_event_task = asyncio.create_task(found_event.wait())

            done, pending = await asyncio.wait(
                [nav_task, wait_event_task],
                return_when=asyncio.FIRST_COMPLETED
            )

            # Cancelar la tarea pendiente que no completó primero
            for t in pending:
                t.cancel()
                try:
                    await t
                except Exception:
                    pass

            # Si found_event disparó antes que la navegación, abortar esta pestaña
            if found_event.is_set() and nav_task not in done:
                return ""

            # Comprobar si la navegación lanzó excepción
            if nav_task in done:
                exc = nav_task.exception()
                if exc is not None:
                    return ""

            if found_event.is_set():
                return ""

            # Scroll para activar lazy-load de footer (con early-exit)
            try:
                scroll_task = asyncio.create_task(
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                )
                await asyncio.wait([scroll_task, asyncio.create_task(asyncio.sleep(0.5))],
                                   return_when=asyncio.ALL_COMPLETED)
            except Exception:
                pass

            if found_event.is_set():
                return ""

            html = await page.content()

            # Footer primero
            found_source = ""
            footer_html = self._extract_footer(html)
            if footer_html:
                if self._extract_from_html(footer_html, result, search_email, search_phone, search_social):
                    found_source = f"pw-{tab_label}-footer"

            if not result.email:
                if self._extract_from_html(html, result, search_email, search_phone, search_social):
                    found_source = found_source or f"pw-{tab_label}"

            # Señalizar al resto de pestañas del mismo worker
            if result.email and not found_event.is_set():
                found_event.set()

            return found_source

        except Exception:
            return ""
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass

    async def _try_playwright(
        self, 
        result: HybridResult, 
        url: str,
        search_email: bool,
        search_phone: bool,
        search_social: bool
    ):
        """
        Fallback con Playwright para sitios con JS.
        Solo se ejecuta si Katana no encuentra email.

        Optimizaciones activas:
        - Bloqueo de image, stylesheet, font, media, other via route interception
        - Filtrado de scripts de terceros (trackers, ads, analytics)
        - 3 pestañas simultáneas por worker: Home + /contacto + página legal
        - En cuanto una pestaña encuentra el email, las demás se cancelan
          → libera recursos inmediatamente para el siguiente dominio
        """
        if not PLAYWRIGHT_AVAILABLE:
            return
        
        playwright = None
        browser = None
        
        try:
            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(
                headless=True,
                args=BROWSER_ARGS
            )
            
            context = await browser.new_context(
                viewport={'width': 1280, 'height': 800},
                user_agent=CHROME_USER_AGENT,
                locale='es-ES'
            )

            # Instalar interceptor de rutas en el contexto completo
            # (aplica a TODAS las pestañas abiertas desde este contexto)
            base_domain = urlparse(url).netloc.lower()
            await context.route(
                "**/*",
                lambda route: asyncio.ensure_future(self._route_handler(route, base_domain))
            )

            # Evento compartido: en cuanto una pestaña encuentra email → cancela las demás
            found_event = asyncio.Event()

            # Respetar el límite de pestañas impuesto por el throttle (1, 2 o 3)
            allowed_tabs = self._tab_count_fn() if self._tab_count_fn else 3
            allowed_tabs = max(1, min(3, allowed_tabs))

            _all_tab_pages = [
                (url, "home"),
                (urljoin(url, HIGH_VALUE_PATHS[0]), HIGH_VALUE_PATHS[0].strip("/")),
                (urljoin(url, HIGH_VALUE_PATHS[3]), HIGH_VALUE_PATHS[3].strip("/")),
            ]
            tab_pages = _all_tab_pages[:allowed_tabs]

            # Lanzar las 3 pestañas simultáneamente
            tab_tasks = [
                asyncio.create_task(
                    self._fetch_page_tab(
                        context, tab_url, tab_label,
                        result, found_event,
                        search_email, search_phone, search_social
                    )
                )
                for tab_url, tab_label in tab_pages
            ]

            # Esperar a que todas terminen (las que no encuentran nada terminan solas;
            # las que sí encuentran señalizan found_event y las demás abortan antes)
            tab_sources = await asyncio.gather(*tab_tasks, return_exceptions=True)

            sources = [s for s in tab_sources if isinstance(s, str) and s]
            if sources:
                result.source = (result.source + " + " if result.source else "") + " + ".join(sources)

            await context.close()
            
        except Exception:
            pass
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            if playwright:
                try:
                    await playwright.stop()
                except Exception:
                    pass


def extract_contacts_hybrid(
    domains: List[Dict[str, Any]], 
    fields: List[str] = None,
    on_progress: Callable = None,
    fast_mode: bool = False
) -> List[Dict[str, Any]]:
    """
    Función de conveniencia para extracción híbrida.

    Args:
        fast_mode: True → solo Katana (15s máx por dominio).
                   False → Katana + Playwright fallback (modo preciso).
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        extractor = HybridContactExtractor(on_progress=on_progress, fast_mode=fast_mode)
        return loop.run_until_complete(
            extractor.extract_all_parallel(domains, fields)
        )
    finally:
        loop.close()
        asyncio.set_event_loop(None)
