"""
Extractor de datos de contacto usando Playwright (Async).
Motor de extracción en memoria, sin binarios externos.

Características:
- Modo sigilo: sin imágenes ni CSS (máxima velocidad)
- Extracción del footer (90% de contactos)
- Navegación automática a /contacto si no hay email
- Timeout configurable con entrega parcial
- Campos dinámicos (email, phone, social)
"""
import asyncio
import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set
from urllib.parse import urlparse, urljoin

try:
    from playwright.async_api import async_playwright, Page, Browser, BrowserContext, TimeoutError as PlaywrightTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# User-Agent real de Chrome
CHROME_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Args para Codespaces/Docker
BROWSER_ARGS = [
    '--no-sandbox',
    '--disable-setuid-sandbox',
    '--disable-dev-shm-usage',
    '--disable-gpu'
]


@dataclass
class ContactData:
    """Datos de contacto extraídos de una web."""
    domain: str
    url: str
    
    # Datos extraídos
    title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    
    # Redes sociales
    linkedin: Optional[str] = None
    instagram: Optional[str] = None
    twitter: Optional[str] = None
    facebook: Optional[str] = None
    youtube: Optional[str] = None
    tiktok: Optional[str] = None
    
    # Lista de todas las redes sociales
    social_media: List[str] = field(default_factory=list)
    
    # Estado
    extraction_success: bool = False
    partial_data: bool = False
    source: str = ""
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "url": self.url,
            "title": self.title,
            "email": self.email,
            "phone": self.phone,
            "linkedin": self.linkedin,
            "instagram": self.instagram,
            "twitter": self.twitter,
            "facebook": self.facebook,
            "youtube": self.youtube,
            "tiktok": self.tiktok,
            "social_media": self.social_media,
            "extraction_success": self.extraction_success,
            "partial_data": self.partial_data,
            "source": self.source,
            "error_message": self.error_message
        }
    
    def has_any_data(self) -> bool:
        return bool(self.email or self.phone or self.social_media or self.title)
    
    def has_contact_data(self) -> bool:
        """Tiene email o teléfono o red social."""
        return bool(self.email or self.phone or self.social_media)
    
    def to_csv_row(self) -> Dict[str, str]:
        return {
            "domain": self.domain,
            "url": self.url,
            "title": self.title or "N/A",
            "email": self.email or "N/A",
            "phone": self.phone or "N/A",
            "linkedin": self.linkedin or "N/A",
            "instagram": self.instagram or "N/A",
            "twitter": self.twitter or "N/A",
            "facebook": self.facebook or "N/A",
            "youtube": self.youtube or "N/A",
            "tiktok": self.tiktok or "N/A"
        }


