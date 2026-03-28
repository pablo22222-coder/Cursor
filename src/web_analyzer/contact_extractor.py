"""
ContactExtractor - Extracción Selectiva de Alta Efectividad
Motor de extracción con Playwright optimizado para capturar solo los datos solicitados.

Características:
- Extracción selectiva (solo email, teléfono o RRSS según se solicite)
- Navegación en cascada (Triple Salto)
- Extracción de atributos ocultos (mailto:, tel:)
- Regex de alta sensibilidad
- Técnicas anti-bloqueo (humano real)
"""
import asyncio
import re
import random
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set
from urllib.parse import urlparse, urljoin

try:
    from playwright.async_api import async_playwright, Page, Browser, BrowserContext, TimeoutError as PlaywrightTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


CHROME_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"

BROWSER_ARGS = [
    '--no-sandbox',
    '--disable-setuid-sandbox',
    '--disable-dev-shm-usage',
    '--disable-gpu',
    '--disable-blink-features=AutomationControlled',
    '--disable-infobars',
    '--window-size=1920,1080'
]


@dataclass
class ContactData:
    """Datos de contacto extraídos."""
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
    pages_visited: List[str] = field(default_factory=list)
    fields_requested: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    
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
            "pages_visited": self.pages_visited,
            "fields_requested": self.fields_requested,
            "error_message": self.error_message
        }
    
    def has_all_requested(self, fields: List[str]) -> bool:
        """Comprueba si tenemos todos los datos solicitados."""
        for f in fields:
            if f == 'email' and not self.email:
                return False
            if f == 'phone' and not self.phone:
                return False
            if f == 'social' and not self.social_media:
                return False
        return True
    
    def has_any_data(self) -> bool:
        return bool(self.email or self.phone or self.social_media)
    
    def to_csv_row(self) -> Dict[str, str]:
        social_str = "; ".join([s.get('url', '') for s in self.social_media]) if self.social_media else ""
        return {
            "domain": self.domain,
            "url": self.url,
            "title": self.title or "N/A",
            "email": self.email or "N/A",
            "phone": self.phone or "N/A",
            "social_media": social_str or "N/A"
        }


