# Domain Finder 🔍

**Software profesional para encontrar dominios que SEAN lo que describes, no dominios que hablen de ello.**

## El Problema que Resuelve

Cuando buscas "ecommerce" en Google, obtienes:
- ❌ Shopify (plataforma para crear ecommerce)
- ❌ Wikipedia (definición de ecommerce)
- ❌ Blogs que hablan de ecommerce
- ❌ Tutoriales sobre cómo crear un ecommerce

**Domain Finder te da:**
- ✅ Tiendas online reales que venden productos
- ✅ Verificadas con detección de tecnología
- ✅ Filtradas por tipo de negocio real
- ✅ Con métricas de rendimiento

## Características

### 🎯 Búsqueda Inteligente
- Entiende prompts en lenguaje natural
- Detecta tipo de negocio (ecommerce, SaaS, agencia, etc.)
- Detecta categoría de producto (electrónica, moda, belleza, etc.)
- Filtra resultados educativos/informativos automáticamente

### 🔬 Detección de Tecnología (WebTech)
- Detecta CMS (WordPress, Shopify, etc.)
- Detecta plataformas ecommerce (WooCommerce, Magento, etc.)
- Identifica procesadores de pago (Stripe, PayPal)
- Detecta herramientas de analytics y marketing

### 📊 Métricas de Rendimiento (PageSpeed Insights)
- Score de rendimiento
- Score de SEO
- Accesibilidad
- Mobile-friendly
- Core Web Vitals

### 🏆 Sistema de Scoring
- Puntuación basada en múltiples factores
- Filtrado automático por umbral mínimo
- Explicación de por qué cada dominio coincide o no

## Instalación

```bash
# Clonar el repositorio
git clone <repo-url>
cd domain-finder

# Crear entorno virtual (recomendado)
python -m venv venv
source venv/bin/activate  # Linux/Mac
# o: venv\Scripts\activate  # Windows

# Instalar dependencias
pip install -r requirements.txt

# Configurar API key (obtener en https://serper.dev)
export SERPER_API_KEY="tu_api_key"
```

## Uso Rápido

### Línea de Comandos

```bash
# Búsqueda básica
python main.py "ecommerce de electronica"

# Con más opciones
python main.py "agencia de marketing digital en España" --max-results 10

# Sin análisis de PageSpeed (más rápido)
python main.py "tienda de ropa online" --no-pagespeed

# Salida en JSON
python main.py "saas de gestion" --json

# Modo verbose
python main.py "dropshipping de productos" -v
```

### API REST

```bash
# Iniciar servidor
python main.py --serve

# El servidor estará disponible en http://localhost:8000
# Documentación interactiva en http://localhost:8000/docs
```

### Uso como Librería Python

```python
import asyncio
from src.core import DomainFinder

async def main():
    # Crear instancia
    finder = DomainFinder(serper_api_key="tu_api_key")
    
    # Buscar dominios
    result = await finder.find("ecommerce de electronica en España")
    
    # Ver resultados
    print(f"Encontrados: {result.total_matches} dominios")
    for domain in result.matched_domains:
        print(f"- {domain.domain} (score: {domain.total_score:.2f})")
    
    # Analizar un dominio específico
    analysis = await finder.analyze_domain("example.com")
    print(f"Tipo: {analysis.detected_business_type}")
    print(f"CMS: {analysis.detected_cms}")
    
    # Verificar si un dominio cumple un prompt
    verification = await finder.verify_domain("example.com", "ecommerce")
    print(f"Coincide: {verification.is_match}")

asyncio.run(main())
```

## API Endpoints

### POST /search
Búsqueda completa de dominios.

```json
{
  "prompt": "ecommerce de electronica",
  "max_results": 20,
  "include_pagespeed": true,
  "min_score": 0.6
}
```

### POST /quick-search
Búsqueda rápida (solo nombres de dominio).

```json
{
  "prompt": "tienda de ropa online",
  "max_results": 10
}
```

### POST /analyze
Análisis detallado de un dominio.

```json
{
  "domain": "example.com"
}
```

### POST /verify
Verificar si un dominio cumple un prompt.

```json
{
  "domain": "example.com",
  "prompt": "ecommerce de moda"
}
```

## Tipos de Negocio Soportados

