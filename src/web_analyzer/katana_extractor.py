"""
Extractor de datos de contacto usando Katana.
Ejecuta el binario katana via subprocess para extraer emails, teléfonos y redes sociales.

Comando: katana -u [URL] -d 2 -jc -field email,social_media,phone,title -j

Katana rastrea la web hasta 2 niveles de profundidad, analiza archivos JavaScript,
y extrae datos de contacto estructurados en formato JSON.
"""
import subprocess
import json
import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set
from urllib.parse import urlparse


@dataclass
class ContactData:
    """Datos de contacto extraídos de una web."""
    domain: str
    url: str
    
    # Datos extraídos
    email: Optional[str] = None
    phone: Optional[str] = None
    title: Optional[str] = None
    
    # Redes sociales (una de cada)
    linkedin: Optional[str] = None
    instagram: Optional[str] = None
    twitter: Optional[str] = None
    facebook: Optional[str] = None
    youtube: Optional[str] = None
    tiktok: Optional[str] = None
    
    # Lista completa de redes sociales encontradas
    social_media: List[str] = field(default_factory=list)
    
    # Listas completas (por si se necesitan)
    all_emails: List[str] = field(default_factory=list)
    all_phones: List[str] = field(default_factory=list)
    
    # Estado
    extraction_success: bool = False
    partial_data: bool = False
    error_message: Optional[str] = None
    raw_output: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "url": self.url,
            "email": self.email,
            "phone": self.phone,
            "title": self.title,
            "linkedin": self.linkedin,
            "instagram": self.instagram,
            "twitter": self.twitter,
            "facebook": self.facebook,
            "youtube": self.youtube,
            "tiktok": self.tiktok,
            "social_media": self.social_media,
            "extraction_success": self.extraction_success,
            "partial_data": self.partial_data,
            "error_message": self.error_message
        }
    
    def has_any_data(self) -> bool:
        """Verifica si se extrajo algún dato."""
        return bool(
            self.email or 
            self.phone or 
            self.title or 
            self.social_media
        )
    
    def get_primary_social(self) -> Optional[str]:
        """Retorna la red social principal (LinkedIn > Instagram > Twitter > Facebook)."""
        return self.linkedin or self.instagram or self.twitter or self.facebook or self.youtube
    
    def to_csv_row(self) -> Dict[str, str]:
        """Retorna los datos formateados para CSV."""
        return {
            "domain": self.domain,
            "url": self.url,
            "title": self.title or "",
            "email": self.email or "",
            "phone": self.phone or "",
            "linkedin": self.linkedin or "",
            "instagram": self.instagram or "",
            "twitter": self.twitter or "",
            "facebook": self.facebook or "",
            "youtube": self.youtube or "",
            "tiktok": self.tiktok or ""
        }


