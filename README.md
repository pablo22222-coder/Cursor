# Domain Finder 🔍

Sistema inteligente para encontrar dominios que **SEAN** lo que describe el prompt, no webs que hablen sobre el tema.

## 🎯 Problema que resuelve

Cuando buscas "ecommerce" en Google, obtienes artículos sobre "qué es ecommerce" o plataformas como Shopify. Este software encuentra **tiendas online reales** que venden productos.

### Ejemplos de uso:
- `ecommerce de electrónica` → Encuentra tiendas que venden electrónica
- `agencia de marketing digital` → Encuentra agencias reales, no blogs sobre marketing
- `saas de gestión de proyectos` → Encuentra herramientas SaaS reales
- `tienda de ropa old money` → Encuentra tiendas con ese estilo específico

## 🏗️ Arquitectura

```
/workspace/
├── config/
│   ├── __init__.py
│   └── settings.py           # API keys y configuración
├── src/
│   ├── __init__.py
│   ├── main.py               # Punto de entrada principal
│   ├── prompt_interpreter/
│   │   ├── __init__.py
│   │   └── gemini_interpreter.py   # Interpreta prompts con Gemini AI
│   ├── web_search/
│   │   ├── __init__.py
│   │   └── serper_search.py        # Búsqueda web con Serper API
│   ├── web_analyzer/
│   │   ├── __init__.py
│   │   ├── pagespeed_analyzer.py   # Métricas con PageSpeed API
│   │   └── webtech_analyzer.py     # Detección de tecnologías
│   ├── domain_validator/
│   │   ├── __init__.py
│   │   └── validator.py            # Validación de dominios
│   └── utils/
│       ├── __init__.py
│       └── helpers.py              # Funciones de utilidad
├── tests/
│   └── test_main.py
├── requirements.txt
└── README.md
```

## 🔧 Instalación

```bash
# Clonar el repositorio
git clone <repo-url>
cd workspace

# Instalar dependencias
pip install -r requirements.txt
```

## 🚀 Uso

### Línea de comandos

```bash
# Búsqueda básica
python -m src.main "ecommerce de electrónica"

# Con más resultados
python -m src.main "agencia de marketing digital" --max-results 30

# Exportar a JSON
python -m src.main "saas de gestión" --export json

# Con análisis de rendimiento (más lento)
python -m src.main "tienda online lenta" --use-pagespeed

# Modo silencioso (solo dominios)
python -m src.main "ecommerce" -q
```

### Como librería Python

```python
from src.main import DomainFinder

# Crear instancia
finder = DomainFinder(
    use_webtech=True,      # Analizar tecnologías
    use_pagespeed=False,   # No analizar rendimiento
    verbose=True           # Mostrar progreso
)

# Buscar dominios
results = finder.find_domains(
    prompt="ecommerce de cosméticos naturales",
    max_results=20,
    min_confidence=50.0
)

# Procesar resultados
for result in results:
    print(f"{result.domain} - Confianza: {result.confidence_score}%")
    if result.tech_profile and result.tech_profile.get("is_ecommerce"):
        print(f"  Plataforma: {result.tech_profile.get('ecommerce_platform')}")
```

## 📊 Flujo del sistema

```
1. PROMPT → "ecommerce de crema facial"
        ↓
2. GEMINI INTERPRETER
   - Detecta: tipo=ecommerce, categoría=cosméticos
   - Genera queries inteligentes:
     • "tienda crema facial online"
     • "comprar crema facial"
     • "cosmética facial shop"
        ↓
3. SERPER SEARCH
   - Ejecuta búsquedas en Google
   - Filtra dominios duplicados
   - Excluye Wikipedia, Medium, etc.
        ↓
4. DOMAIN VALIDATOR
   - Analiza contenido de cada web
   - Detecta indicadores de ecommerce
   - Verifica tecnologías (Shopify, WooCommerce)
   - Calcula score de confianza
        ↓
5. RESULTADOS
   - Lista de dominios válidos
   - Ordenados por confianza
   - Con metadatos (tecnologías, keywords)
```

## 🔑 APIs utilizadas

### 1. Gemini AI (Google)
- **Función**: Interpreta el prompt y genera queries inteligentes
- **Ventaja**: Entiende contexto y genera búsquedas relevantes

### 2. Serper API
- **Función**: Búsqueda en Google
- **Ventaja**: Resultados de Google sin scraping

### 3. WebTech
- **Función**: Detecta tecnologías web
- **Detecta**: 
  - CMS (WordPress, Joomla)
  - E-commerce (Shopify, WooCommerce, Magento)
  - Frameworks (React, Vue, Angular)
  - Analytics (Google Analytics, Hotjar)
  - Payment (Stripe, PayPal)

### 4. PageSpeed Insights API (Opcional)
- **Función**: Analiza rendimiento
- **Métricas**:
  - Performance score (0-100)
  - SEO score
  - Core Web Vitals
  - Mobile-friendly

## 📋 Opciones de línea de comandos

| Opción | Descripción |
|--------|-------------|
| `prompt` | Descripción del tipo de webs a buscar |
| `--max-results, -n` | Número máximo de dominios (default: 20) |
| `--min-confidence, -c` | Confianza mínima 0-100 (default: 50) |
| `--export, -e` | Exportar: json, csv, both |
| `--use-pagespeed` | Usar PageSpeed para métricas |
| `--no-webtech` | No usar WebTech |
| `--quiet, -q` | Solo mostrar dominios |

## 🎯 Tipos de búsqueda soportados

### E-commerce
```bash
python -m src.main "ecommerce de electrónica"
python -m src.main "tienda de ropa online"
python -m src.main "shop de cosméticos naturales"
```

### SaaS
```bash
python -m src.main "saas de gestión de proyectos"
python -m src.main "software de contabilidad"
python -m src.main "plataforma de email marketing"
```

### Agencias/Servicios
```bash
python -m src.main "agencia de marketing digital"
python -m src.main "estudio de diseño web"
python -m src.main "consultoría de negocios"
```

### Con especificaciones adicionales
```bash
python -m src.main "ecommerce de ropa old money"
python -m src.main "tienda de electrónica con envío gratis"
python -m src.main "agencia de SEO en Madrid"
```

### Con métricas de rendimiento
```bash
python -m src.main "webs con velocidad de carga lenta" --use-pagespeed
python -m src.main "ecommerce rápido" --use-pagespeed
```

## 📤 Formato de salida

### JSON Export
```json
{
  "generated_at": "2024-01-15T10:30:00",
  "total_results": 15,
  "valid_count": 15,
  "results": [
    {
      "domain": "example-shop.com",
      "url": "https://example-shop.com",
      "is_valid": true,
      "confidence_score": 85.5,
      "validation_reasons": ["Contenido relevante", "Tecnologías compatibles"],
      "tech_profile": {
        "is_ecommerce": true,
        "ecommerce_platform": ["Shopify"],
        "payment": ["Stripe", "PayPal"]
      }
    }
  ]
}
```

## ⚙️ Configuración

Las API keys están en `config/settings.py`. También puedes usar variables de entorno:

```bash
export SERPER_API_KEY="tu-api-key"
export GEMINI_API_KEY="tu-api-key"
export PAGESPEED_API_KEY="tu-api-key"
```

## 🧪 Tests

```bash
# Ejecutar tests
pytest tests/ -v

# Solo tests unitarios (sin APIs)
pytest tests/ -v -m "not integration"
```

## 📝 Licencia

MIT License
