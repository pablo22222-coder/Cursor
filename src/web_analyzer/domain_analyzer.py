"""
DomainAnalyzer - Auditoría técnica completa + Sales Triggers de un dominio.

Este módulo es el motor del modo "Analizar a fondo" (inspect).
Ejecuta en orden:
  1. HTTP status + redirects (requests.head)
  2. SSL certificate (socket + ssl)
  3. Wappalyzer (subprocess, 30s timeout)
  4. Playwright: metadata, contactos, páginas
  5. Sales Triggers: WHOIS, DNS/MX, píxeles, lead magnets,
     pop-ups, H1, meta-tags, blog, RRSS, idioma, sitemap, ads.txt,
     e-commerce reviews, alertas de prioridad.

El buscador de dominios (domain_pipeline.py) NO ejecuta Sales Triggers
— sólo valida, detecta tech y extrae contacto. Cada auditoría profunda
se lanza desde el endpoint /inspect/<domain>.
"""
import asyncio
import re
import ssl
import socket
import requests
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse, urljoin
import subprocess
import json

try:
    from playwright.async_api import async_playwright, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


@dataclass
class DomainAnalysis:
    """Resultado del análisis completo de un dominio."""
    domain: str
    url: str
    success: bool = False

    # HTTP Info
    http_status: Optional[int] = None
    final_url: Optional[str] = None
    redirects: List[Dict[str, Any]] = field(default_factory=list)

    # SSL
    ssl: Optional[Dict[str, Any]] = None

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    language: Optional[str] = None

    # Technologies (Wappalyzer)
    technologies: List[str] = field(default_factory=list)

    # Contact
    contact: Dict[str, Any] = field(default_factory=dict)

    # Pages
    pages: List[Dict[str, str]] = field(default_factory=list)

    # Sales Triggers (deep audit — populated by analyze_sales_triggers)
    sales_triggers: Optional[Dict[str, Any]] = None

    # Error
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain":        self.domain,
            "url":           self.url,
            "success":       self.success,
            "http_status":   self.http_status,
            "final_url":     self.final_url,
            "redirects":     self.redirects,
            "ssl":           self.ssl,
            "metadata":      self.metadata,
            "language":      self.language,
            "technologies":  self.technologies,
            "contact":       self.contact,
            "pages":         self.pages,
            "sales_triggers":self.sales_triggers,
            "error":         self.error,
        }


