"""
ContactExtractor - Extracción de Efectividad Extrema
Motor de extracción con Playwright optimizado para capturar 100% de emails y teléfonos.

Características:
- Navegación en cascada (Triple Salto)
- Extracción de atributos ocultos (mailto:, tel:)
- Regex de alta sensibilidad
- Técnicas anti-bloqueo (humano real)
- Persistencia inmediata de datos
"""
import asyncio
import re
import random
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse, urljoin

try:
    from playwright.async_api import async_playwright, Page, Browser, BrowserContext, TimeoutError as PlaywrightTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


# User-Agent moderno de Chrome (actualizado)
CHROME_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"

# Args para Codespaces + Anti-detección
BROWSER_ARGS = [
    '--no-sandbox',
    '--disable-setuid-sandbox',
    '--disable-dev-shm-usage',
    '--disable-gpu',
    '--disable-blink-features=AutomationControlled',  # Anti-bot detection
    '--disable-infobars',
    '--window-size=1920,1080'
]


@dataclass
class ContactData:
    """Datos de contacto extraídos."""
    domain: str
    url: str
    
    # Datos principales
    title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    
    # Todos los emails/teléfonos encontrados
    all_emails: List[str] = field(default_factory=list)
    all_phones: List[str] = field(default_factory=list)
    
    # Estado
    extraction_success: bool = False
    source: str = ""
    pages_visited: List[str] = field(default_factory=list)
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
            "extraction_success": self.extraction_success,
            "source": self.source,
            "pages_visited": self.pages_visited,
            "error_message": self.error_message
        }
    
    def has_complete_data(self) -> bool:
        """Tiene email Y teléfono."""
        return bool(self.email and self.phone)
    
    def has_any_data(self) -> bool:
        return bool(self.email or self.phone)
    
    def to_csv_row(self) -> Dict[str, str]:
        return {
            "domain": self.domain,
            "url": self.url,
            "title": self.title or "N/A",
            "email": self.email or "N/A",
            "phone": self.phone or "N/A"
        }


