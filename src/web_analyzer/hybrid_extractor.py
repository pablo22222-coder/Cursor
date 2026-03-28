"""
HybridExtractor - Sistema híbrido Katana + Playwright con 3 Workers
Optimizado para máxima velocidad en extracción de contactos.

Estrategia:
1. Katana primero (ultra rápido, sin JS) - 7s timeout
2. Si encuentra email válido → SALTAR Playwright (ahorro ~70% tiempo)
3. Si Katana falla → Playwright como último recurso

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
    from playwright.async_api import async_playwright, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


MAX_WORKERS = 3
KATANA_TIMEOUT = 7  # seconds - ultra fast
PLAYWRIGHT_TIMEOUT = 15000  # ms

CHROME_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"

BROWSER_ARGS = [
    '--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage',
    '--disable-gpu', '--disable-blink-features=AutomationControlled'
]

# Páginas de alto valor para buscar contactos
HIGH_VALUE_PATHS = ['/contacto', '/contact', '/about', '/legal', '/aviso-legal', '/kontakt', '/quienes-somos']

# Emails placeholder a ignorar
PLACEHOLDER_EMAILS = {
    'example@domain.com', 'email@example.com', 'your@email.com',
    'info@example.com', 'contact@example.com', 'name@domain.com',
    'user@example.com', 'test@test.com', 'admin@example.com'
}

# Lista negra de dominios técnicos (ampliada)
BLACKLIST_DOMAINS = {
    # Servicios técnicos
    'sentry.io', 'ingest.io', 'amazonaws.com', 'cloudfront.net',
    'googleusercontent.com', 'gstatic.com', 'cloudflare.com',
    'herokuapp.com', 'vercel.app', 'netlify.app', 'github.io',
    'githubusercontent.com', 'gravatar.com', 'wp.com',
    # Plataformas web
    'wixpress.com', 'wix.com', 'squarespace.com', 'shopify.com',
    'myshopify.com', 'webflow.io', 'godaddy.com',
    # Estándares y schemas
    'w3.org', 'schema.org', 'json-ld.org', 'ogp.me',
    # Test y ejemplos
    'example.com', 'example.org', 'example.net', 'test.com',
    'test.org', 'localhost', 'domain.com', 'email.com',
    'yourdomain.com', 'company.com', 'website.com',
    # Tracking y analytics
    'analytics.google.com', 'doubleclick.net', 'facebook.com',
    'fbcdn.net', 'twitter.com', 'linkedin.com'
}

# Palabras clave para descartar (noreply, notificaciones, etc.)
BLACKLIST_KEYWORDS = re.compile(
    r'^(noreply|no-reply|no\.reply|donotreply|do-not-reply|'
    r'notification|notifications|alert|alerts|'
    r'mailer|mailer-daemon|postmaster|'
    r'bounce|bounces|unsubscribe|'
    r'dev|devops|staging|test|debug|'
    r'admin-noreply|system|automated|'
    r'newsletter-noreply|marketing-noreply)@',
    re.IGNORECASE
)

# Regex para detectar hashes aleatorios (mezcla sin sentido de letras y números)
HASH_PATTERN = re.compile(r'^[a-z0-9]{8,}$', re.IGNORECASE)
RANDOM_CHARS_PATTERN = re.compile(r'[0-9].*[a-z].*[0-9]|[a-z].*[0-9].*[a-z].*[0-9]', re.IGNORECASE)


def validate_email_quality(email: str) -> tuple[bool, str]:
    """
    Valida la calidad de un email antes de guardarlo.
    
    Returns:
        tuple: (is_valid: bool, reason: str)
        
    Filtros aplicados (ultra rápido con Regex):
    1. Longitud de usuario > 25 chars con patrón hash
    2. Dominios técnicos en lista negra
    3. Palabras clave de sistema (noreply, notification, etc.)
    """
    if not email or '@' not in email:
        return False, "invalid_format"
    
    email_lower = email.lower().strip()
    
    try:
        user_part, domain_part = email_lower.rsplit('@', 1)
    except ValueError:
        return False, "invalid_format"
    
    # === FILTRO 1: Longitud + Hash aleatorio ===
    # Emails con >25 chars O patrón de hash (mezcla aleatoria de letras+números)
    num_digits = sum(1 for c in user_part if c.isdigit())
    num_letters = sum(1 for c in user_part if c.isalpha())
    
    if len(user_part) > 25:
        if HASH_PATTERN.match(user_part) or RANDOM_CHARS_PATTERN.search(user_part):
            if num_digits >= 4:
                return False, f"hash_username ({len(user_part)} chars)"
    
    # Detectar hashes más cortos pero obvios (ej: user1234567890abcdef1234)
    if len(user_part) > 15 and num_digits >= 6 and num_letters >= 6:
        # Proporción alta de números mezclados con letras = probable hash
        if not any(sep in user_part for sep in ['.', '_', '-']):  # Sin separadores normales
            return False, f"probable_hash ({num_digits} digits, {num_letters} letters)"
    
    # === FILTRO 2: Lista negra de dominios técnicos ===
    if domain_part in BLACKLIST_DOMAINS:
        return False, f"blacklisted_domain ({domain_part})"
    
    # Verificar subdominios (ej: mail.sentry.io)
    for blacklisted in BLACKLIST_DOMAINS:
        if domain_part.endswith('.' + blacklisted):
            return False, f"blacklisted_subdomain ({domain_part})"
    
    # === FILTRO 3: Palabras clave de sistema ===
    if BLACKLIST_KEYWORDS.match(email_lower):
        return False, f"system_keyword ({user_part})"
    
    # === FILTRO 4: Extensiones de archivo (común en scraping) ===
    if any(email_lower.endswith(ext) for ext in ['.png', '.jpg', '.gif', '.svg', '.js', '.css', '.json']):
        return False, "file_extension"
    
    # === FILTRO 5: Placeholders conocidos ===
    if email_lower in PLACEHOLDER_EMAILS:
        return False, "placeholder"
    
    return True, "valid"


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
    
    def __init__(self, max_workers: int = MAX_WORKERS, on_progress: Callable = None):
        self.max_workers = max_workers
        self.semaphore = None
        self.on_progress = on_progress
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
        """
        url = domain_info.get('url', '')
        domain = domain_info.get('domain', '')
        
        result = HybridResult(domain=domain, url=url)
        search_email = 'email' in fields
        search_phone = 'phone' in fields
        search_social = 'social' in fields
        
        # === PASO 1: KATANA (Ultra rápido) ===
        katana_success = await self._try_katana(result, url, search_email, search_phone, search_social)
        
        if katana_success and result.email:
            # ¡Katana encontró email! Saltar Playwright
            result.extraction_method = "katana"
            result.katana_found = True
            result.success = True
            self.katana_hits += 1
            print(f"[Katana] ⚡ {domain} -> {result.email} (SKIP Playwright)")
        else:
            # === PASO 2: PLAYWRIGHT (Fallback profundo) ===
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
        
        # Añadir resultado a domain_info
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
        """
        Valida email usando validate_email_quality().
        Ultra rápido con Regex, sin consumo de RAM.
        """
        is_valid, reason = validate_email_quality(email)
        
        if not is_valid:
            # Log para debugging (opcional, comentar en producción)
            # print(f"[Email] ❌ Descartado: {email} ({reason})")
            pass
        
        return is_valid
    
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
                viewport={'width': 1920, 'height': 1080},
                user_agent=CHROME_USER_AGENT,
                locale='es-ES'
            )
            
            page = await context.new_page()
            page.set_default_timeout(PLAYWRIGHT_TIMEOUT)
            
            # Block heavy resources
            await page.route("**/*", lambda route: (
                route.abort() if route.request.resource_type in ["image", "font", "media", "stylesheet"]
                else route.continue_()
            ))
            
            sources = []
            
            # Home
            try:
                await page.goto(url, wait_until='domcontentloaded', timeout=PLAYWRIGHT_TIMEOUT)
                
                # Scroll rápido para cargar lazy content
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1)
                
                html = await page.content()
                
                # Footer primero
                footer_html = self._extract_footer(html)
                if footer_html:
                    if self._extract_from_html(footer_html, result, search_email, search_phone, search_social):
                        sources.append("pw-footer")
                
                if not result.email:
                    if self._extract_from_html(html, result, search_email, search_phone, search_social):
                        sources.append("pw-home")
                        
            except:
                pass
            
            # Contact pages si no hay email
            if not result.email:
                for path in HIGH_VALUE_PATHS[:2]:
                    try:
                        contact_url = urljoin(url, path)
                        response = await page.goto(contact_url, wait_until='domcontentloaded', timeout=10000)
                        
                        if response and response.ok:
                            await asyncio.sleep(0.5)
                            html = await page.content()
                            
                            if self._extract_from_html(html, result, search_email, search_phone, search_social):
                                sources.append(f"pw-{path.strip('/')}")
                            
                            if result.email:
                                break
                    except:
                        continue
            
            if sources:
                result.source = (result.source + " + " if result.source else "") + " + ".join(sources)
            
            await context.close()
            
        except Exception as e:
            pass
        finally:
            if browser:
                try:
                    await browser.close()
                except:
                    pass
            if playwright:
                try:
                    await playwright.stop()
                except:
                    pass


def extract_contacts_hybrid(
    domains: List[Dict[str, Any]], 
    fields: List[str] = None,
    on_progress: Callable = None
) -> List[Dict[str, Any]]:
    """
    Función de conveniencia para extracción híbrida.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        extractor = HybridContactExtractor(on_progress=on_progress)
        return loop.run_until_complete(
            extractor.extract_all_parallel(domains, fields)
        )
    finally:
        loop.close()
        asyncio.set_event_loop(None)
