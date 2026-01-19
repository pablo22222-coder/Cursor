"""
Analizador de prompts - Interpreta qué tipo de web busca el usuario.

Este módulo es CRÍTICO para resolver el problema principal:
- Distinguir entre "webs que hablen de X" vs "webs que SEAN X"
- Extraer especificaciones del prompt (tipo de producto, nicho, etc.)
"""
import re
from typing import List, Tuple, Optional
from ..models.domain import PromptIntent, BusinessType


class PromptAnalyzer:
    """
    Analiza el prompt del usuario para entender exactamente qué busca.
    
    Problema a resolver: Cuando el usuario pone "ecommerce", no quiere
    webs que hablen de ecommerce (como Shopify o artículos), sino webs
    que SEAN ecommerce (tiendas online reales).
    """
    
    # Patrones para detectar tipos de negocio
    BUSINESS_PATTERNS = {
        BusinessType.ECOMMERCE: [
            r'\becommerce\b', r'\be-commerce\b', r'\btienda\s+online\b',
            r'\btienda\s+virtual\b', r'\bshop\b', r'\bstore\b',
            r'\bcomercio\s+electr[oó]nico\b'
        ],
        BusinessType.SAAS: [
            r'\bsaas\b', r'\bsoftware\s+as\s+a\s+service\b',
            r'\bplataforma\b', r'\bherramienta\s+online\b',
            r'\bapp\s+web\b', r'\baplicaci[oó]n\s+web\b'
        ],
        BusinessType.AGENCY: [
            r'\bagencia\b', r'\bagency\b', r'\bestudio\b',
            r'\bconsultor[ií]a\b', r'\bconsulting\b'
        ],
        BusinessType.DROPSHIPPING: [
            r'\bdropshipping\b', r'\bdrop\s*shipping\b'
        ],
        BusinessType.MARKETPLACE: [
            r'\bmarketplace\b', r'\bmercado\b'
        ],
        BusinessType.BLOG: [
            r'\bblog\b', r'\bblogs\b'
        ],
        BusinessType.PORTFOLIO: [
            r'\bportfolio\b', r'\bportafolio\b'
        ],
        BusinessType.SUBSCRIPTION: [
            r'\bsuscripci[oó]n\b', r'\bsubscription\b', r'\bmembres[ií]a\b'
        ],
        BusinessType.SERVICE: [
            r'\bservicio\b', r'\bservice\b'
        ],
        BusinessType.CORPORATE: [
            r'\bcorporativ[oa]\b', r'\bempresa\b', r'\bcorporate\b'
        ]
    }
    
    # Palabras clave que indican nichos/sectores
    NICHE_KEYWORDS = [
        # Moda y ropa
        (r'\bmoda\b|\bfashion\b|\bropa\b|\bclothing\b|\btextil\b', 'moda'),
        (r'\bold\s*money\b', 'old money'),
        (r'\bstreet\s*wear\b|\burban\b', 'streetwear'),
        (r'\blujo\b|\bluxury\b|\bpremium\b', 'lujo'),
        
        # Tecnología
        (r'\belectr[oó]nica\b|\belectronics\b|\btech\b|\btecnolog[ií]a\b', 'tecnología'),
        (r'\bgadgets?\b|\bdispositivos?\b', 'gadgets'),
        (r'\bm[oó]viles?\b|\bsmartphones?\b|\bcelulares?\b', 'móviles'),
        
        # Salud y belleza
        (r'\bbelleza\b|\bbeauty\b|\bcosm[eé]tic[oa]s?\b', 'belleza'),
        (r'\bcremas?\s*(faciale?s?)?\b|\bskincare\b|\bcuidado\s*(de\s*la)?\s*piel\b', 'skincare'),
        (r'\bmaquillaje\b|\bmakeup\b', 'maquillaje'),
        (r'\bsalud\b|\bhealth\b|\bbienestar\b|\bwellness\b', 'salud'),
        (r'\bsuplementos?\b|\bvitaminas?\b', 'suplementos'),
        
        # Hogar
        (r'\bhogar\b|\bhome\b|\bcasa\b|\bmuebles?\b|\bfurniture\b', 'hogar'),
        (r'\bdecoraci[oó]n\b|\bdecor\b', 'decoración'),
        
        # Alimentación
        (r'\baliment(os?|aci[oó]n)\b|\bfood\b|\bcomida\b', 'alimentación'),
        (r'\bvegan[oa]?\b|\bvegetarian[oa]?\b|\borg[aá]nic[oa]?\b', 'orgánico'),
        
        # Marketing
        (r'\bmarketing\b', 'marketing'),
        (r'\bmarketing\s+digital\b|\bdigital\s+marketing\b', 'marketing digital'),
        (r'\bseo\b', 'SEO'),
        (r'\bpublicidad\b|\badvertising\b|\bads\b', 'publicidad'),
        (r'\bredes\s+sociales\b|\bsocial\s+media\b', 'redes sociales'),
        
        # Otros
        (r'\bdeportes?\b|\bsports?\b|\bfitness\b', 'deportes'),
        (r'\bmascotas?\b|\bpets?\b', 'mascotas'),
        (r'\bni[ñn]os?\b|\binfantil\b|\bkids?\b|\bbeb[eé]s?\b', 'infantil'),
        (r'\bjuguetes?\b|\btoys?\b', 'juguetes'),
        (r'\bjoyer[ií]a\b|\bjewelry\b|\bjoyas?\b', 'joyería'),
        (r'\brelojes?\b|\bwatches?\b', 'relojes'),
        (r'\bautom[oó]vil(es)?\b|\bcars?\b|\bcoches?\b|\bveh[ií]culos?\b', 'automoción'),
    ]
    
    # Indicadores de métricas que el usuario quiere analizar
    METRICS_KEYWORDS = {
        'velocidad': [r'\bvelocidad\b', r'\br[aá]pida?\b', r'\blenta?\b', r'\bcarga\b', r'\bspeed\b'],
        'seo': [r'\bseo\b', r'\bposicionamiento\b', r'\branking\b'],
        'mobile': [r'\bm[oó]vil\b', r'\bmobile\b', r'\bresponsive\b'],
        'performance': [r'\bperformance\b', r'\brendimiento\b'],
        'accesibilidad': [r'\baccesibilidad\b', r'\baccessibility\b'],
    }
    
    def __init__(self):
        """Inicializa el analizador de prompts."""
        pass
    
    def analyze(self, prompt: str) -> PromptIntent:
        """
        Analiza el prompt y extrae la intención del usuario.
        
        Args:
            prompt: El prompt del usuario (ej: "ecommerce de crema facial")
            
        Returns:
            PromptIntent con toda la información extraída
        """
        prompt_lower = prompt.lower().strip()
        
        # Detectar tipo de negocio
        business_type, business_confidence = self._detect_business_type(prompt_lower)
        
        # Detectar nicho/sector
        niche = self._detect_niche(prompt_lower)
        
        # Detectar producto/servicio específico
        product_service = self._detect_product_service(prompt_lower, business_type, niche)
        
        # Detectar características adicionales
        characteristics = self._extract_characteristics(prompt_lower)
        
        # Detectar métricas a analizar
        metrics = self._detect_metrics_to_analyze(prompt_lower)
        
        # Generar queries de búsqueda
        search_queries = self._generate_search_queries(
            business_type, niche, product_service, characteristics, prompt
        )
        
        return PromptIntent(
            business_type=business_type,
            niche=niche,
            product_service=product_service,
            characteristics=characteristics,
            metrics_to_analyze=metrics,
            original_prompt=prompt,
            search_queries=search_queries,
            confidence=business_confidence
        )
    
    def _detect_business_type(self, prompt: str) -> Tuple[BusinessType, int]:
        """Detecta el tipo de negocio que busca el usuario."""
        for business_type, patterns in self.BUSINESS_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, prompt, re.IGNORECASE):
                    # Calcular confianza basada en la especificidad del patrón
                    confidence = 80 if len(pattern) > 10 else 60
                    return business_type, confidence
        
        return BusinessType.UNKNOWN, 30
    
    def _detect_niche(self, prompt: str) -> Optional[str]:
        """Detecta el nicho o sector específico."""
        for pattern, niche_name in self.NICHE_KEYWORDS:
            if re.search(pattern, prompt, re.IGNORECASE):
                return niche_name
        return None
    
    def _detect_product_service(
        self, 
        prompt: str, 
        business_type: BusinessType,
        niche: Optional[str]
    ) -> Optional[str]:
        """
        Detecta el producto o servicio específico mencionado.
        
        Intenta extraer especificaciones más allá del nicho general.
        Ej: "ecommerce de crema facial" -> producto = "crema facial"
        """
        # Patrones para extraer el producto/servicio después de "de"
        de_patterns = [
            r'\bde\s+([a-záéíóúñ\s]+?)(?:\s+que|\s+con|\s*$)',
            r'\bpara\s+([a-záéíóúñ\s]+?)(?:\s+que|\s+con|\s*$)',
        ]
        
        for pattern in de_patterns:
            match = re.search(pattern, prompt, re.IGNORECASE)
            if match:
                product = match.group(1).strip()
                # Filtrar si es solo el nicho que ya detectamos
                if niche and product.lower() == niche.lower():
                    continue
                # Filtrar palabras muy genéricas
                if product and len(product) > 2 and product not in ['la', 'el', 'los', 'las', 'un', 'una']:
                    return product
        
        return None
    
    def _extract_characteristics(self, prompt: str) -> List[str]:
        """Extrae características adicionales del prompt."""
        characteristics = []
        
        # Patrones de características
        char_patterns = [
            (r'\bpequeñ[oa]s?\b', 'pequeño'),
            (r'\bgrandes?\b', 'grande'),
            (r'\blocal(es)?\b', 'local'),
            (r'\binternacional(es)?\b', 'internacional'),
            (r'\bespañol(es|as)?\b|\ben\s+españa\b', 'español'),
            (r'\bnuev[oa]s?\b', 'nuevo'),
            (r'\bestablecid[oa]s?\b', 'establecido'),
            (r'\bcon\s+blog\b', 'tiene blog'),
            (r'\bsin\s+blog\b', 'sin blog'),
            (r'\bcon\s+env[ií]o\s+gratis\b', 'envío gratis'),
        ]
        
        for pattern, char_name in char_patterns:
            if re.search(pattern, prompt, re.IGNORECASE):
                characteristics.append(char_name)
        
        return characteristics
    
    def _detect_metrics_to_analyze(self, prompt: str) -> List[str]:
        """Detecta si el usuario quiere analizar métricas específicas."""
        metrics = []
        
        for metric_name, patterns in self.METRICS_KEYWORDS.items():
            for pattern in patterns:
                if re.search(pattern, prompt, re.IGNORECASE):
                    metrics.append(metric_name)
                    break
        
        return metrics
    
    def _generate_search_queries(
        self,
        business_type: BusinessType,
        niche: Optional[str],
        product_service: Optional[str],
        characteristics: List[str],
        original_prompt: str
    ) -> List[str]:
        """
        Genera queries de búsqueda inteligentes.
        
        CLAVE: Estas queries deben encontrar webs que SEAN el tipo de negocio,
        no webs que hablen de él.
        """
        queries = []
        
        # Mapeo de tipos de negocio a términos de búsqueda efectivos
        business_search_terms = {
            BusinessType.ECOMMERCE: [
                "tienda online", "comprar", "shop", "store",
                "carrito de compra", "envío", "productos"
            ],
            BusinessType.SAAS: [
                "software", "plataforma", "herramienta", "app",
                "pricing", "planes", "free trial", "demo"
            ],
            BusinessType.AGENCY: [
                "agencia", "servicios", "portfolio", "clientes",
                "proyectos", "contacto"
            ],
            BusinessType.DROPSHIPPING: [
                "tienda online", "comprar", "envío directo",
                "productos importados"
            ],
            BusinessType.MARKETPLACE: [
                "marketplace", "vendedores", "compradores",
                "plataforma de ventas"
            ],
        }
        
        # Query base según tipo de negocio
        if business_type != BusinessType.UNKNOWN:
            terms = business_search_terms.get(business_type, [])
            
            # Construir queries combinando nicho y tipo
            if niche:
                # Query principal: nicho + indicador de que es ese tipo de web
                if business_type == BusinessType.ECOMMERCE:
                    queries.append(f"tienda online {niche}")
                    queries.append(f"comprar {niche} online")
                    queries.append(f"shop {niche}")
                    if product_service:
                        queries.append(f"comprar {product_service} online")
                        queries.append(f"tienda {product_service}")
                elif business_type == BusinessType.AGENCY:
                    queries.append(f"agencia de {niche}")
                    queries.append(f"agencia {niche} servicios")
                elif business_type == BusinessType.SAAS:
                    queries.append(f"software {niche}")
                    queries.append(f"herramienta {niche} online")
                    queries.append(f"plataforma {niche}")
            else:
                # Sin nicho, usar términos genéricos pero que encuentren webs reales
                if business_type == BusinessType.ECOMMERCE:
                    queries.append("tienda online comprar")
                    queries.append("shop online productos")
                elif business_type == BusinessType.AGENCY:
                    queries.append("agencia servicios portfolio")
                elif business_type == BusinessType.SAAS:
                    queries.append("software online pricing plans")
        
        # Si tenemos producto/servicio específico, crear queries más específicas
        if product_service:
            queries.append(f"comprar {product_service}")
            queries.append(f"{product_service} tienda online")
        
        # Añadir características locales si aplica
        if 'español' in characteristics or 'local' in characteristics:
            queries = [f"{q} españa" for q in queries[:3]] + queries
        
        # Eliminar duplicados manteniendo orden
        seen = set()
        unique_queries = []
        for q in queries:
            if q.lower() not in seen:
                seen.add(q.lower())
                unique_queries.append(q)
        
        return unique_queries[:5]  # Máximo 5 queries diferentes
