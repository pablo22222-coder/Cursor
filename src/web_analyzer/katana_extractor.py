"""
Extractor de datos de contacto usando Katana (Optimizado).
Usa subprocess.Popen con streaming y early exit para máxima eficiencia.

Comando: katana -u [URL] -d 2 -jc -silent -timeout 45

Optimizaciones:
- Ejecución asíncrona con Popen
- Streaming line-by-line del stdout
- Early exit cuando tenemos email + red social
- Hard timeout de 60s para evitar bloqueos
"""
import subprocess
import re
import threading
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
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
    error_message: Optional[str] = None
    
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
            "early_exit": self.early_exit,
            "error_message": self.error_message
        }
    
    def has_any_data(self) -> bool:
        """Verifica si se extrajo algún dato."""
        return bool(self.email or self.phone or self.social_media)
    
    def has_minimum_data(self) -> bool:
        """Verifica si tenemos los datos mínimos para early exit (email + 1 red social)."""
        return bool(self.email and self.social_media)
    
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
    Extractor optimizado de datos de contacto usando Katana.
    
    Usa subprocess.Popen con streaming para máxima eficiencia.
    Implementa early exit cuando encuentra email + red social.
    """
    
    # Regex para email (aplicado a texto plano)
    EMAIL_REGEX = re.compile(
        r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    )
    
    # Regex para redes sociales (aplicado a texto plano)
    SOCIAL_REGEX = re.compile(
        r'(linkedin\.com/(?:company|in)/|instagram\.com/|facebook\.com/|twitter\.com/|x\.com/|youtube\.com/(?:c/|channel/|user/|@)|tiktok\.com/@)[a-zA-Z0-9_.-]+'
    )
    
    # Regex para teléfonos
    PHONE_REGEX = re.compile(
        r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}'
    )
    
    # Emails a excluir
    EXCLUDED_EMAIL_DOMAINS = {
        "example.com", "example.org", "test.com", "email.com",
        "domain.com", "yoursite.com", "yourdomain.com",
        "sentry.io", "wixpress.com", "w3.org", "schema.org",
        "googleusercontent.com", "gstatic.com", "gravatar.com",
        "wordpress.org", "wp.com", "jsdelivr.net", "cloudflare.com"
    }
    
    EXCLUDED_EMAIL_PREFIXES = {
        "noreply", "no-reply", "donotreply", "mailer-daemon",
        "postmaster", "webmaster", "admin@localhost", "support@example",
        "info@example", "contact@example", "hello@example"
    }
    
    def __init__(self, katana_timeout: int = 45, hard_timeout: int = 60, 
                 katana_path: str = "katana", depth: int = 2):
        """
        Args:
            katana_timeout: Timeout interno de Katana (segundos)
            hard_timeout: Timeout máximo total para evitar bloqueos (segundos)
            katana_path: Ruta al binario katana
            depth: Profundidad de rastreo
        """
        self.katana_timeout = katana_timeout
        self.hard_timeout = hard_timeout
        self.katana_path = katana_path
        self.depth = depth
    
    def extract(self, url: str) -> ContactData:
        """
        Extrae datos de contacto de una URL usando Katana con streaming.
        
        Implementa early exit cuando encuentra email + al menos una red social.
        Hard timeout de 60s para evitar bloqueos del servidor.
        
        Args:
            url: URL a rastrear
            
        Returns:
            ContactData con los datos extraídos
        """
        # Normalizar URL
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        
        domain = self._extract_domain(url)
        contact = ContactData(domain=domain, url=url)
        
        # Datos encontrados durante el streaming
        found_data = {
            "email": None,
            "phone": None,
            "linkedin": None,
            "instagram": None,
            "twitter": None,
            "facebook": None,
            "youtube": None,
            "tiktok": None
        }
        
        process = None
        timer = None
        timed_out = False
        
        def kill_process():
            """Callback del timer para matar el proceso."""
            nonlocal timed_out
            timed_out = True
            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.kill()
                except:
                    pass
        
        try:
            # Comando: katana -u [URL] -d 2 -jc -silent -timeout 45
            cmd = [
                self.katana_path,
                "-u", url,
                "-d", str(self.depth),
                "-jc",
                "-silent",
                "-timeout", str(self.katana_timeout)
            ]
            
            # Iniciar proceso con Popen para streaming
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            
            # Timer de seguridad para hard timeout
            timer = threading.Timer(self.hard_timeout, kill_process)
            timer.start()
            
            # Streaming line-by-line
            for line in process.stdout:
                if timed_out:
                    break
                
                line = line.strip()
                if not line:
                    continue
                
                # Aplicar regex a cada línea
                self._extract_from_line(line, found_data)
                
                # CONDICIÓN DE CORTE: email + al menos una red social
                if found_data["email"] and self._has_any_social(found_data):
                    contact.early_exit = True
                    process.terminate()
                    break
            
            # Esperar a que termine el proceso (con timeout corto)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
            
        except FileNotFoundError:
            contact.error_message = "Katana no encontrado en el sistema"
        except Exception as e:
            contact.error_message = f"Error: {str(e)}"
        finally:
            # Cancelar timer si aún está activo
            if timer:
                timer.cancel()
            
            # Asegurar que el proceso está terminado
            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.kill()
                except:
                    pass
        
        # Transferir datos encontrados al objeto ContactData
        self._populate_contact(contact, found_data)
        
        # Determinar estado
        if timed_out:
            contact.error_message = f"Hard timeout ({self.hard_timeout}s)"
            contact.partial_data = contact.has_any_data()
        
        contact.extraction_success = contact.has_any_data()
        
        return contact
    
    def _extract_from_line(self, line: str, found_data: Dict):
        """
        Extrae datos aplicando regex a una línea de texto.
        Actualiza found_data in-place.
        """
        # Buscar email si no tenemos uno
        if not found_data["email"]:
            email_match = self.EMAIL_REGEX.search(line)
            if email_match:
                email = email_match.group()
                if self._is_valid_email(email):
                    found_data["email"] = email
        
        # Buscar teléfono si no tenemos uno
        if not found_data["phone"]:
            phone_match = self.PHONE_REGEX.search(line)
            if phone_match:
                phone = phone_match.group()
                if self._is_valid_phone(phone):
                    found_data["phone"] = self._format_phone(phone)
        
        # Buscar redes sociales
        for social_match in self.SOCIAL_REGEX.finditer(line):
            social_url = social_match.group()
            self._categorize_social(social_url, found_data)
    
    def _categorize_social(self, url: str, found_data: Dict):
        """Categoriza una URL de red social y la guarda si no tenemos una de ese tipo."""
        url_lower = url.lower()
        
        # Normalizar URL
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        # Limpiar parámetros de tracking
        url = re.sub(r'\?.*$', '', url)
        
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
        """Verifica si tenemos al menos una red social."""
        return any([
            found_data["linkedin"],
            found_data["instagram"],
            found_data["twitter"],
            found_data["facebook"],
            found_data["youtube"],
            found_data["tiktok"]
        ])
    
    def _populate_contact(self, contact: ContactData, found_data: Dict):
        """Transfiere los datos encontrados al objeto ContactData."""
        contact.email = found_data["email"]
        contact.phone = found_data["phone"]
        contact.linkedin = found_data["linkedin"]
        contact.instagram = found_data["instagram"]
        contact.twitter = found_data["twitter"]
        contact.facebook = found_data["facebook"]
        contact.youtube = found_data["youtube"]
        contact.tiktok = found_data["tiktok"]
        
        # Construir lista de redes sociales
        for platform in ["linkedin", "instagram", "twitter", "facebook", "youtube", "tiktok"]:
            if found_data[platform]:
                contact.social_media.append(found_data[platform])
    
    def _is_valid_email(self, email: str) -> bool:
        """Verifica si un email es válido y no es genérico."""
        if not email:
            return False
        
        email_lower = email.lower()
        
        # Verificar dominio excluido
        if '@' in email_lower:
            domain = email_lower.split('@')[1]
            if domain in self.EXCLUDED_EMAIL_DOMAINS:
                return False
            
            # Verificar prefijo excluido
            prefix = email_lower.split('@')[0]
            if any(prefix.startswith(excl) for excl in self.EXCLUDED_EMAIL_PREFIXES):
                return False
        
        # Verificar que el dominio tenga al menos un punto
        if '@' in email and '.' not in email.split('@')[1]:
            return False
        
        return True
    
    def _is_valid_phone(self, phone: str) -> bool:
        """Verifica si un teléfono parece válido."""
        digits = re.sub(r'\D', '', phone)
        return 7 <= len(digits) <= 15
    
    def _format_phone(self, phone: str) -> str:
        """Formatea un número de teléfono."""
        return re.sub(r'\s+', ' ', phone.strip())
    
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


def extract_contacts(url: str, katana_timeout: int = 45, hard_timeout: int = 60) -> ContactData:
    """Función de conveniencia para extraer contactos de una URL."""
    extractor = KatanaExtractor(katana_timeout=katana_timeout, hard_timeout=hard_timeout)
    return extractor.extract(url)
