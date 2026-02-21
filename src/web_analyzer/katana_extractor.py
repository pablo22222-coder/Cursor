"""
Extractor de datos de contacto usando Katana (Ultra-Optimizado).
Extracción multicanal: Katana streaming + Footer + Páginas de contacto.

Comando: katana -u [URL] -d 2 -jc -silent -timeout 30 -extension-filter js,css,png,jpg,jpeg,gif,svg,woff,woff2,pdf,ico,json -f url

Optimizaciones:
- Filtro de extensiones para ignorar archivos basura
- Extracción paralela del footer (90% de contactos están ahí)
- Priorización de páginas /contacto, /contact, /about
- Early exit con email + red social
- Fallback a /contacto si no hay datos en 20s
"""
import subprocess
import re
import threading
import requests
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set
from urllib.parse import urlparse, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
import time


@dataclass
class ContactData:
    """Datos de contacto extraídos de una web."""
    domain: str
    url: str
    
    # Datos extraídos
    email: Optional[str] = None
    phone: Optional[str] = None
    
    # Redes sociales
    linkedin: Optional[str] = None
    instagram: Optional[str] = None
    twitter: Optional[str] = None
    facebook: Optional[str] = None
    youtube: Optional[str] = None
    tiktok: Optional[str] = None
    
    # Lista de todas las redes sociales encontradas
    social_media: List[str] = field(default_factory=list)
    
    # Estado
    extraction_success: bool = False
    partial_data: bool = False
    early_exit: bool = False
    source: str = ""  # Donde se encontraron los datos
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "url": self.url,
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
            "early_exit": self.early_exit,
            "source": self.source,
            "error_message": self.error_message
        }
    
    def has_any_data(self) -> bool:
        return bool(self.email or self.phone or self.social_media)
    
    def has_minimum_data(self) -> bool:
        """Email + al menos una red social."""
        return bool(self.email and self.social_media)
    
    def to_csv_row(self) -> Dict[str, str]:
        return {
            "domain": self.domain,
            "url": self.url,
            "email": self.email or "N/A",
            "phone": self.phone or "N/A",
            "linkedin": self.linkedin or "N/A",
            "instagram": self.instagram or "N/A",
            "twitter": self.twitter or "N/A",
            "facebook": self.facebook or "N/A",
            "youtube": self.youtube or "N/A",
            "tiktok": self.tiktok or "N/A"
        }