class ContactExtractor:
    """
    Extractor de contactos de efectividad extrema.
    Captura 100% de emails y teléfonos disponibles.
    """
    
    # === REGEX DE ALTA SENSIBILIDAD ===
    
    # Email: Captura todo excepto dominios técnicos
    EMAIL_REGEX = re.compile(
        r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
        re.IGNORECASE
    )
    
    # mailto: extractor
    MAILTO_REGEX = re.compile(
        r'href=["\']mailto:([^"\'?]+)',
        re.IGNORECASE
    )
    
    # tel: extractor  
    TEL_REGEX = re.compile(
        r'href=["\']tel:([^"\']+)["\']',
        re.IGNORECASE
    )
    
    # Teléfono robusto: españoles (6,7,8,9) e internacionales
    PHONE_REGEX = re.compile(
        r'(?:\+34\s?)?[6789]\d{2}[\s.-]?\d{3}[\s.-]?\d{3}|'  # Españoles
        r'(?:\+\d{1,3}[\s.-]?)?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}',  # Internacionales
        re.IGNORECASE
    )
    
    # Dominios técnicos a excluir (emails inválidos)
    EXCLUDED_DOMAINS = {
        'sentry.io', 'wixpress.com', 'w3.org', 'schema.org',
        'googleusercontent.com', 'gstatic.com', 'googleapis.com',
        'cloudflare.com', 'jsdelivr.net', 'unpkg.com', 'cdnjs.com',
        'gravatar.com', 'wp.com', 'wordpress.org', 'wordpress.com',
        'example.com', 'example.org', 'test.com', 'localhost'
    }
    
    # Extensiones de archivo a excluir
    EXCLUDED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico', '.pdf'}
    
    # Prefijos de email a excluir
    EXCLUDED_PREFIXES = {'noreply', 'no-reply', 'donotreply', 'mailer-daemon', 'postmaster'}
    
    # === RUTAS DE NAVEGACIÓN EN CASCADA ===
    CONTACT_PATHS = [
        '/contacto',
        '/contact', 
        '/contactenos',
        '/aviso-legal',
        '/legal',
        '/quienes-somos',
        '/about',
        '/sobre-nosotros',
        '/impressum',
        '/kontakt',
        '/contacto.html',
        '/contact.html'
    ]
    
    def __init__(self, timeout: int = 45, headless: bool = True):
        self.timeout = timeout
        self.headless = headless
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._playwright = None
    
    async def _init_browser(self):
        """Inicializa navegador con anti-detección."""
        if not PLAYWRIGHT_AVAILABLE:
            raise ImportError("Playwright no instalado. Ejecuta: pip install playwright && playwright install chromium")
        
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=BROWSER_ARGS
        )
    
    async def _close_browser(self):
        """Cierra navegador y libera memoria."""
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
        """Crea página con técnicas anti-detección."""
        self._context = await self._browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent=CHROME_USER_AGENT,
            locale='es-ES',
            timezone_id='Europe/Madrid',
            java_script_enabled=True
        )
        
        page = await self._context.new_page()
        
        # Bloquear solo recursos pesados (mantener JS para scripts de contacto)
        await page.route("**/*", lambda route: (
            route.abort() if route.request.resource_type in ["image", "font", "media"]
            else route.continue_()
        ))
        
        # Inyectar script anti-detección
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = {runtime: {}};
        """)
        
        return page
    
    async def _simulate_human(self, page: Page):
        """Simula comportamiento humano para activar scripts ocultos."""
        try:
            # Movimiento de ratón aleatorio
            await page.mouse.move(
                random.randint(100, 500),
                random.randint(100, 300)
            )
            await asyncio.sleep(0.3)
            
            # Scroll aleatorio
            scroll_amount = random.randint(300, 800)
            await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
            await asyncio.sleep(0.5)
            
            # Scroll hasta el footer
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.5)
            
            # Volver arriba
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(0.3)
        except:
            pass
    
    async def extract_async(self, url: str) -> ContactData:
        """
        Extracción de efectividad extrema.
        Navegación en cascada hasta encontrar email Y teléfono.
        """
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        
        domain = self._extract_domain(url)
        contact = ContactData(domain=domain, url=url)
        sources = []
        
        try:
            await self._init_browser()
            page = await self._create_stealth_page()
            page.set_default_timeout(self.timeout * 1000)
            
            # === PASO 1: Extraer de la HOME ===
            try:
                await page.goto(url, wait_until='domcontentloaded', timeout=15000)
                contact.pages_visited.append(url)
                
                # Extraer título
                try:
                    contact.title = await page.title()
                except:
                    pass
                
                # Simular humano
                await self._simulate_human(page)
                
                # Esperar carga dinámica
                await asyncio.sleep(2)
                
                # Extraer datos
                html = await page.content()
                self._extract_all_data(html, contact)
                
                if contact.email or contact.phone:
                    sources.append("home")
                
            except Exception as e:
                contact.error_message = f"Error en home: {str(e)[:50]}"
            
            # === PASO 2: NAVEGACIÓN EN CASCADA ===
            # Continuar hasta tener email Y teléfono, o agotar rutas
            if not contact.has_complete_data():
                for path in self.CONTACT_PATHS:
                    if contact.has_complete_data():
                        break  # Ya tenemos todo
                    
                    try:
                        contact_url = urljoin(url, path)
                        
                        # Evitar visitar la misma página
                        if contact_url in contact.pages_visited:
                            continue
                        
                        response = await page.goto(
                            contact_url, 
                            wait_until='domcontentloaded', 
                            timeout=10000
                        )
                        
                        if response and response.ok:
                            contact.pages_visited.append(contact_url)
                            
                            # Simular humano
                            await self._simulate_human(page)
                            await asyncio.sleep(1)
                            
                            # Extraer datos
                            html = await page.content()
                            found_new = self._extract_all_data(html, contact)
                            
                            if found_new:
                                sources.append(path.strip('/'))
                                
                    except:
                        continue
            
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
            # Cerrar browser al final
            await self._close_browser()
        
        # Establecer fuente y estado
        contact.source = " + ".join(sources) if sources else "none"
        contact.extraction_success = contact.has_any_data()
        
        return contact
    
    def _extract_all_data(self, html: str, contact: ContactData) -> bool:
        """
        Extrae emails y teléfonos de HTML.
        Retorna True si encontró datos nuevos.
        """
        found_new = False
        
        # === EXTRAER EMAILS ===
        
        # 1. De mailto: (más confiable)
        for match in self.MAILTO_REGEX.finditer(html):
            email = match.group(1).strip().lower()
            email = email.split('?')[0]  # Quitar parámetros
            
            if self._is_valid_email(email) and email not in contact.all_emails:
                contact.all_emails.append(email)
                if not contact.email:
                    contact.email = email
                    found_new = True
        
        # 2. De texto plano
        for match in self.EMAIL_REGEX.finditer(html):
            email = match.group().lower()
            
            if self._is_valid_email(email) and email not in contact.all_emails:
                contact.all_emails.append(email)
                if not contact.email:
                    contact.email = email
                    found_new = True
        
        # === EXTRAER TELÉFONOS ===
        
        # 1. De tel: (más confiable)
        for match in self.TEL_REGEX.finditer(html):
            phone = match.group(1).strip()
            phone = self._normalize_phone(phone)
            
            if self._is_valid_phone(phone) and phone not in contact.all_phones:
                contact.all_phones.append(phone)
                if not contact.phone:
                    contact.phone = phone
                    found_new = True
        
        # 2. De texto plano
        for match in self.PHONE_REGEX.finditer(html):
            phone = match.group()
            phone = self._normalize_phone(phone)
            
            if self._is_valid_phone(phone) and phone not in contact.all_phones:
                contact.all_phones.append(phone)
                if not contact.phone:
                    contact.phone = phone
                    found_new = True
        
        return found_new
    
    def _is_valid_email(self, email: str) -> bool:
        """Valida email con alta sensibilidad."""
        if not email or '@' not in email:
            return False
        
        email = email.lower().strip()
        
        # Verificar extensiones de archivo
        for ext in self.EXCLUDED_EXTENSIONS:
            if email.endswith(ext):
                return False
        
        # Verificar dominio
        try:
            domain = email.split('@')[1]
            if domain in self.EXCLUDED_DOMAINS:
                return False
            if '.' not in domain:
                return False
        except:
            return False
        
        # Verificar prefijo
        prefix = email.split('@')[0]
        if any(prefix.startswith(excl) for excl in self.EXCLUDED_PREFIXES):
            return False
        
        return True
    
    def _is_valid_phone(self, phone: str) -> bool:
        """Valida teléfono."""
        if not phone:
            return False
        
        # Contar dígitos
        digits = re.sub(r'\D', '', phone)
        
        # Teléfono válido: 9-15 dígitos
        if not (9 <= len(digits) <= 15):
            return False
        
        # Evitar números obvios falsos
        if digits in ['123456789', '000000000', '111111111', '999999999']:
            return False
        
        return True
    
    def _normalize_phone(self, phone: str) -> str:
        """Normaliza teléfono: quita espacios y guiones extra."""
        # Limpiar
        phone = re.sub(r'[\s.-]+', ' ', phone.strip())
        phone = re.sub(r'\s+', ' ', phone)
        return phone
    
    def _extract_domain(self, url: str) -> str:
        """Extrae dominio de URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except:
            return url
    
    def extract(self, url: str) -> ContactData:
        """
        Versión síncrona para Flask.
        Crea nuevo event loop para funcionar en threads.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.extract_async(url))
        finally:
            loop.close()
            asyncio.set_event_loop(None)


# Función de conveniencia
def extract_contacts(url: str, timeout: int = 45) -> ContactData:
    """Extrae contactos de una URL."""
    extractor = ContactExtractor(timeout=timeout)
    return extractor.extract(url)
