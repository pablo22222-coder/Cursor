"""
ParallelDomainAnalyzer - Análisis de dominios con 3 Workers concurrentes
Usa asyncio.Semaphore(3) para procesar hasta 3 dominios simultáneamente.

Arquitectura:
- Semaphore limita a 3 workers activos
- Cada worker gestiona su propia instancia de Playwright
- Limpieza automática de recursos al terminar
"""
import asyncio
import re
import ssl
import socket
import subprocess
import json
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from urllib.parse import urlparse, urljoin
import aiohttp

try:
    from playwright.async_api import async_playwright, Page, Browser
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


MAX_WORKERS = 3
MAX_DOMAINS = 30
WAPPALYZER_TIMEOUT = 10
PAGE_TIMEOUT = 15000


@dataclass
class DomainResult:
    """Resultado del análisis de un dominio."""
    domain: str
    url: str
    success: bool = False
    
    http_status: Optional[int] = None
    final_url: Optional[str] = None
    redirects: List[Dict[str, Any]] = field(default_factory=list)
    
    ssl_info: Optional[Dict[str, Any]] = None
    
    metadata: Dict[str, Any] = field(default_factory=dict)
    language: Optional[str] = None
    
    technologies: List[str] = field(default_factory=list)
    
    contact: Dict[str, Any] = field(default_factory=dict)
    
    pages: List[Dict[str, str]] = field(default_factory=list)
    
    error: Optional[str] = None
    processing_time: float = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "url": self.url,
            "success": self.success,
            "http_status": self.http_status,
            "final_url": self.final_url,
            "redirects": self.redirects,
            "ssl": self.ssl_info,
            "metadata": self.metadata,
            "language": self.language,
            "technologies": self.technologies,
            "contact": self.contact,
            "pages": self.pages,
            "error": self.error,
            "processing_time": round(self.processing_time, 2)
        }