class KatanaExtractor:
    """
    Extractor ultra-optimizado con extracción multicanal.
    
    Canales de extracción:
    1. Streaming de URLs de Katana (con filtro de extensiones)
    2. Footer de la página principal (en paralelo)
    3. Páginas de contacto priorizadas
    4. Fallback a /contacto si no hay datos
    """
    
    # Regex para email
    EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
    
    # Regex para mailto: en URLs
    MAILTO_REGEX = re.compile(r'mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})')
    
    # Regex para redes sociales
    SOCIAL_REGEX = re.compile(
        r'(linkedin\.com/(?:company|in)/|instagram\.com/|facebook\.com/|'
        r'twitter\.com/|x\.com/|youtube\.com/(?:c/|channel/|user/|@)|tiktok\.com/@)[a-zA-Z0-9_.-]+',
        re.IGNORECASE
    )
    
    # Regex para teléfonos
    PHONE_REGEX = re.compile(r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}')
    
    # URLs prioritarias para contacto
    CONTACT_PATTERNS = ['contacto', 'contact', 'about', 'nosotros', 'legal', 'aviso', 'imprint', 'impressum']
    
    # Extensiones a filtrar (basura)
    EXTENSION_FILTER = "js,css,png,jpg,jpeg,gif,svg,woff,woff2,pdf,ico,json,xml,txt,map"
    
    # Emails a excluir
    EXCLUDED_EMAIL_DOMAINS = {
        "example.com", "example.org", "test.com", "email.com", "domain.com",
        "sentry.io", "wixpress.com", "w3.org", "schema.org", "googleusercontent.com",
        "gstatic.com", "gravatar.com", "wordpress.org", "wp.com", "jsdelivr.net",
        "cloudflare.com", "facebook.com", "twitter.com", "instagram.com"
    }
    
    EXCLUDED_EMAIL_PREFIXES = {'noreply', 'no-reply', 'donotreply', 'mailer-daemon', 'postmaster', 'webmaster'}
    
    def __init__(self, katana_timeout: int = 30, hard_timeout: int = 45,
                 fallback_timeout: int = 20, katana_path: str = "katana", depth: int = 2):
        """
        Args:
            katana_timeout: Timeout interno de Katana
            hard_timeout: Timeout máximo total
            fallback_timeout: Segundos sin datos antes de probar /contacto
            katana_path: Ruta al binario
            depth: Profundidad de rastreo
        """
        self.katana_timeout = katana_timeout
        self.hard_timeout = hard_timeout
        self.fallback_timeout = fallback_timeout
        self.katana_path = katana_path
        self.depth = depth
        
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def extract(self, url: str) -> ContactData:
        """
        Extrae datos de contacto con extracción multicanal.
        
        1. Inicia Katana streaming + fetch footer en paralelo
        2. Prioriza URLs de contacto
        3. Early exit con email + social
        4. Fallback a /contacto si no hay datos en 20s
        """
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        
        domain = self._extract_domain(url)
        contact = ContactData(domain=domain, url=url)
        
        found_data = {
            "email": None, "phone": None,
            "linkedin": None, "instagram": None, "twitter": None,
            "facebook": None, "youtube": None, "tiktok": None
        }
        
        process = None
        timer = None
        timed_out = False
        start_time = time.time()
        fallback_triggered = False
        sources = []
        
        def kill_process():
            nonlocal timed_out
            timed_out = True
            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.kill()
                except:
                    pass
        
        try:
            # === CANAL 1: Fetch footer en paralelo (muy rápido) ===
            with ThreadPoolExecutor(max_workers=2) as executor:
                footer_future = executor.submit(self._fetch_and_extract_footer, url, found_data)
                
                # === CANAL 2: Katana streaming con filtro de extensiones ===
                cmd = [
                    self.katana_path,
                    "-u", url,
                    "-d", str(self.depth),
                    "-jc",
                    "-silent",
                    "-timeout", str(self.katana_timeout),
                    "-extension-filter", self.EXTENSION_FILTER,
                    "-f", "url"
                ]
                
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1
                )
                
                # Hard timeout timer
                timer = threading.Timer(self.hard_timeout, kill_process)
                timer.start()
                
                contact_urls_to_fetch = []
                
                # Streaming de URLs de Katana
                for line in process.stdout:
                    if timed_out:
                        break
                    
                    line = line.strip()
                    if not line:
                        continue
                    
                    # Extraer de la URL misma (mailto:, redes sociales en URL)
                    self._extract_from_url(line, found_data)
                    
                    # Priorizar URLs de contacto
                    line_lower = line.lower()
                    if any(pattern in line_lower for pattern in self.CONTACT_PATTERNS):
                        if line not in contact_urls_to_fetch:
                            contact_urls_to_fetch.append(line)
                    
                    # Early exit
                    if found_data["email"] and self._has_any_social(found_data):
                        contact.early_exit = True
                        sources.append("katana_stream")
                        process.terminate()
                        break
                    
                    # Fallback a /contacto si no hay datos después de fallback_timeout
                    elapsed = time.time() - start_time
                    if elapsed > self.fallback_timeout and not self._has_any_data(found_data) and not fallback_triggered:
                        fallback_triggered = True
                        # Intentar /contacto en paralelo
                        executor.submit(self._fetch_contact_page, url, found_data)
                
                # Esperar resultado del footer
                try:
                    footer_result = footer_future.result(timeout=2)
                    if footer_result:
                        sources.append("footer")
                except:
                    pass
                
                # Si aún no tenemos datos completos, procesar URLs de contacto
                if not (found_data["email"] and self._has_any_social(found_data)):
                    for contact_url in contact_urls_to_fetch[:3]:  # Máximo 3 URLs
                        if timed_out:
                            break
                        try:
                            if self._fetch_and_extract_page(contact_url, found_data):
                                sources.append("contact_page")
                                if found_data["email"] and self._has_any_social(found_data):
                                    break
                        except:
                            pass
                
                # Último recurso: /contacto directo
                if not found_data["email"] and not timed_out:
                    if self._fetch_contact_page(url, found_data):
                        sources.append("fallback_contacto")
            
            # Cleanup proceso
            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=1)
                except:
                    process.kill()
                    
        except FileNotFoundError:
            contact.error_message = "Katana no encontrado"
            # Intentar solo con requests
            self._fetch_and_extract_footer(url, found_data)
            self._fetch_contact_page(url, found_data)
        except Exception as e:
            contact.error_message = f"Error: {str(e)}"
        finally:
            if timer:
                timer.cancel()
            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.kill()
                except:
                    pass
        
        # Transferir datos
        self._populate_contact(contact, found_data)
        contact.source = " + ".join(sources) if sources else "none"
        
        if timed_out:
            contact.error_message = f"Timeout ({self.hard_timeout}s)"
            contact.partial_data = contact.has_any_data()
        
        contact.extraction_success = contact.has_any_data()
        
        return contact
    
    def _fetch_and_extract_footer(self, url: str, found_data: Dict) -> bool:
        """
        Fetch rápido de la página principal y extracción del footer.
        El 90% de los datos de contacto están en el footer.
        """
        try:
            response = self.session.get(url, timeout=8, allow_redirects=True)
            if response.status_code != 200:
                return False
            
            html = response.text
            
            # Extraer contenido del footer
            footer_match = re.search(r'<footer[^>]*>(.*?)</footer>', html, re.DOTALL | re.IGNORECASE)
            if footer_match:
                footer_html = footer_match.group(1)
                self._extract_from_html(footer_html, found_data)
                if found_data["email"] or self._has_any_social(found_data):
                    return True
            
            # También buscar en secciones comunes de contacto
            contact_sections = re.findall(
                r'<(?:div|section)[^>]*(?:class|id)=["\'][^"\']*(?:contact|footer|social)[^"\']*["\'][^>]*>(.*?)</(?:div|section)>',
                html, re.DOTALL | re.IGNORECASE
            )
            for section in contact_sections[:3]:
                self._extract_from_html(section, found_data)
                if found_data["email"] and self._has_any_social(found_data):
                    return True
            
            # Buscar en todo el HTML si no encontramos nada
            if not found_data["email"]:
                self._extract_from_html(html, found_data)
            
            return bool(found_data["email"] or self._has_any_social(found_data))
            
        except Exception:
            return False
    
    def _fetch_contact_page(self, base_url: str, found_data: Dict) -> bool:
        """
        Intenta fetch de páginas de contacto comunes.
        """
        contact_paths = ['/contacto', '/contact', '/contactenos', '/about', '/sobre-nosotros', '/legal']
        
        for path in contact_paths:
            if found_data["email"] and self._has_any_social(found_data):
                return True
            
            try:
                contact_url = urljoin(base_url, path)
                if self._fetch_and_extract_page(contact_url, found_data):
                    return True
            except:
                continue
        
        return False
    
    def _fetch_and_extract_page(self, url: str, found_data: Dict) -> bool:
        """
        Fetch y extracción de una página específica.
        """
        try:
            response = self.session.get(url, timeout=5, allow_redirects=True)
            if response.status_code == 200:
                self._extract_from_html(response.text, found_data)
                return bool(found_data["email"] or self._has_any_social(found_data))
        except:
            pass
        return False
    
    def _extract_from_url(self, url: str, found_data: Dict):
        """
        Extrae datos directamente de una URL (mailto:, enlaces a redes sociales).
        """
        # Buscar mailto:
        if not found_data["email"]:
            mailto_match = self.MAILTO_REGEX.search(url)
            if mailto_match:
                email = mailto_match.group(1)
                if self._is_valid_email(email):
                    found_data["email"] = email
        
        # Buscar redes sociales en la URL
        self._extract_social_from_text(url, found_data)
    
    def _extract_from_html(self, html: str, found_data: Dict):
        """
        Extrae datos de un bloque de HTML.
        """
        # Buscar mailto: primero (más confiable)
        if not found_data["email"]:
            for mailto_match in self.MAILTO_REGEX.finditer(html):
                email = mailto_match.group(1)
                if self._is_valid_email(email):
                    found_data["email"] = email
                    break
        
        # Buscar emails en texto
        if not found_data["email"]:
            for email_match in self.EMAIL_REGEX.finditer(html):
                email = email_match.group()
                if self._is_valid_email(email):
                    found_data["email"] = email
                    break
        
        # Buscar teléfonos
        if not found_data["phone"]:
            # Buscar en href="tel:"
            tel_match = re.search(r'href=["\']tel:([^"\']+)["\']', html)
            if tel_match:
                phone = tel_match.group(1)
                if self._is_valid_phone(phone):
                    found_data["phone"] = self._format_phone(phone)
        
        # Buscar redes sociales
        self._extract_social_from_text(html, found_data)
    
    def _extract_social_from_text(self, text: str, found_data: Dict):
        """
        Extrae redes sociales de texto usando regex.
        """
        for match in self.SOCIAL_REGEX.finditer(text):
            social_url = match.group()
            self._categorize_social(social_url, found_data)
    
    def _categorize_social(self, url: str, found_data: Dict):
        """
        Categoriza y guarda una URL de red social.
        """
        url_lower = url.lower()
        
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        url = re.sub(r'\?.*$', '', url)  # Limpiar parámetros
        
        if 'linkedin.com/' in url_lower and not found_data["linkedin"]:
            found_data["linkedin"] = url
        elif 'instagram.com/' in url_lower and not found_data["instagram"]:
            found_data["instagram"] = url
        elif ('twitter.com/' in url_lower or 'x.com/' in url_lower) and not found_data["twitter"]:
            found_data["twitter"] = url
        elif 'facebook.com/' in url_lower and not found_data["facebook"]:
            found_data["facebook"] = url
        elif 'youtube.com/' in url_lower and not found_data["youtube"]:
            found_data["youtube"] = url
        elif 'tiktok.com/' in url_lower and not found_data["tiktok"]:
            found_data["tiktok"] = url
    
    def _has_any_social(self, found_data: Dict) -> bool:
        return any([
            found_data["linkedin"], found_data["instagram"], found_data["twitter"],
            found_data["facebook"], found_data["youtube"], found_data["tiktok"]
        ])
    
    def _has_any_data(self, found_data: Dict) -> bool:
        return bool(found_data["email"] or found_data["phone"] or self._has_any_social(found_data))
    
    def _populate_contact(self, contact: ContactData, found_data: Dict):
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
            if domain in self.EXCLUDED_EMAIL_DOMAINS:
                return False
            prefix = email_lower.split('@')[0]
            if any(prefix.startswith(excl) for excl in self.EXCLUDED_EMAIL_PREFIXES):
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


def extract_contacts(url: str, katana_timeout: int = 30, hard_timeout: int = 45) -> ContactData:
    """Función de conveniencia."""
    extractor = KatanaExtractor(katana_timeout=katana_timeout, hard_timeout=hard_timeout)
    return extractor.extract(url)
