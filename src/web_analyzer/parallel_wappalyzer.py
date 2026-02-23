"""
ParallelWappalyzer - Análisis de tecnologías con 3 Workers paralelos
Usa asyncio.Semaphore(3) para analizar hasta 3 dominios simultáneamente.
"""
import asyncio
import subprocess
import json
from typing import List, Dict, Any, Callable, Optional
from concurrent.futures import ThreadPoolExecutor


MAX_WORKERS = 3
WAPPALYZER_TIMEOUT = 10  # seconds per domain


# Categorización de tecnologías por nombre
TECH_CATEGORIES = {
    'cms': ['WordPress', 'Drupal', 'Joomla', 'Wix', 'Squarespace', 'Webflow', 'Ghost', 'Contentful'],
    'ecommerce': ['Shopify', 'WooCommerce', 'Magento', 'PrestaShop', 'BigCommerce', 'OpenCart', 'Stripe', 'PayPal'],
    'crm': ['Salesforce', 'HubSpot', 'Zoho', 'Pipedrive', 'Freshsales', 'monday.com'],
    'email_marketing': ['Mailchimp', 'Klaviyo', 'SendGrid', 'Mailjet', 'ActiveCampaign', 'Brevo', 'ConvertKit'],
    'analytics': ['Google Analytics', 'Hotjar', 'Mixpanel', 'Segment', 'Amplitude', 'Heap', 'Matomo'],
    'live_chat': ['Intercom', 'Drift', 'Zendesk', 'LiveChat', 'Crisp', 'Tawk.to', 'Tidio'],
    'framework': ['React', 'Vue.js', 'Angular', 'Next.js', 'Nuxt.js', 'Svelte', 'jQuery'],
}


def categorize_tech(tech_name: str) -> Dict[str, bool]:
    """Categoriza una tecnología por nombre."""
    result = {cat: False for cat in TECH_CATEGORIES}
    tech_lower = tech_name.lower()
    
    for category, techs in TECH_CATEGORIES.items():
        for known_tech in techs:
            if known_tech.lower() in tech_lower or tech_lower in known_tech.lower():
                result[category] = True
                break
    
    return result


def analyze_single_domain(url: str) -> Dict[str, Any]:
    """
    Analiza un solo dominio con Wappalyzer (10s timeout).
    Ejecutado en un thread separado.
    """
    result = {
        'url': url,
        'success': False,
        'technologies': [],
        'categories': {
            'cms': [], 'ecommerce': [], 'crm': [], 
            'email_marketing': [], 'analytics': [], 
            'live_chat': [], 'framework': []
        },
        'has_ecommerce': False,
        'has_crm': False,
        'has_email_marketing': False
    }
    
    try:
        process = subprocess.run(
            ['wappalyzergo', '-u', url, '-td', '-json', '-fr'],
            capture_output=True,
            text=True,
            timeout=WAPPALYZER_TIMEOUT
        )
        
        if process.returncode == 0 and process.stdout:
            data = json.loads(process.stdout)
            
            # Extraer tecnologías
            technologies = []
            if isinstance(data, dict):
                for url_data in data.values():
                    if isinstance(url_data, dict) and 'tech' in url_data:
                        technologies = url_data['tech']
                        break
            elif isinstance(data, list):
                technologies = data
            
            result['technologies'] = technologies
            result['success'] = True
            
            # Categorizar
            for tech in technologies:
                categories = categorize_tech(tech)
                for cat, is_match in categories.items():
                    if is_match and tech not in result['categories'].get(cat, []):
                        result['categories'][cat].append(tech)
            
            # Flags
            result['has_ecommerce'] = len(result['categories']['ecommerce']) > 0
            result['has_crm'] = len(result['categories']['crm']) > 0
            result['has_email_marketing'] = len(result['categories']['email_marketing']) > 0
            
    except subprocess.TimeoutExpired:
        result['success'] = True  # Timeout is ok, just no results
    except FileNotFoundError:
        pass  # Wappalyzer not installed
    except json.JSONDecodeError:
        pass
    except Exception as e:
        result['error'] = str(e)[:50]
    
    return result


class ParallelWappalyzerAnalyzer:
    """
    Analizador de tecnologías con 3 Workers paralelos.
    Usa ThreadPoolExecutor porque Wappalyzer es un proceso externo.
    """
    
    def __init__(self, max_workers: int = MAX_WORKERS, on_progress: Callable = None):
        self.max_workers = max_workers
        self.on_progress = on_progress
        self.completed = 0
        self.total = 0
    
    def analyze_domains(self, domains: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Analiza múltiples dominios en paralelo con 3 workers.
        
        Args:
            domains: Lista de dicts con 'url' y 'domain'
        
        Returns:
            Lista de dominios con datos de tecnología añadidos
        """
        self.total = len(domains)
        self.completed = 0
        
        results = []
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            futures = {}
            for i, domain_info in enumerate(domains):
                url = domain_info.get('url', '')
                future = executor.submit(analyze_single_domain, url)
                futures[future] = (i, domain_info)
            
            # Collect results as they complete
            for future in futures:
                i, domain_info = futures[future]
                
                try:
                    tech_result = future.result(timeout=WAPPALYZER_TIMEOUT + 5)
                    
                    # Add tech data to domain_info
                    domain_info['tech_profile'] = {
                        'all_techs': tech_result['technologies'][:15],
                        'cms': tech_result['categories']['cms'],
                        'ecommerce': tech_result['categories']['ecommerce'],
                        'crm': tech_result['categories']['crm'],
                        'email': tech_result['categories']['email_marketing'],
                        'analytics': tech_result['categories']['analytics'],
                        'chat': tech_result['categories']['live_chat']
                    }
                    domain_info['tech'] = tech_result['categories']['ecommerce'][:3]
                    domain_info['is_ecommerce'] = tech_result['has_ecommerce']
                    domain_info['wappalyzer_success'] = tech_result['success']
                    
                except Exception as e:
                    domain_info['tech_profile'] = None
                    domain_info['tech'] = []
                    domain_info['is_ecommerce'] = False
                    domain_info['wappalyzer_success'] = False
                
                self.completed += 1
                if self.on_progress:
                    progress = int((self.completed / self.total) * 100)
                    self.on_progress(
                        progress,
                        f"Wappalyzer: {domain_info.get('domain', '')}",
                        self.completed,
                        self.total
                    )
                
                results.append(domain_info)
        
        return results
    
    def check_tech_requirements(
        self,
        domain_info: Dict[str, Any],
        must_have: List[str] = None,
        must_not: List[str] = None
    ) -> bool:
        """Verifica si un dominio cumple requisitos de tecnología."""
        if not must_have and not must_not:
            return True
        
        tech_profile = domain_info.get('tech_profile', {})
        if not tech_profile:
            return False
        
        all_techs = set(t.lower() for t in tech_profile.get('all_techs', []))
        
        # Check must_have
        if must_have:
            for req in must_have:
                req_lower = req.lower()
                found = any(req_lower in tech for tech in all_techs)
                if not found:
                    return False
        
        # Check must_not
        if must_not:
            for excl in must_not:
                excl_lower = excl.lower()
                found = any(excl_lower in tech for tech in all_techs)
                if found:
                    return False
        
        return True


def analyze_technologies_parallel(
    domains: List[Dict[str, Any]],
    on_progress: Callable = None
) -> List[Dict[str, Any]]:
    """
    Función de conveniencia para análisis paralelo de tecnologías.
    """
    analyzer = ParallelWappalyzerAnalyzer(on_progress=on_progress)
    return analyzer.analyze_domains(domains)