class ParallelDomainAnalyzer:
    """
    Analizador de dominios con procesamiento paralelo (3 Workers).
    
    Características:
    - Semaphore para limitar a 3 workers concurrentes
    - Cada worker tiene su propia instancia de Playwright
    - Wappalyzer con timeout de 10s
    - Extracción Triple Salto (Home, Contacto, Legal)
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
    
    CONTACT_PATHS = ['/contacto', '/contact', '/aviso-legal', '/legal', '/about', '/quienes-somos']
    
    BROWSER_ARGS = [
        '--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage',
        '--disable-gpu', '--disable-blink-features=AutomationControlled'
    ]
    
    def __init__(self, max_workers: int = MAX_WORKERS, on_progress: Callable = None):
        self.max_workers = max_workers
        self.semaphore = None
        self.on_progress = on_progress
        self.completed = 0
        self.total = 0
    
    async def analyze_domains(self, domains: List[str]) -> List[DomainResult]:
        """
        Analiza múltiples dominios en paralelo con máximo 3 workers.
        
        Args:
            domains: Lista de dominios (máximo 30)
        
        Returns:
            Lista de resultados de análisis
        """
        # Limitar a MAX_DOMAINS
        domains = domains[:MAX_DOMAINS]
        self.total = len(domains)
        self.completed = 0
        
        # Crear semáforo para limitar workers
        self.semaphore = asyncio.Semaphore(self.max_workers)
        
        # Crear tareas para cada dominio
        tasks = [self._analyze_with_semaphore(domain, i) for i, domain in enumerate(domains)]
        
        # Ejecutar todas las tareas
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Procesar resultados
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append(DomainResult(
                    domain=domains[i],
                    url=f"https://{domains[i]}",
                    success=False,
                    error=str(result)
                ))
            else:
                final_results.append(result)
        
        return final_results
    
    async def _analyze_with_semaphore(self, domain: str, index: int) -> DomainResult:
        """Analiza un dominio respetando el semáforo."""
        async with self.semaphore:
            result = await self._analyze_single_domain(domain)
            
            self.completed += 1
            if self.on_progress:
                progress = int((self.completed / self.total) * 100)
                self.on_progress(progress, f"Analizando {domain}...", self.completed, self.total)
            
            return result
    
    async def _analyze_single_domain(self, domain: str) -> DomainResult:
        """Análisis completo de un solo dominio."""
        import time
        start_time = time.time()
        
        # Normalizar URL
        if not domain.startswith(('http://', 'https://')):
            url = f'https://{domain}'
        else:
            url = domain
            domain = urlparse(url).netloc
            if domain.startswith('www.'):
                domain = domain[4:]
        
        result = DomainResult(domain=domain, url=url)
        
        try:
            # 1. HTTP Status (async)
            await self._check_http_async(result)
            
            # 2. SSL Certificate
            await self._check_ssl(result)
            
            # 3. Wappalyzer (10s timeout)
            await self._analyze_technologies(result)
            
            # 4. Playwright: Triple Salto
            await self._analyze_with_playwright(result)
            
            result.success = True
            
        except Exception as e:
            result.error = str(e)[:100]
            result.success = False
        
        result.processing_time = time.time() - start_time
        return result
    
    async def _check_http_async(self, result: DomainResult):
        """Check HTTP status asíncronamente."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.head(
                    result.url,
                    allow_redirects=True,
                    timeout=aiohttp.ClientTimeout(total=10),
                    headers={'User-Agent': 'Mozilla/5.0 Chrome/121.0.0.0'}
                ) as response:
                    result.http_status = response.status
                    result.final_url = str(response.url)
                    
                    # Track redirects
                    if response.history:
                        for r in response.history:
                            result.redirects.append({
                                'status': r.status,
                                'url': str(r.url)
                            })
        except Exception as e:
            result.http_status = None
            result.error = f"HTTP: {str(e)[:30]}"
    
    async def _check_ssl(self, result: DomainResult):
        """Check SSL certificate."""
        try:
            parsed = urlparse(result.url)
            hostname = parsed.netloc
            
            def get_ssl_info():
                context = ssl.create_default_context()
                with socket.create_connection((hostname, 443), timeout=5) as sock:
                    with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                        cert = ssock.getpeercert()
                        return {
                            'valid': True,
                            'issuer': dict(x[0] for x in cert.get('issuer', [])).get('organizationName', 'Unknown'),
                            'expires': cert.get('notAfter', 'Unknown'),
                            'protocol': ssock.version()
                        }
            
            # Run in executor to not block
            loop = asyncio.get_event_loop()
            result.ssl_info = await loop.run_in_executor(None, get_ssl_info)
            
        except Exception as e:
            result.ssl_info = {'valid': False, 'error': str(e)[:50]}
    
    async def _analyze_technologies(self, result: DomainResult):
        """Wappalyzer con timeout de 10 segundos."""
        try:
            def run_wappalyzer():
                try:
                    process = subprocess.run(
                        ['wappalyzergo', '-u', result.url, '-td', '-json', '-fr'],
                        capture_output=True,
                        text=True,
                        timeout=WAPPALYZER_TIMEOUT
                    )
                    
                    if process.returncode == 0 and process.stdout:
                        data = json.loads(process.stdout)
                        if isinstance(data, dict):
                            for url_data in data.values():
                                if isinstance(url_data, dict) and 'tech' in url_data:
                                    return url_data['tech']
                        elif isinstance(data, list):
                            return data
                except subprocess.TimeoutExpired:
                    pass
                except json.JSONDecodeError:
                    pass
                except FileNotFoundError:
                    pass
                return []
            
            loop = asyncio.get_event_loop()
            result.technologies = await loop.run_in_executor(None, run_wappalyzer)
            
        except Exception:
            result.technologies = []
    
    async def _analyze_with_playwright(self, result: DomainResult):
        """Extracción Triple Salto con Playwright."""
        if not PLAYWRIGHT_AVAILABLE:
            return
        
        playwright = None
        browser = None
        
        try:
            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(
                headless=True,
                args=self.BROWSER_ARGS
            )
            
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/121.0.0.0',
                locale='es-ES'
            )
            
            page = await context.new_page()
            page.set_default_timeout(PAGE_TIMEOUT)
            
            # Block heavy resources
            await page.route("**/*", lambda route: (
                route.abort() if route.request.resource_type in ["image", "font", "media"]
                else route.continue_()
            ))
            
            # === TRIPLE SALTO ===
            
            # 1. HOME
            try:
                await page.goto(result.url, wait_until='domcontentloaded', timeout=PAGE_TIMEOUT)
                
                # Metadata
                result.metadata = await self._extract_metadata(page)
                result.language = await self._detect_language(page)
                
                # Contacts
                html = await page.content()
                self._extract_contacts(html, result)
                
                # Important pages
                await self._find_pages(page, result)
                
            except Exception:
                pass
            
            # 2. CONTACT PAGES (si no tenemos email)
            if not result.contact.get('email'):
                for path in self.CONTACT_PATHS[:3]:  # Primeros 3
                    try:
                        contact_url = urljoin(result.url, path)
                        response = await page.goto(contact_url, wait_until='domcontentloaded', timeout=8000)
                        if response and response.ok:
                            html = await page.content()
                            self._extract_contacts(html, result)
                            if result.contact.get('email'):
                                break
                    except:
                        continue
            
            await context.close()
            
        except Exception as e:
            if not result.error:
                result.error = f"Playwright: {str(e)[:50]}"
        finally:
            # Limpieza de recursos
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
    
    async def _extract_metadata(self, page: Page) -> Dict[str, Any]:
        """Extract page metadata."""
        metadata = {}
        try:
            metadata['title'] = await page.title()
            
            desc = await page.query_selector('meta[name="description"]')
            if desc:
                metadata['description'] = await desc.get_attribute('content')
            
            og_title = await page.query_selector('meta[property="og:title"]')
            if og_title:
                metadata['og_title'] = await og_title.get_attribute('content')
                
        except:
            pass
        return metadata
    
    async def _detect_language(self, page: Page) -> Optional[str]:
        """Detect page language."""
        try:
            html_el = await page.query_selector('html')
            if html_el:
                lang = await html_el.get_attribute('lang')
                if lang:
                    return lang[:2].lower()
        except:
            pass
        return None
    
    def _extract_contacts(self, html: str, result: DomainResult):
        """Extract contact information."""
        contact = result.contact
        
        # Emails
        for match in self.MAILTO_REGEX.finditer(html):
            email = match.group(1).strip().lower().split('?')[0]
            if self._is_valid_email(email):
                if 'email' not in contact:
                    contact['email'] = email
                if 'all_emails' not in contact:
                    contact['all_emails'] = []
                if email not in contact['all_emails']:
                    contact['all_emails'].append(email)
        
        for match in self.EMAIL_REGEX.finditer(html):
            email = match.group().lower()
            if self._is_valid_email(email):
                if 'email' not in contact:
                    contact['email'] = email
                if 'all_emails' not in contact:
                    contact['all_emails'] = []
                if email not in contact['all_emails']:
                    contact['all_emails'].append(email)
        
        # Phones
        for match in self.TEL_REGEX.finditer(html):
            phone = match.group(1).strip()
            phone = re.sub(r'[\s.-]+', ' ', phone)
            if len(re.sub(r'\D', '', phone)) >= 9:
                if 'phone' not in contact:
                    contact['phone'] = phone
        
        for match in self.PHONE_REGEX.finditer(html):
            phone = re.sub(r'[\s.-]+', ' ', match.group())
            if len(re.sub(r'\D', '', phone)) >= 9:
                if 'phone' not in contact:
                    contact['phone'] = phone
        
        # Social media
        if 'social_media' not in contact:
            contact['social_media'] = []
        
        found_urls = {s['url'] for s in contact['social_media']}
        
        for platform, pattern in self.SOCIAL_PATTERNS.items():
            for match in pattern.finditer(html):
                url = match.group()
                if url not in found_urls and 'share' not in url.lower():
                    contact['social_media'].append({'platform': platform, 'url': url})
                    found_urls.add(url)
        
        result.contact = contact
    
    def _is_valid_email(self, email: str) -> bool:
        """Comprobación mínima de formato. Conservamos todos los emails
        detectados por EMAIL_REGEX sin filtrado de calidad adicional."""
        return bool(email) and '@' in email
    
    async def _find_pages(self, page: Page, result: DomainResult):
        """Find important pages."""
        important = {
            '/contacto': 'Contacto', '/contact': 'Contact',
            '/about': 'About', '/servicios': 'Servicios',
            '/aviso-legal': 'Aviso Legal', '/privacidad': 'Privacidad'
        }
        
        try:
            links = await page.query_selector_all('a[href]')
            found = set()
            
            for link in links[:50]:
                try:
                    href = await link.get_attribute('href')
                    if href:
                        for path, title in important.items():
                            if path in href.lower() and path not in found:
                                result.pages.append({
                                    'path': path,
                                    'title': title,
                                    'url': urljoin(result.url, href)
                                })
                                found.add(path)
                except:
                    continue
        except:
            pass


def analyze_domains_parallel(domains: List[str], on_progress: Callable = None) -> List[Dict]:
    """
    Función de conveniencia para análisis paralelo.
    Crea su propio event loop para uso desde Flask.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        analyzer = ParallelDomainAnalyzer(on_progress=on_progress)
        results = loop.run_until_complete(analyzer.analyze_domains(domains))
        return [r.to_dict() for r in results]
    finally:
        loop.close()
        asyncio.set_event_loop(None)
