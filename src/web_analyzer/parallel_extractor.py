"""
ParallelExtractor - Extracción de contactos con 3 Workers paralelos
Usa asyncio.Semaphore(3) para procesar hasta 3 dominios simultáneamente.
"""
import asyncio
import re
import random
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable, Set
from urllib.parse import urlparse, urljoin

try:
    from playwright.async_api import async_playwright, Page, Browser
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


MAX_WORKERS = 3
CHROME_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"

BROWSER_ARGS = [
    '--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage',
    '--disable-gpu', '--disable-blink-features=AutomationControlled'
]

# Tipos de recurso bloqueados (no aportan emails y consumen RAM/tiempo)
BLOCKED_RESOURCE_TYPES = {"image", "stylesheet", "font", "media", "other"}

# Dominios de terceros bloqueados (trackers, ads, analytics)
BLOCKED_THIRD_PARTY_DOMAINS = {
    "google-analytics.com", "analytics.google.com", "googletagmanager.com",
    "googletagservices.com", "googlesyndication.com", "stats.g.doubleclick.net",
    "doubleclick.net", "adservice.google.com", "googleadservices.com",
    "connect.facebook.net", "facebook.net", "pixel.facebook.com",
    "platform.twitter.com", "static.ads-twitter.com", "analytics.twitter.com",
    "snap.licdn.com", "px.ads.linkedin.com",
    "clarity.ms", "bat.bing.com",
    "static.hotjar.com", "vars.hotjar.com", "script.hotjar.com",
    "cdn.mxpnl.com", "api.mixpanel.com",
    "cdn.segment.com", "api.segment.io",
    "cdn.amplitude.com",
    "widget.intercom.io", "js.intercom.io",
    "js.driftt.com",
    "client.crisp.chat",
    "code.tidio.co",
    "static.zdassets.com",
    "js.hs-analytics.net", "js.hs-banner.com",
    "browser.sentry-cdn.com", "js.sentry-cdn.com",
}


@dataclass
class ContactResult:
    """Resultado de extracción de contacto."""
    domain: str
    url: str
    
    title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    
    all_emails: List[str] = field(default_factory=list)
    all_phones: List[str] = field(default_factory=list)
    social_media: List[Dict[str, str]] = field(default_factory=list)
    
    extraction_success: bool = False
    source: str = ""
    pages_visited: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "url": self.url,
            "title": self.title,
            "email": self.email,
            "phone": self.phone,
            "all_emails": self.all_emails,
            "all_phones": self.all_phones,
            "social_media": self.social_media,
            "extraction_success": self.extraction_success,
            "source": self.source,
            "pages_visited": self.pages_visited
        }


