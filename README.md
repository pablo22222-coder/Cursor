# Domain Finder - Buscador Inteligente de Dominios

Sistema inteligente que encuentra webs que **SEAN** lo que describe el prompt, no webs que hablen de eso.

## El Problema que Resuelve

Cuando buscas "ecommerce" en Google, obtienes:
- ❌ Shopify (habla de ecommerce, pero no ES un ecommerce)
- ❌ Artículos "Qué es el ecommerce"
- ❌ Guías "Cómo crear un ecommerce"

Lo que realmente necesitas:
- ✅ zalando.es (ES un ecommerce)
- ✅ pccomponentes.com (ES un ecommerce de electrónica)
- ✅ tiendas reales que venden productos

## Estructura del Proyecto

```
/workspace/
├── README.md                 # Esta documentación
├── requirements.txt          # Dependencias Python
├── run.py                    # Script principal de ejecución
├── config/
│   ├── __init__.py
│   └── settings.py          # Configuración y API keys
├── src/
│   ├── __init__.py
│   ├── main.py              # Clase principal DomainFinder
│   ├── prompt_analyzer/
│   │   ├── __init__.py
│   │   └── analyzer.py      # Analiza el prompt (detecta tipo, nicho, producto)
│   ├── search/
│   │   ├── __init__.py
│   │   ├── serper_client.py # Cliente para API de Serper (búsqueda Google)
│   │   └── query_generator.py # Genera queries inteligentes
│   ├── validators/
│   │   ├── __init__.py
│   │   ├── domain_validator.py # Valida si el dominio cumple el prompt
│   │   ├── tech_analyzer.py   # Usa WebTech para detectar tecnologías
│   │   └── pagespeed_analyzer.py # Usa PageSpeed para métricas
│   └── models/
│       ├── __init__.py
│       └── domain.py         # Modelos de datos (Domain, TechStack, etc.)
└── tests/
    └── __init__.py
```

## Instalación

```bash
pip install -r requirements.txt
```

## Uso

### Línea de Comandos

```bash
# Búsqueda básica
python run.py "ecommerce de electrónica"

# Con análisis de PageSpeed
python run.py "agencia de marketing digital" --pagespeed

# Más resultados
python run.py "saas de gestión" --results 20

# Salida JSON
python run.py "tienda de ropa" --json

# Búsqueda rápida (sin validación de tecnologías)
python run.py "dropshipping" --no-validate
```

### Como Librería Python

```python
from src.main import DomainFinder, find_domains

# Forma simple
domains = find_domains("ecommerce de crema facial")

# Forma avanzada
finder = DomainFinder()
domains = finder.find(
    prompt="tienda online de electrónica españa",
    max_results=15,
    validate_tech=True,
    analyze_pagespeed=True,
    min_match_score=50
)

# Ver resultados
finder.print_results(domains)

# Obtener reporte JSON
report = finder.get_detailed_report(domains)
```

## Componentes Principales

### 1. Prompt Analyzer (`src/prompt_analyzer/analyzer.py`)

Analiza el prompt del usuario para extraer:
- **Tipo de negocio**: ecommerce, SaaS, agencia, dropshipping, etc.
- **Nicho**: moda, electrónica, marketing, salud, etc.
- **Producto/servicio**: crema facial, software CRM, etc.
- **Características**: local, internacional, español, etc.
- **Métricas a analizar**: velocidad, SEO, mobile, etc.

```python
from src.prompt_analyzer import PromptAnalyzer

analyzer = PromptAnalyzer()
intent = analyzer.analyze("ecommerce de crema facial español")

print(intent.business_type)    # BusinessType.ECOMMERCE
print(intent.niche)            # "skincare"
print(intent.product_service)  # "crema facial"
print(intent.characteristics)  # ["español"]
```

### 2. Search (`src/search/`)

#### SerperClient
Cliente para buscar en Google usando la API de Serper.

```python
from src.search import SerperClient

client = SerperClient()
domains = client.search("tienda online ropa", num_results=10)
```

#### QueryGenerator
Genera queries inteligentes que encuentran webs REALES, no artículos.