| Tipo | Descripción | Tecnologías Detectadas |
|------|-------------|----------------------|
| ecommerce | Tiendas online | Shopify, WooCommerce, Magento, Stripe |
| saas | Software como servicio | React, Vue, Node.js, Stripe |
| agencia | Agencias de servicios | WordPress, HubSpot, Calendly |
| dropshipping | Tiendas sin stock | Shopify, Oberlo, AliExpress |
| blog | Blogs y contenido | WordPress, Ghost, Medium |
| marketplace | Mercados online | Multi-vendor platforms |
| corporativo | Webs corporativas | WordPress, Webflow |
| landing | Landing pages | Unbounce, Leadpages |

## Categorías de Producto

- **electronica**: smartphones, ordenadores, tablets
- **moda**: ropa, zapatos, accesorios
- **belleza**: cosméticos, cremas, skincare
- **deportes**: fitness, running, gym
- **hogar**: decoración, muebles
- **alimentacion**: comida, gourmet
- **mascotas**: accesorios para mascotas
- **salud**: suplementos, vitaminas

## Estructura del Proyecto

```
domain-finder/
├── main.py              # Punto de entrada principal
├── requirements.txt     # Dependencias
├── README.md           
├── src/
│   ├── __init__.py
│   ├── core.py          # Orquestador principal
│   ├── api.py           # API FastAPI
│   ├── cli.py           # Interfaz de línea de comandos
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py  # Configuración y definiciones
│   ├── modules/
│   │   ├── __init__.py
│   │   ├── prompt_parser.py    # Parser de prompts
│   │   ├── search_engine.py    # Búsqueda con Serper
│   │   ├── web_analyzer.py     # Análisis WebTech + PageSpeed
│   │   └── domain_verifier.py  # Verificación y scoring
│   └── utils/
│       └── __init__.py
└── tests/
    ├── __init__.py
    ├── test_prompt_parser.py
    └── test_search_engine.py
```

## Configuración Avanzada

### Variables de Entorno

```bash
# Requerido
SERPER_API_KEY=tu_api_key

# Opcionales (tienen valores por defecto)
PAGESPEED_API_KEY=AIzaSyBRtOyTpP55RnUuu-2S7-yXiI55yhe0lWo
```

### Archivo .env

Crea un archivo `.env` en la raíz:

```env
SERPER_API_KEY=tu_api_key
```

### Configuración de Scoring

En `src/config/settings.py` puedes ajustar:

```python
class ScoringSettings:
    technology_match_weight: float = 0.35   # Peso de tecnología
    content_match_weight: float = 0.30      # Peso de contenido
    metrics_match_weight: float = 0.20      # Peso de métricas
    quality_score_weight: float = 0.15      # Peso de calidad
    minimum_score_threshold: float = 0.60   # Umbral mínimo
```

## APIs Utilizadas

### Serper API (Requerida)
- Búsquedas de Google
- Obtener API key: https://serper.dev

### Google PageSpeed Insights (Incluida)
- Métricas de rendimiento
- API key incluida (25,000 requests/día gratis)

### WebTech (Incluida)
- Detección de tecnologías
- Open source, sin límites

## Ejemplos de Uso

### Encontrar tiendas de electrónica

```bash
python main.py "ecommerce de electronica"
```

Resultado:
```
✅ MATCHING DOMAINS
1. tiendaelectronica.es
   Score: 0.85
   Type: ecommerce
   Tech: Shopify, Stripe

2. electronicsshop.com
   Score: 0.78
   Type: ecommerce
   Tech: WooCommerce, PayPal
```

### Encontrar agencias de marketing

```bash
python main.py "agencia de marketing digital en Madrid"
```

### Encontrar SaaS

```bash
python main.py "software de gestion de proyectos"
```

### Verificar un dominio específico

```bash
python -c "
import asyncio
from src.core import DomainFinder

async def verify():
    finder = DomainFinder()
    result = await finder.verify_domain('example.com', 'ecommerce')
    print(f'Match: {result.is_match}')
    print(f'Score: {result.total_score}')

asyncio.run(verify())
"
```

## Testing

```bash
# Ejecutar todos los tests
pytest tests/ -v

# Ejecutar test específico
pytest tests/test_prompt_parser.py -v
```

## Contribuir

1. Fork el repositorio
2. Crea una rama (`git checkout -b feature/nueva-funcionalidad`)
3. Commit cambios (`git commit -am 'Añadir nueva funcionalidad'`)
4. Push a la rama (`git push origin feature/nueva-funcionalidad`)
5. Crea un Pull Request

## Licencia

MIT License

## Soporte

Para reportar bugs o solicitar funcionalidades, abre un Issue en el repositorio.