class ParallelContactExtractor:
    """
    Extractor de contactos con 3 Workers paralelos.
    Optimizado para la Fase 3 del buscador de dominios.
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
        'youtube': re.compile(r'https?://(?:www\.)?youtube\.com/(?:c/|channel/|user/|@)?[a-zA-Z0-9_-]+/?', re.IGNORECASE),
        'tiktok': re.compile(r'https?://(?:www\.)?tiktok\.com/@[a-zA-Z0-9_.]+/?', re.IGNORECASE),
    }
    
    EXCLUDED_DOMAINS = {'sentry.io', 'wixpress.com', 'w3.org', 'schema.org', 'example.com'}
    EXCLUDED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.svg'}
    
    CONTACT_PATHS = ['/contacto', '/contact', '/aviso-legal', '/legal', '/about', '/quienes-somos']
    
    def __init__(self, max_workers: int = MAX_WORKERS, on_progress: Callable = None):
        self.max_workers = max_workers
        self.semaphore = None
        self.on_progress = on_progress
        self.completed = 0
        self.total = 0
    
    async def extract_contacts_parallel(
        self, 
        domains: List[Dict[str, Any]], 
        fields: List[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Extrae contactos de múltiples dominios en paralelo con 3 workers.
        
        Args:
            domains: Lista de dicts con 'url' y 'domain'
            fields: Campos a extraer ['email', 'phone', 'social']
        
        Returns:
            Lista de resultados con datos de contacto añadidos
        """
        if not fields:
            fields = ['email', 'phone', 'social']
        
        self.total = len(domains)
        self.completed = 0
        
        # Crear semáforo para limitar workers
        self.semaphore = asyncio.Semaphore(self.max_workers)
        
        # Crear tareas
        tasks = [
            self._extract_with_semaphore(domain_info, fields, i) 
            for i, domain_info in enumerate(domains)
        ]
        
        # Ejecutar en paralelo
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Procesar resultados
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                domain_info = domains[i].copy()
                domain_info['contact'] = {
                    'email': None, 'phone': None, 'social_media': [],
                    'extraction_success': False, 'source': 'error'
                }
                final_results.append(domain_info)
            else:
                final_results.append(result)
        
        return final_results
    
    async def _extract_with_semaphore(
        self, 
        domain_info: Dict[str, Any], 
        fields: List[str],
        index: int
    ) -> Dict[str, Any]:
        """Extrae contactos respetando el semáforo."""
        async with self.semaphore:
            result = await self._extract_single(domain_info, fields)
            
            self.completed += 1
            if self.on_progress:
                progress = int((self.completed / self.total) * 100)
                self.on_progress(
                    progress, 
                    f"Extrayendo {domain_info.get('domain', '')}...",
                    self.completed, 
                    self.total
                )
            
            return result
    
    async def _extract_single(
        self, 
        domain_info: Dict[str, Any], 
        fields: List[str]
    ) -> Dict[str, Any]:
        """Extrae contactos de un solo dominio."""
        url = domain_info.get('url', '')
        domain = domain_info.get('domain', '')
        
        contact = ContactResult(domain=domain, url=url)
        sources = []
        
        search_email = 'email' in fields
        search_phone = 'phone' in fields
        search_social = 'social' in fields
        
        if not PLAYWRIGHT_AVAILABLE:
            domain_info['contact'] = contact.to_dict()
            return domain_info
        
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
            page.set_default_timeout(15000)

            # Block non-essential resources and third-party trackers/ads
            async def _route_handler(route):
                resource_type = route.request.resource_type
                if resource_type in BLOCKED_RESOURCE_TYPES:
                    await route.abort()
                    return
                if resource_type == "script":
                    req_url = route.request.url.lower()
                    for blocked in BLOCKED_THIRD_PARTY_DOMAINS:
                        if blocked in req_url:
                            await route.abort()
                            return
                await route.continue_()

            await page.route("**/*", lambda route: asyncio.ensure_future(_route_handler(route)))
            
            # Anti-detection
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            """)
            
            pages_visited = 0
            
            # === PASO 1: HOME ===
            try:
                await page.goto(url, wait_until='domcontentloaded', timeout=15000)
                pages_visited += 1
                
                # Title
                try:
                    contact.title = await page.title()
                except:
                    pass
                
                # Simulate human
                await self._simulate_human(page)
                await asyncio.sleep(1)
                
                # Extract
                html = await page.content()
                if self._extract_data(html, contact, search_email, search_phone, search_social):
                    sources.append("home")
                
            except:
                pass
            
            # === PASO 2: CONTACT PAGES (Triple Salto) ===
            if search_email and not contact.email:
                for path in self.CONTACT_PATHS:
                    if contact.email:
                        break
                    
                    try:
                        contact_url = urljoin(url, path)
                        response = await page.goto(contact_url, wait_until='domcontentloaded', timeout=10000)
                        
                        if response and response.ok:
                            pages_visited += 1
                            await self._simulate_human(page)
                            await asyncio.sleep(0.5)
                            
                            html = await page.content()
                            if self._extract_data(html, contact, search_email, search_phone, search_social):
                                sources.append(path.strip('/'))
                    except:
                        continue
            
            contact.pages_visited = pages_visited
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
        
        contact.source = " + ".join(sources) if sources else "none"
        contact.extraction_success = bool(contact.email or contact.phone or contact.social_media)
        
        # Add contact to domain_info
        domain_info['contact'] = {
            'email': contact.email if search_email else None,
            'phone': contact.phone if search_phone else None,
            'all_emails': contact.all_emails if search_email else [],
            'all_phones': contact.all_phones if search_phone else [],
            'social_media': contact.social_media if search_social else [],
            'extraction_success': contact.extraction_success,
            'source': contact.source,
            'pages_visited': contact.pages_visited
        }
        
        # Update title if found
        if contact.title and (not domain_info.get('title') or len(contact.title) > len(domain_info.get('title', ''))):
            domain_info['title'] = contact.title
        
        return domain_info
    
    async def _simulate_human(self, page: Page):
        """Simulate human behavior."""
        try:
            await page.mouse.move(random.randint(100, 400), random.randint(100, 300))
            await page.evaluate(f"window.scrollBy(0, {random.randint(200, 500)})")
            await asyncio.sleep(0.3)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.3)
        except:
            pass
    
    def _extract_data(
        self, 
        html: str, 
        contact: ContactResult,
        search_email: bool,
        search_phone: bool,
        search_social: bool
    ) -> bool:
        """Extract data from HTML."""
        found_new = False
        
        # Emails
        if search_email:
            for match in self.MAILTO_REGEX.finditer(html):
                email = match.group(1).strip().lower().split('?')[0]
                if self._is_valid_email(email) and email not in contact.all_emails:
                    contact.all_emails.append(email)
                    if not contact.email:
                        contact.email = email
                        found_new = True
            
            for match in self.EMAIL_REGEX.finditer(html):
                email = match.group().lower()
                if self._is_valid_email(email) and email not in contact.all_emails:
                    contact.all_emails.append(email)
                    if not contact.email:
                        contact.email = email
                        found_new = True
        
        # Phones
        if search_phone:
            for match in self.TEL_REGEX.finditer(html):
                phone = re.sub(r'[\s.-]+', ' ', match.group(1).strip())
                if len(re.sub(r'\D', '', phone)) >= 9 and phone not in contact.all_phones:
                    contact.all_phones.append(phone)
                    if not contact.phone:
                        contact.phone = phone
                        found_new = True
            
            for match in self.PHONE_REGEX.finditer(html):
                phone = re.sub(r'[\s.-]+', ' ', match.group())
                if len(re.sub(r'\D', '', phone)) >= 9 and phone not in contact.all_phones:
                    contact.all_phones.append(phone)
                    if not contact.phone:
                        contact.phone = phone
                        found_new = True
        
        # Social
        if search_social:
            found_urls: Set[str] = {s['url'] for s in contact.social_media}
            
            for platform, pattern in self.SOCIAL_PATTERNS.items():
                for match in pattern.finditer(html):
                    url = match.group()
                    if url not in found_urls and 'share' not in url.lower():
                        contact.social_media.append({'platform': platform, 'url': url})
                        found_urls.add(url)
                        found_new = True
        
        return found_new
    
    def _is_valid_email(self, email: str) -> bool:
        if not email or '@' not in email:
            return False
        domain = email.split('@')[1]
        if domain in self.EXCLUDED_DOMAINS:
            return False
        if any(email.endswith(ext) for ext in self.EXCLUDED_EXTENSIONS):
            return False
        return True


def extract_contacts_parallel(
    domains: List[Dict[str, Any]], 
    fields: List[str] = None,
    on_progress: Callable = None
) -> List[Dict[str, Any]]:
    """
    Función de conveniencia para extracción paralela.
    Crea su propio event loop para uso desde Flask.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        extractor = ParallelContactExtractor(on_progress=on_progress)
        return loop.run_until_complete(
            extractor.extract_contacts_parallel(domains, fields)
        )
    finally:
        loop.close()
        asyncio.set_event_loop(None)