```python
from src.search import QueryGenerator

generator = QueryGenerator()
queries = generator.generate_queries(intent)
# ["comprar crema facial online", "tienda skincare españa", ...]
```

### 3. Validators (`src/validators/`)

#### TechAnalyzer (WebTech)
Detecta tecnologías de la web: CMS, plataformas ecommerce, pagos, analytics.

```python
from src.validators import TechAnalyzer

tech = TechAnalyzer()
stack = tech.analyze("https://ejemplo.com")

print(stack.ecommerce_platform)  # "shopify"
print(stack.payment_processors)  # ["stripe", "paypal"]
print(stack.cms)                 # "wordpress"
```

#### PageSpeedAnalyzer
Analiza métricas de rendimiento y SEO.

```python
from src.validators import PageSpeedAnalyzer

pagespeed = PageSpeedAnalyzer()
metrics = pagespeed.analyze("https://ejemplo.com")

print(metrics.performance_score)  # 85
print(metrics.seo_score)          # 92
print(metrics.is_mobile_friendly) # True
```

#### DomainValidator
Combina todo para determinar si un dominio cumple el prompt.

```python
from src.validators import DomainValidator

validator = DomainValidator()
validated_domain = validator.validate(domain, intent, analyze_pagespeed=True)

print(validated_domain.analysis.match_score)    # 75
print(validated_domain.analysis.matches_prompt) # True
print(validated_domain.analysis.match_reasons)  # ["Plataforma: shopify", ...]
```

## APIs Utilizadas

### Serper (Búsqueda en Google)
- **API Key**: Configurada en `config/settings.py`
- **Límites**: Según tu plan de Serper
- **Uso**: Búsqueda de dominios

### PageSpeed Insights (Google)
- **API Key**: Configurada en `config/settings.py`
- **Límites**: 25,000 requests/día GRATIS
- **Uso**: Métricas de rendimiento, SEO, accesibilidad

### WebTech
- **Sin API Key**: Es una librería open-source
- **Sin límites**: Completamente gratuita
- **Uso**: Detectar tecnologías (CMS, ecommerce, pagos, etc.)

## Tipos de Negocio Detectados

| Tipo | Descripción | Indicadores |
|------|-------------|-------------|
| ECOMMERCE | Tiendas online | Shopify, WooCommerce, carrito, pagos |
| SAAS | Software as a Service | Pricing, trial, API, integrations |
| AGENCY | Agencias | Portfolio, servicios, proyectos |
| DROPSHIPPING | Dropshipping | Tienda + sin marca clara |
| MARKETPLACE | Marketplaces | Vendedores, compradores |
| BLOG | Blogs | WordPress sin ecommerce |
| CORPORATE | Corporativas | Empresas, about us |

## Ejemplos de Prompts

```
# Ecommerce
"ecommerce de electrónica"
"tienda online de ropa old money"
"ecommerce de crema facial españa"

# SaaS
"saas de gestión de proyectos"
"software de email marketing"
"herramienta de analytics"

# Agencias
"agencia de marketing digital"
"agencia de diseño web española"
"estudio de branding"

# Con métricas
"ecommerce con carga lenta"  # Analizará velocidad
"web con mal SEO"            # Analizará SEO score
```

## Flujo del Sistema

```
┌─────────────────┐
│  Usuario Input  │
│    (prompt)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Prompt Analyzer │  → Extrae: tipo, nicho, producto, características
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Query Generator │  → Genera queries que encuentran webs REALES
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Serper Search  │  → Busca en Google
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Tech Analyzer │  → Detecta tecnologías (WebTech)
│ PageSpeed (opt) │  → Analiza métricas
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│Domain Validator │  → Calcula match score
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Resultados    │  → Dominios que CUMPLEN el prompt
└─────────────────┘
```

## Configuración

Las API keys están en `config/settings.py`:

```python
# Serper API
SERPER_API_KEY = "tu_api_key"

# PageSpeed Insights API
PAGESPEED_API_KEY = "tu_api_key"
```

También puedes usar variables de entorno:
```bash
export SERPER_API_KEY="tu_api_key"
export PAGESPEED_API_KEY="tu_api_key"
```