class DomainAnalyzer:
    """
    Analizador completo de dominios.
    - Wappalyzer: tecnologías (10s timeout)
    - Playwright: contactos, metadata, páginas
    - HTTP: status, redirecciones
    - SSL: certificado
    """
    
    WAPPALYZER_TIMEOUT = 30  # seconds per domain (deep audit)
    
    # Contact patterns
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
    
    EXCLUDED_DOMAINS = {
        'sentry.io', 'wixpress.com', 'w3.org', 'schema.org', 'example.com',
        'googleusercontent.com', 'gstatic.com', 'googleapis.com', 'cloudflare.com'
    }
    
    CONTACT_PATHS = ['/contacto', '/contact', '/aviso-legal', '/legal', '/about', '/quienes-somos']
    
    BROWSER_ARGS = [
        '--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage',
        '--disable-gpu', '--disable-blink-features=AutomationControlled'
    ]
    
    def __init__(self):
        self._playwright = None
        self._browser = None
    
    async def analyze_domain(self, domain: str) -> DomainAnalysis:
        """
        Auditoría completa de un dominio (modo 'Analizar a fondo').

        Fases:
          1. HTTP Status & Redirects
          2. SSL Certificate
          3. Wappalyzer (30s timeout)
          4. Playwright: metadata, contacts, pages
          5. Sales Triggers: WHOIS, DNS/MX, píxeles, SEO, blog, RRSS,
             sitemap, ads.txt, e-commerce reviews, alertas de prioridad
        """
        if not domain.startswith(('http://', 'https://')):
            url = f'https://{domain}'
        else:
            url = domain
            domain = urlparse(url).netloc
            if domain.startswith('www.'):
                domain = domain[4:]

        result = DomainAnalysis(domain=domain, url=url)

        try:
            # 1. HTTP Status & Redirects
            await self._check_http(result)

            # 2. SSL Certificate
            await self._check_ssl(result)

            # 3. Wappalyzer (30s timeout — upgraded from 10s)
            await self._analyze_technologies(result)

            # 4. Playwright: metadata, contacts, pages
            await self._analyze_with_playwright(result)

            # 5. Sales Triggers deep audit (WHOIS, DNS, píxeles, SEO, blog…)
            try:
                from src.web_analyzer.sales_triggers import analyze_sales_triggers
                # Build tech_profile from wappalyzer data for reuse
                tech_profile = None
                if result.technologies:
                    tech_profile = {"all_techs": result.technologies}
                result.sales_triggers = analyze_sales_triggers(
                    result.final_url or result.url,
                    tech_profile=tech_profile,
                )
            except Exception as st_err:
                result.sales_triggers = {"error": str(st_err)[:120], "alerts": []}

            result.success = True

        except Exception as e:
            result.error = str(e)
            result.success = False
        
        return result
    
    async def _check_http(self, result: DomainAnalysis):
        """Check HTTP status and redirects."""
        try:
            response = requests.head(
                result.url,
                allow_redirects=True,
                timeout=10,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/121.0.0.0'}
            )
            
            result.http_status = response.status_code
            result.final_url = response.url
            
            # Track redirects
            if response.history:
                for r in response.history:
                    result.redirects.append({
                        'status': r.status_code,
                        'url': r.url
                    })
        except requests.RequestException as e:
            result.http_status = None
            result.error = f"HTTP error: {str(e)[:50]}"
    
    async def _check_ssl(self, result: DomainAnalysis):
        """Check SSL certificate."""
        try:
            parsed = urlparse(result.url)
            hostname = parsed.netloc
            
            context = ssl.create_default_context()
            with socket.create_connection((hostname, 443), timeout=5) as sock:
                with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                    cert = ssock.getpeercert()
                    
                    result.ssl = {
                        'valid': True,
                        'issuer': dict(x[0] for x in cert.get('issuer', [])).get('organizationName', 'Unknown'),
                        'expires': cert.get('notAfter', 'Unknown'),
                        'protocol': ssock.version()
                    }
        except Exception as e:
            result.ssl = {
                'valid': False,
                'error': str(e)[:50]
            }
    
    async def _analyze_technologies(self, result: DomainAnalysis):
        """Analyze technologies with Wappalyzer (10s timeout)."""
        try:
            cmd = ['wappalyzergo', '-u', result.url, '-td', '-json', '-fr']
            
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.WAPPALYZER_TIMEOUT
            )
            
            if process.returncode == 0 and process.stdout:
                try:
                    data = json.loads(process.stdout)
                    
                    # Extract technologies
                    if isinstance(data, dict):
                        for url_data in data.values():
                            if isinstance(url_data, dict) and 'tech' in url_data:
                                result.technologies = url_data['tech']
                                break
                    elif isinstance(data, list):
                        result.technologies = data
                        
                except json.JSONDecodeError:
                    pass
                    
        except subprocess.TimeoutExpired:
            result.technologies = []
        except FileNotFoundError:
            pass
        except Exception:
            pass
    
    async def _analyze_with_playwright(self, result: DomainAnalysis):
        """Extract metadata, contacts and pages with Playwright."""
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
            page.set_default_timeout(15000)
            
            # Block heavy resources
            await page.route("**/*", lambda route: (
                route.abort() if route.request.resource_type in ["image", "font", "media"]
                else route.continue_()
            ))
            
            # Navigate to main page
            try:
                await page.goto(result.url, wait_until='domcontentloaded', timeout=15000)
            except:
                return
            
            # Extract metadata
            result.metadata = await self._extract_metadata(page)
            
            # Detect language
            result.language = await self._detect_language(page)
            
            # Extract contacts from homepage
            html = await page.content()
            self._extract_contacts(html, result)
            
            # Find important pages
            await self._find_pages(page, result)
            
            # Visit contact pages if no email found
            if not result.contact.get('email'):
                for path in self.CONTACT_PATHS:
                    try:
                        contact_url = urljoin(result.url, path)
                        response = await page.goto(contact_url, wait_until='domcontentloaded', timeout=10000)
                        if response and response.ok:
                            html = await page.content()
                            self._extract_contacts(html, result)
                            if result.contact.get('email'):
                                break
                    except:
                        continue
            
            await context.close()
            
        except Exception as e:
            result.error = f"Playwright error: {str(e)[:50]}"
        finally:
            if browser:
                await browser.close()
            if playwright:
                await playwright.stop()
    
    async def _extract_metadata(self, page: Page) -> Dict[str, Any]:
        """Extract page metadata."""
        metadata = {}
        
        try:
            # Title
            metadata['title'] = await page.title()
            
            # Meta description
            desc = await page.query_selector('meta[name="description"]')
            if desc:
                metadata['description'] = await desc.get_attribute('content')
            
            # OG tags
            og_title = await page.query_selector('meta[property="og:title"]')
            if og_title:
                metadata['og_title'] = await og_title.get_attribute('content')
            
            og_desc = await page.query_selector('meta[property="og:description"]')
            if og_desc:
                metadata['og_description'] = await og_desc.get_attribute('content')
            
            # Keywords
            keywords = await page.query_selector('meta[name="keywords"]')
            if keywords:
                metadata['keywords'] = await keywords.get_attribute('content')
                
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
    
    def _extract_contacts(self, html: str, result: DomainAnalysis):
        """Extract contact information from HTML."""
        contact = result.contact
        
        # Emails from mailto
        for match in self.MAILTO_REGEX.finditer(html):
            email = match.group(1).strip().lower().split('?')[0]
            if self._is_valid_email(email):
                if 'email' not in contact:
                    contact['email'] = email
                if 'all_emails' not in contact:
                    contact['all_emails'] = []
                if email not in contact['all_emails']:
                    contact['all_emails'].append(email)
        
        # Emails from text
        for match in self.EMAIL_REGEX.finditer(html):
            email = match.group().lower()
            if self._is_valid_email(email):
                if 'email' not in contact:
                    contact['email'] = email
                if 'all_emails' not in contact:
                    contact['all_emails'] = []
                if email not in contact['all_emails']:
                    contact['all_emails'].append(email)
        
        # Phones from tel
        for match in self.TEL_REGEX.finditer(html):
            phone = match.group(1).strip()
            phone = re.sub(r'[\s.-]+', ' ', phone)
            if len(re.sub(r'\D', '', phone)) >= 9:
                if 'phone' not in contact:
                    contact['phone'] = phone
        
        # Phones from text
        for match in self.PHONE_REGEX.finditer(html):
            phone = match.group()
            phone = re.sub(r'[\s.-]+', ' ', phone)
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
                if url not in found_urls and not any(x in url.lower() for x in ['share', 'intent', 'dialog']):
                    contact['social_media'].append({'platform': platform, 'url': url})
                    found_urls.add(url)
        
        result.contact = contact
    
    def _is_valid_email(self, email: str) -> bool:
        """Validate email."""
        if not email or '@' not in email:
            return False
        domain = email.split('@')[1]
        if domain in self.EXCLUDED_DOMAINS:
            return False
        if any(email.endswith(ext) for ext in ['.png', '.jpg', '.gif', '.svg']):
            return False
        return True
    
    async def _find_pages(self, page: Page, result: DomainAnalysis):
        """Find important pages."""
        important_paths = {
            '/contacto': 'Contacto',
            '/contact': 'Contact',
            '/about': 'Acerca de',
            '/quienes-somos': 'Quiénes somos',
            '/servicios': 'Servicios',
            '/services': 'Services',
            '/productos': 'Productos',
            '/products': 'Products',
            '/aviso-legal': 'Aviso Legal',
            '/legal': 'Legal',
            '/privacidad': 'Privacidad',
            '/privacy': 'Privacy'
        }
        
        try:
            links = await page.query_selector_all('a[href]')
            found_paths = set()
            
            for link in links[:100]:  # Limit to first 100 links
                try:
                    href = await link.get_attribute('href')
                    if href:
                        for path, title in important_paths.items():
                            if path in href.lower() and path not in found_paths:
                                full_url = urljoin(result.url, href)
                                result.pages.append({
                                    'path': path,
                                    'title': title,
                                    'url': full_url
                                })
                                found_paths.add(path)
                except:
                    continue
        except:
            pass
    
    def analyze_sync(self, domain: str) -> DomainAnalysis:
        """Synchronous wrapper for Flask."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.analyze_domain(domain))
        finally:
            loop.close()
            asyncio.set_event_loop(None)


def analyze_domain(domain: str) -> Dict[str, Any]:
    """Convenience function to analyze a single domain."""
    analyzer = DomainAnalyzer()
    result = analyzer.analyze_sync(domain)
    return result.to_dict()