class KatanaExtractor:
    """
    Extrae datos de contacto de sitios web usando Katana.
    
    Ejecuta el binario katana via subprocess con los siguientes parámetros:
    - -u [URL]: URL a rastrear
    - -d 2: Profundidad de 2 niveles
    - -jc: Analizar archivos JavaScript
    - -field email,social_media,phone,title: Campos a extraer
    - -j: Salida en JSON
    """
    
    # Patrones para validar y limpiar datos
    EMAIL_PATTERN = re.compile(
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    )
    
    PHONE_PATTERN = re.compile(
        r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}'
    )
    
    # Patrones de redes sociales
    SOCIAL_PATTERNS = {
        "linkedin": re.compile(r'(?:https?://)?(?:www\.)?linkedin\.com/(?:company|in)/[^/\s"\'<>]+', re.IGNORECASE),
        "instagram": re.compile(r'(?:https?://)?(?:www\.)?instagram\.com/[^/\s"\'<>]+', re.IGNORECASE),
        "twitter": re.compile(r'(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/[^/\s"\'<>]+', re.IGNORECASE),
        "facebook": re.compile(r'(?:https?://)?(?:www\.)?facebook\.com/[^/\s"\'<>]+', re.IGNORECASE),
        "youtube": re.compile(r'(?:https?://)?(?:www\.)?youtube\.com/(?:c/|channel/|user/|@)[^/\s"\'<>]+', re.IGNORECASE),
        "tiktok": re.compile(r'(?:https?://)?(?:www\.)?tiktok\.com/@[^/\s"\'<>]+', re.IGNORECASE),
    }
    
    # Emails a excluir (genéricos, ejemplos, etc.)
    EXCLUDED_EMAIL_DOMAINS = {
        "example.com", "example.org", "test.com", "email.com",
        "domain.com", "yoursite.com", "yourdomain.com",
        "sentry.io", "wixpress.com", "w3.org", "schema.org",
        "googleusercontent.com", "gstatic.com"
    }
    
    EXCLUDED_EMAIL_PREFIXES = {
        "noreply", "no-reply", "donotreply", "mailer-daemon",
        "postmaster", "webmaster", "admin@localhost"
    }
    
    def __init__(self, timeout: int = 45, katana_path: str = "katana", depth: int = 2):
        """
        Args:
            timeout: Timeout en segundos para la ejecución de Katana (default: 45)
            katana_path: Ruta al binario katana (default: busca en PATH)
            depth: Profundidad de rastreo (default: 2)
        """
        self.timeout = timeout
        self.katana_path = katana_path
        self.depth = depth
    
    def extract(self, url: str, fields: List[str] = None) -> ContactData:
        """
        Extrae datos de contacto de una URL usando Katana.
        
        Args:
            url: URL a rastrear
            fields: Lista de campos a extraer (default: todos)
                    Opciones: email, phone, social_media, title
            
        Returns:
            ContactData con los datos extraídos
        """
        # Normalizar URL
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        
        domain = self._extract_domain(url)
        contact = ContactData(domain=domain, url=url)
        
        # Campos por defecto
        if fields is None:
            fields = ["email", "social_media", "phone", "title"]
        
        # Construir el campo para Katana
        field_str = ",".join(fields)
        
        try:
            # Ejecutar Katana via subprocess
            # Comando: katana -u [URL] -d 2 -jc -field email,social_media,phone,title -j
            result = subprocess.run(
                [
                    self.katana_path,
                    "-u", url,
                    "-d", str(self.depth),
                    "-jc",
                    "-field", field_str,
                    "-j",
                    "-silent"
                ],
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            
            contact.raw_output = result.stdout
            
            if result.stdout:
                self._parse_katana_output(result.stdout, contact)
                contact.extraction_success = contact.has_any_data()
                contact.partial_data = contact.has_any_data() and not all([
                    contact.email if "email" in fields else True,
                    contact.phone if "phone" in fields else True,
                    contact.social_media if "social_media" in fields else True,
                    contact.title if "title" in fields else True
                ])
            else:
                contact.error_message = result.stderr or "No output from Katana"
                
        except subprocess.TimeoutExpired as e:
            # En caso de timeout, intentar parsear lo que se haya capturado
            contact.error_message = f"Timeout ({self.timeout}s) - datos parciales"
            if e.stdout:
                try:
                    stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else e.stdout
                    self._parse_katana_output(stdout, contact)
                    contact.partial_data = contact.has_any_data()
                    contact.extraction_success = contact.has_any_data()
                except:
                    pass
        except FileNotFoundError:
            contact.error_message = "Katana no encontrado en el sistema"
        except Exception as e:
            contact.error_message = f"Error: {str(e)}"
        
        return contact
    
    def _parse_katana_output(self, output: str, contact: ContactData):
        """
        Parsea la salida JSON de Katana.
        
        Katana puede devolver múltiples líneas JSON, una por cada hallazgo.
        """
        emails_found = set()
        phones_found = set()
        socials_found = {key: set() for key in self.SOCIAL_PATTERNS.keys()}
        titles_found = set()
        
        lines = output.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Intentar parsear como JSON
            try:
                data = json.loads(line)
                self._extract_from_json(data, emails_found, phones_found, socials_found, titles_found)
            except json.JSONDecodeError:
                # Si no es JSON, buscar patrones directamente en la línea
                self._extract_from_text(line, emails_found, phones_found, socials_found)
        
        # Asignar el primer email válido
        valid_emails = [e for e in emails_found if self._is_valid_email(e)]
        if valid_emails:
            contact.email = valid_emails[0]
            contact.all_emails = valid_emails
        
        # Asignar el primer teléfono válido
        valid_phones = [p for p in phones_found if self._is_valid_phone(p)]
        if valid_phones:
            contact.phone = self._format_phone(valid_phones[0])
            contact.all_phones = [self._format_phone(p) for p in valid_phones]
        
        # Asignar redes sociales (una de cada tipo)
        for platform, urls in socials_found.items():
            if urls:
                clean_url = self._clean_social_url(list(urls)[0])
                setattr(contact, platform, clean_url)
                contact.social_media.append(clean_url)
        
        # Asignar título
        if titles_found:
            # Tomar el título más largo (probablemente el más descriptivo)
            contact.title = max(titles_found, key=len)
    
    def _extract_from_json(self, data: Dict, emails: Set, phones: Set, 
                          socials: Dict[str, Set], titles: Set):
        """Extrae datos de un objeto JSON de Katana."""
        if not isinstance(data, dict):
            return
        
        # Extraer email
        if "email" in data:
            email_val = data["email"]
            if isinstance(email_val, str):
                emails.add(email_val)
            elif isinstance(email_val, list):
                emails.update(email_val)
        
        # Extraer teléfono
        if "phone" in data:
            phone_val = data["phone"]
            if isinstance(phone_val, str):
                phones.add(phone_val)
            elif isinstance(phone_val, list):
                phones.update(phone_val)
        
        # Extraer título
        if "title" in data:
            title_val = data["title"]
            if isinstance(title_val, str) and title_val.strip():
                titles.add(title_val.strip())
        
        # Extraer redes sociales
        if "social_media" in data:
            social_val = data["social_media"]
            social_urls = []
            if isinstance(social_val, str):
                social_urls = [social_val]
            elif isinstance(social_val, list):
                social_urls = social_val
            
            for url in social_urls:
                self._categorize_social_url(url, socials)
        
        # Buscar en otros campos que puedan contener URLs
        for key in ["url", "endpoint", "source"]:
            if key in data and isinstance(data[key], str):
                self._extract_from_text(data[key], emails, phones, socials)
    
    def _extract_from_text(self, text: str, emails: Set, phones: Set, socials: Dict[str, Set]):
        """Extrae datos buscando patrones en texto plano."""
        # Buscar emails
        for match in self.EMAIL_PATTERN.finditer(text):
            emails.add(match.group())
        
        # Buscar teléfonos
        for match in self.PHONE_PATTERN.finditer(text):
            phones.add(match.group())
        
        # Buscar redes sociales
        self._categorize_social_url(text, socials)
    
    def _categorize_social_url(self, url: str, socials: Dict[str, Set]):
        """Categoriza una URL de red social."""
        for platform, pattern in self.SOCIAL_PATTERNS.items():
            match = pattern.search(url)
            if match:
                socials[platform].add(match.group())
                break
    
    def _is_valid_email(self, email: str) -> bool:
        """Verifica si un email es válido y no es genérico."""
        if not email or not self.EMAIL_PATTERN.match(email):
            return False
        
        email_lower = email.lower()
        
        # Verificar dominio excluido
        domain = email_lower.split('@')[1] if '@' in email_lower else ""
        if domain in self.EXCLUDED_EMAIL_DOMAINS:
            return False
        
        # Verificar prefijo excluido
        prefix = email_lower.split('@')[0] if '@' in email_lower else ""
        if any(prefix.startswith(excl) for excl in self.EXCLUDED_EMAIL_PREFIXES):
            return False
        
        return True
    
    def _is_valid_phone(self, phone: str) -> bool:
        """Verifica si un teléfono parece válido."""
        # Extraer solo dígitos
        digits = re.sub(r'\D', '', phone)
        # Un teléfono válido tiene entre 7 y 15 dígitos
        return 7 <= len(digits) <= 15
    
    def _format_phone(self, phone: str) -> str:
        """Formatea un número de teléfono."""
        # Limpiar espacios extra
        return re.sub(r'\s+', ' ', phone.strip())
    
    def _clean_social_url(self, url: str) -> str:
        """Limpia y normaliza una URL de red social."""
        url = url.strip()
        # Asegurar que tenga https://
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        # Remover parámetros de tracking
        url = re.sub(r'\?.*$', '', url)
        return url
    
    def _extract_domain(self, url: str) -> str:
        """Extrae el dominio de una URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except:
            return url


def extract_contacts(url: str, fields: List[str] = None, timeout: int = 45) -> ContactData:
    """Función de conveniencia para extraer contactos de una URL."""
    extractor = KatanaExtractor(timeout=timeout)
    return extractor.extract(url, fields)