class ContactExtractor:
    """
    Extractor de contactos usando Playwright.
    
    Modo sigilo para máxima velocidad:
    - Sin cargar imágenes
    - Sin cargar CSS
    - Sin cargar fuentes
    """
    
    # Regex patterns
    EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
    MAILTO_REGEX = re.compile(r'mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})')
    PHONE_REGEX = re.compile(r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}')
    TEL_REGEX = re.compile(r'href=["\']tel:([^"\']+)["\']')
    
    SOCIAL_PATTERNS = {
        "linkedin": re.compile(r'(?:https?://)?(?:www\.)?linkedin\.com/(?:company|in)/[a-zA-Z0-9_.-]+', re.I),
        "instagram": re.compile(r'(?:https?://)?(?:www\.)?instagram\.com/[a-zA-Z0-9_.-]+', re.I),
        "twitter": re.compile(r'(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/[a-zA-Z0-9_.-]+', re.I),
        "facebook": re.compile(r'(?:https?://)?(?:www\.)?facebook\.com/[a-zA-Z0-9_.-]+', re.I),
        "youtube": re.compile(r'(?:https?://)?(?:www\.)?youtube\.com/(?:c/|channel/|user/|@)[a-zA-Z0-9_.-]+', re.I),
        "tiktok": re.compile(r'(?:https?://)?(?:www\.)?tiktok\.com/@[a-zA-Z0-9_.-]+', re.I),
    }
    
    # Páginas de contacto a verificar
    CONTACT_PATHS = ['/contacto', '/contact', '/contactenos', '/aviso-legal', '/legal', '/about', '/sobre-nosotros', '/impressum']
    
    # Emails a excluir
    EXCLUDED_DOMAINS = {
        "example.com", "example.org", "test.com", "sentry.io", "wixpress.com",
        "w3.org", "schema.org", "googleusercontent.com", "gstatic.com",
        "gravatar.com", "wordpress.org", "jsdelivr.net", "cloudflare.com",
        "facebook.com", "twitter.com", "instagram.com", "linkedin.com"
    }
    EXCLUDED_PREFIXES = {'noreply', 'no-reply', 'donotreply', 'postmaster', 'webmaster', 'mailer-daemon'}
    
    def __init__(self, timeout: int = 45, headless: bool = True):
        """
        Args:
            timeout: Timeout total en segundos
            headless: Ejecutar sin interfaz gráfica
        """
        self.timeout = timeout
        self.headless = headless
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._playwright = None
    
    async def _init_browser(self):
        """Inicializa el navegador con modo sigilo y args para Codespaces."""
        if not PLAYWRIGHT_AVAILABLE:
            raise ImportError("Playwright no está instalado. Ejecuta: pip install playwright && playwright install chromium")
        
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=BROWSER_ARGS
        )
    
    async def _close_browser(self):
        """Cierra el navegador y libera memoria."""
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
        """
        Crea una página en modo sigilo (sin imágenes, CSS, fuentes).
        User-Agent real de Chrome para evitar detección.
        """
        self._context = await self._browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent=CHROME_USER_AGENT,
            locale='es-ES',
            timezone_id='Europe/Madrid'
        )
        
        page = await self._context.new_page()
        
        # Bloquear recursos innecesarios para máxima velocidad
        await page.route("**/*", lambda route: (
            route.abort() if route.request.resource_type in ["image", "stylesheet", "font", "media"]
            else route.continue_()
        ))
        
        return page
    
    async def _quick_scroll(self, page: Page):
        """
        Scroll rápido para cargar contenido lazy-loaded.
        Baja hasta el footer y vuelve arriba.
        """
        try:
            # Scroll hasta abajo
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.5)
            # Scroll hasta arriba
            await page.evaluate("window.scrollTo(0, 0)")
        except:
            pass

    async def extract_async(self, url: str, fields: List[str] = None) -> ContactData:
        """
        Extrae datos de contacto de una URL.
        
        Args:
            url: URL a extraer
            fields: Campos a buscar ['email', 'phone', 'social', 'title']
                   Si es None, busca todos
        
        Returns:
            ContactData con los datos encontrados
        """
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        
        domain = self._extract_domain(url)
        contact = ContactData(domain=domain, url=url)
        
        # Campos por defecto
        if fields is None:
            fields = ['email', 'phone', 'social', 'title']
        
        search_email = 'email' in fields
        search_phone = 'phone' in fields
        search_social = 'social' in fields
        search_title = 'title' in fields
        
        found_data = {
            "title": None, "email": None, "phone": None,
            "linkedin": None, "instagram": None, "twitter": None,
            "facebook": None, "youtube": None, "tiktok": None
        }
        sources = []
        
        try:
            await self._init_browser()
            page = await self._create_stealth_page()
            
            # Timeout global
            page.set_default_timeout(self.timeout * 1000)
            
            try:
                # === PASO 1: Navegar a la Home ===
                await page.goto(url, wait_until='domcontentloaded', timeout=15000)
                
                # Extraer título
                if search_title:
                    try:
                        found_data["title"] = await page.title()
                        if found_data["title"]:
                            sources.append("title")
                    except:
                        pass
                
                # Scroll rápido para cargar contenido lazy
                await self._quick_scroll(page)
                
                # Esperar 2 segundos para que cargue contenido dinámico
                await asyncio.sleep(2)
                
                # Extraer del HTML completo
                html = await page.content()
                
                # Buscar en footer específicamente (90% de contactos están ahí)
                footer_html = await self._get_footer_content(page)
                if footer_html:
                    self._extract_from_html(footer_html, found_data, search_email, search_phone, search_social)
                    if found_data["email"] or self._has_any_social(found_data):
                        sources.append("footer")
                
                # Si no hay email, buscar en todo el HTML
                if search_email and not found_data["email"]:
                    self._extract_from_html(html, found_data, search_email, search_phone, search_social)
                    if found_data["email"]:
                        sources.append("homepage")
                
                # === PASO 2: Si no hay email, ir a página de contacto ===
                if search_email and not found_data["email"]:
                    for path in self.CONTACT_PATHS:
                        try:
                            contact_url = urljoin(url, path)
                            response = await page.goto(contact_url, wait_until='domcontentloaded', timeout=8000)
                            
                            if response and response.ok:
                                # Scroll y espera en página de contacto
                                await self._quick_scroll(page)
                                await asyncio.sleep(1)
                                
                                contact_html = await page.content()
                                self._extract_from_html(contact_html, found_data, search_email, search_phone, search_social)
                                
                                if found_data["email"]:
                                    sources.append(f"contact:{path}")
                                    break
                        except:
                            continue
                
            except PlaywrightTimeout:
                contact.partial_data = True
                contact.error_message = f"Timeout ({self.timeout}s)"
            except Exception as e:
                contact.error_message = f"Error navegación: {str(e)[:100]}"
            finally:
                # Cerrar página
                try:
                    await page.close()
                except:
                    pass
            
        except ImportError as e:
            contact.error_message = str(e)
        except Exception as e:
            contact.error_message = f"Error: {str(e)[:100]}"
        finally:
            # SIEMPRE cerrar browser para liberar memoria
            await self._close_browser()
        
        # Transferir datos
        self._populate_contact(contact, found_data)
        contact.source = " + ".join(sources) if sources else "none"
        
        # Determinar estado
        if contact.has_any_data():
            contact.extraction_success = True
            if contact.error_message and contact.has_contact_data():
                contact.partial_data = True
        
        return contact
    
    def extract(self, url: str, fields: List[str] = None) -> ContactData:
        """
        Versión síncrona de extract_async.
        """
        return asyncio.get_event_loop().run_until_complete(self.extract_async(url, fields))
    
    async def _get_footer_content(self, page: Page) -> Optional[str]:
        """Extrae el contenido del footer."""
        try:
            # Intentar múltiples selectores de footer
            selectors = [
                'footer',
                '[class*="footer"]',
                '[id*="footer"]',
                '[class*="contact"]',
                '[id*="contact"]'
            ]
            
            for selector in selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        return await element.inner_html()
                except:
                    continue
            
            return None
        except:
            return None
    
    def _extract_from_html(self, html: str, found_data: Dict, 
                          search_email: bool, search_phone: bool, search_social: bool):
        """Extrae datos de un bloque HTML."""
        
        # Buscar email
        if search_email and not found_data["email"]:
            # Primero buscar mailto: (más confiable)
            for match in self.MAILTO_REGEX.finditer(html):
                email = match.group(1)
                if self._is_valid_email(email):
                    found_data["email"] = email
                    break
            
            # Si no hay mailto, buscar en texto
            if not found_data["email"]:
                for match in self.EMAIL_REGEX.finditer(html):
                    email = match.group()
                    if self._is_valid_email(email):
                        found_data["email"] = email
                        break
        
        # Buscar teléfono
        if search_phone and not found_data["phone"]:
            # Primero buscar href="tel:"
            tel_match = self.TEL_REGEX.search(html)
            if tel_match:
                phone = tel_match.group(1)
                if self._is_valid_phone(phone):
                    found_data["phone"] = self._format_phone(phone)
            
            # Si no hay tel:, buscar en texto
            if not found_data["phone"]:
                for match in self.PHONE_REGEX.finditer(html):
                    phone = match.group()
                    if self._is_valid_phone(phone):
                        found_data["phone"] = self._format_phone(phone)
                        break
        
        # Buscar redes sociales
        if search_social:
            for platform, pattern in self.SOCIAL_PATTERNS.items():
                if not found_data[platform]:
                    match = pattern.search(html)
                    if match:
                        social_url = match.group()
                        if not social_url.startswith('http'):
                            social_url = 'https://' + social_url
                        found_data[platform] = re.sub(r'\?.*$', '', social_url)
    
    def _has_any_social(self, found_data: Dict) -> bool:
        return any([
            found_data["linkedin"], found_data["instagram"], found_data["twitter"],
            found_data["facebook"], found_data["youtube"], found_data["tiktok"]
        ])
    
    def _populate_contact(self, contact: ContactData, found_data: Dict):
        contact.title = found_data["title"]
        contact.email = found_data["email"]
        contact.phone = found_data["phone"]
        contact.linkedin = found_data["linkedin"]
        contact.instagram = found_data["instagram"]
        contact.twitter = found_data["twitter"]
        contact.facebook = found_data["facebook"]
        contact.youtube = found_data["youtube"]
        contact.tiktok = found_data["tiktok"]
        
        for platform in ["linkedin", "instagram", "twitter", "facebook", "youtube", "tiktok"]:
            if found_data[platform]:
                contact.social_media.append(found_data[platform])
    
    def _is_valid_email(self, email: str) -> bool:
        if not email:
            return False
        email_lower = email.lower()
        
        if '@' in email_lower:
            domain = email_lower.split('@')[1]
            if domain in self.EXCLUDED_DOMAINS:
                return False
            prefix = email_lower.split('@')[0]
            if any(prefix.startswith(excl) for excl in self.EXCLUDED_PREFIXES):
                return False
            if '.' not in domain:
                return False
        
        return True
    
    def _is_valid_phone(self, phone: str) -> bool:
        digits = re.sub(r'\D', '', phone)
        return 7 <= len(digits) <= 15
    
    def _format_phone(self, phone: str) -> str:
        return re.sub(r'\s+', ' ', phone.strip())
    
    def _extract_domain(self, url: str) -> str:
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except:
            return url


# Función de conveniencia para uso síncrono
def extract_contacts(url: str, fields: List[str] = None, timeout: int = 45) -> ContactData:
    """
    Extrae datos de contacto de una URL.
    
    Args:
        url: URL a extraer
        fields: Campos a buscar ['email', 'phone', 'social', 'title']
        timeout: Timeout en segundos
    
    Returns:
        ContactData con los datos encontrados
    """
    extractor = ContactExtractor(timeout=timeout)
    return extractor.extract(url, fields)


# Función async para uso en contextos async
async def extract_contacts_async(url: str, fields: List[str] = None, timeout: int = 45) -> ContactData:
    """Versión async de extract_contacts."""
    extractor = ContactExtractor(timeout=timeout)
    return await extractor.extract_async(url, fields)