class ContactExtractor:
    """
    Extractor selectivo de contactos.
    Solo busca los datos que el usuario solicita para máxima eficiencia.
    """
    
    # === REGEX ===
    EMAIL_REGEX = re.compile(
        r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
        re.IGNORECASE
    )
    
    MAILTO_REGEX = re.compile(
        r'href=["\']mailto:([^"\'?]+)',
        re.IGNORECASE
    )
    
    TEL_REGEX = re.compile(
        r'href=["\']tel:([^"\']+)["\']',
        re.IGNORECASE
    )
    
    PHONE_REGEX = re.compile(
        r'(?:\+34\s?)?[6789]\d{2}[\s.-]?\d{3}[\s.-]?\d{3}|'
        r'(?:\+\d{1,3}[\s.-]?)?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}',
        re.IGNORECASE
    )
    
    # Social media patterns
    SOCIAL_PATTERNS = {
        'linkedin': re.compile(r'https?://(?:www\.)?linkedin\.com/(?:company|in)/[a-zA-Z0-9_-]+/?', re.IGNORECASE),
        'instagram': re.compile(r'https?://(?:www\.)?instagram\.com/[a-zA-Z0-9_.]+/?', re.IGNORECASE),
        'twitter': re.compile(r'https?://(?:www\.)?(?:twitter\.com|x\.com)/[a-zA-Z0-9_]+/?', re.IGNORECASE),
        'facebook': re.compile(r'https?://(?:www\.)?facebook\.com/[a-zA-Z0-9.]+/?', re.IGNORECASE),
        'youtube': re.compile(r'https?://(?:www\.)?youtube\.com/(?:c/|channel/|user/|@)?[a-zA-Z0-9_-]+/?', re.IGNORECASE),
        'tiktok': re.compile(r'https?://(?:www\.)?tiktok\.com/@[a-zA-Z0-9_.]+/?', re.IGNORECASE),
    }
    
    EXCLUDED_DOMAINS = {
        'sentry.io', 'wixpress.com', 'w3.org', 'schema.org',
        'googleusercontent.com', 'gstatic.com', 'googleapis.com',
        'cloudflare.com', 'jsdelivr.net', 'unpkg.com', 'cdnjs.com',
        'gravatar.com', 'wp.com', 'wordpress.org', 'wordpress.com',
        'example.com', 'example.org', 'test.com', 'localhost'
    }
    
    EXCLUDED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico', '.pdf'}
    EXCLUDED_PREFIXES = {'noreply', 'no-reply', 'donotreply', 'mailer-daemon', 'postmaster'}
    
    CONTACT_PATHS = [
        '/contacto', '/contact', '/contactenos',
        '/aviso-legal', '/legal',
        '/quienes-somos', '/about', '/sobre-nosotros',
        '/impressum', '/kontakt',
        '/contacto.html', '/contact.html'
    ]
    
    def __init__(self, timeout: int = 45, headless: bool = True):
        self.timeout = timeout
        self.headless = headless
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._playwright = None
    
    async def _init_browser(self):
        if not PLAYWRIGHT_AVAILABLE:
            raise ImportError("Playwright no instalado. Ejecuta: pip install playwright && playwright install chromium")
        
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=BROWSER_ARGS
        )
    
    async def _close_browser(self):
        try:
            if self._context:
                await self._context.close()
                self._context = None
        except:
            pass
        try:
            if self._browser:
                await self._browser.close()
                self._browser = None
        except:
            pass
        try:
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None
        except:
            pass
    
    async def _create_stealth_page(self) -> Page:
        self._context = await self._browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent=CHROME_USER_AGENT,
            locale='es-ES',
            timezone_id='Europe/Madrid',
            java_script_enabled=True
        )
        
        page = await self._context.new_page()
        
        await page.route("**/*", lambda route: (
            route.abort() if route.request.resource_type in ["image", "font", "media"]
            else route.continue_()
        ))
        
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = {runtime: {}};
        """)
        
        return page
    
    async def _simulate_human(self, page: Page):
        try:
            await page.mouse.move(
                random.randint(100, 500),
                random.randint(100, 300)
            )
            await asyncio.sleep(0.3)
            
            scroll_amount = random.randint(300, 800)
            await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
            await asyncio.sleep(0.5)
            
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.5)
            
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(0.3)
        except:
            pass
    
    async def extract_async(self, url: str, fields: List[str] = None) -> ContactData:
        """
        Extracción selectiva - solo busca los campos solicitados.
        
        Args:
            url: URL a analizar
            fields: Lista de campos a extraer ['email', 'phone', 'social']
                   Si es None o vacío, no extrae nada (solo título)
        """
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        
        domain = self._extract_domain(url)
        contact = ContactData(domain=domain, url=url)
        
        # Si no hay campos solicitados, solo devolver estructura básica
        if not fields:
            contact.fields_requested = []
            return contact
        
        contact.fields_requested = fields
        sources = []
        
        # Determinar qué buscar
        search_email = 'email' in fields
        search_phone = 'phone' in fields
        search_social = 'social' in fields
        
        try:
            await self._init_browser()
            page = await self._create_stealth_page()
            page.set_default_timeout(self.timeout * 1000)
            
            # === PASO 1: HOME ===
            try:
                await page.goto(url, wait_until='domcontentloaded', timeout=15000)
                contact.pages_visited.append(url)
                
                try:
                    contact.title = await page.title()
                except:
                    pass
                
                await self._simulate_human(page)
                await asyncio.sleep(2)
                
                html = await page.content()
                self._extract_data(html, contact, search_email, search_phone, search_social)
                
                if contact.has_any_data():
                    sources.append("home")
                
            except Exception as e:
                contact.error_message = f"Error en home: {str(e)[:50]}"
            
            # === PASO 2: NAVEGACIÓN EN CASCADA ===
            # Solo continuar si no tenemos todos los datos solicitados
            if not contact.has_all_requested(fields):
                for path in self.CONTACT_PATHS:
                    if contact.has_all_requested(fields):
                        break
                    
                    try:
                        contact_url = urljoin(url, path)
                        
                        if contact_url in contact.pages_visited:
                            continue
                        
                        response = await page.goto(
                            contact_url, 
                            wait_until='domcontentloaded', 
                            timeout=10000
                        )
                        
                        if response and response.ok:
                            contact.pages_visited.append(contact_url)
                            
                            await self._simulate_human(page)
                            await asyncio.sleep(1)
                            
                            html = await page.content()
                            found_new = self._extract_data(html, contact, search_email, search_phone, search_social)
                            
                            if found_new:
                                sources.append(path.strip('/'))
                                
                    except:
                        continue
            
            try:
                await page.close()
            except:
                pass
                
        except ImportError as e:
            contact.error_message = str(e)
        except Exception as e:
            contact.error_message = f"Error: {str(e)[:100]}"
        finally:
            await self._close_browser()
        
        contact.source = " + ".join(sources) if sources else "none"
        contact.extraction_success = contact.has_any_data()
        
        return contact
    
    def _extract_data(self, html: str, contact: ContactData, 
                      search_email: bool, search_phone: bool, search_social: bool) -> bool:
        """Extrae solo los datos solicitados."""
        found_new = False
        
        # === EMAIL ===
        if search_email and not contact.email:
            for match in self.MAILTO_REGEX.finditer(html):
                email = match.group(1).strip().lower()
                email = email.split('?')[0]
                
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
        
        # === TELÉFONO ===
        if search_phone and not contact.phone:
            for match in self.TEL_REGEX.finditer(html):
                phone = match.group(1).strip()
                phone = self._normalize_phone(phone)
                
                if self._is_valid_phone(phone) and phone not in contact.all_phones:
                    contact.all_phones.append(phone)
                    if not contact.phone:
                        contact.phone = phone
                        found_new = True
            
            for match in self.PHONE_REGEX.finditer(html):
                phone = match.group()
                phone = self._normalize_phone(phone)
                
                if self._is_valid_phone(phone) and phone not in contact.all_phones:
                    contact.all_phones.append(phone)
                    if not contact.phone:
                        contact.phone = phone
                        found_new = True
        
        # === REDES SOCIALES ===
        if search_social:
            found_urls: Set[str] = {s['url'] for s in contact.social_media}
            
            for platform, pattern in self.SOCIAL_PATTERNS.items():
                for match in pattern.finditer(html):
                    social_url = match.group()
                    
                    if social_url not in found_urls and self._is_valid_social(social_url, platform):
                        contact.social_media.append({
                            'platform': platform,
                            'url': social_url
                        })
                        found_urls.add(social_url)
                        found_new = True
        
        return found_new
    
    def _is_valid_email(self, email: str) -> bool:
        if not email or '@' not in email:
            return False
        
        email = email.lower().strip()
        
        for ext in self.EXCLUDED_EXTENSIONS:
            if email.endswith(ext):
                return False
        
        try:
            domain = email.split('@')[1]
            if domain in self.EXCLUDED_DOMAINS:
                return False
            if '.' not in domain:
                return False
        except:
            return False
        
        prefix = email.split('@')[0]
        if any(prefix.startswith(excl) for excl in self.EXCLUDED_PREFIXES):
            return False
        
        return True
    
    def _is_valid_phone(self, phone: str) -> bool:
        if not phone:
            return False
        
        digits = re.sub(r'\D', '', phone)
        
        if not (9 <= len(digits) <= 15):
            return False
        
        if digits in ['123456789', '000000000', '111111111', '999999999']:
            return False
        
        return True
    
    def _is_valid_social(self, url: str, platform: str) -> bool:
        """Valida URLs de redes sociales."""
        url_lower = url.lower()
        
        # Excluir URLs de recursos estáticos
        if any(ext in url_lower for ext in ['.png', '.jpg', '.css', '.js']):
            return False
        
        # Excluir páginas genéricas
        generic_paths = ['share', 'sharer', 'intent', 'dialog', 'login', 'signup']
        if any(gp in url_lower for gp in generic_paths):
            return False
        
        return True
    
    def _normalize_phone(self, phone: str) -> str:
        phone = re.sub(r'[\s.-]+', ' ', phone.strip())
        phone = re.sub(r'\s+', ' ', phone)
        return phone
    
    def _extract_domain(self, url: str) -> str:
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except:
            return url
    
    def extract(self, url: str, fields: List[str] = None) -> ContactData:
        """
        Versión síncrona para Flask.
        Crea nuevo event loop para funcionar en threads.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.extract_async(url, fields))
        finally:
            loop.close()
            asyncio.set_event_loop(None)


def extract_contacts(url: str, fields: List[str] = None, timeout: int = 45) -> ContactData:
    """Extrae contactos de una URL."""
    extractor = ContactExtractor(timeout=timeout)
    return extractor.extract(url, fields)
