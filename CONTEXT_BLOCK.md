# 🎯 DOMAIN FINDER - BLOQUE DE CONTEXTO PARA AGENTES

> **IMPORTANTE**: Este documento contiene TODO el contexto necesario para continuar el desarrollo del software. Léelo completamente antes de hacer cualquier cambio.

---

## 📋 RESUMEN EJECUTIVO

**Domain Finder** es un software que, dado un prompt en lenguaje natural, encuentra dominios que **SEAN** lo que describe el prompt, NO webs que hablen sobre el tema.

### El Problema que Resuelve
Cuando buscas "ecommerce" en Google, obtienes artículos sobre "qué es ecommerce" o plataformas como Shopify. Este software encuentra **tiendas online reales** que venden productos.

### Ejemplos de Prompts
```
"ecommerce de electrónica"           → Tiendas que venden electrónica
"agencia de marketing digital"       → Agencias reales, no blogs sobre marketing
"saas de gestión de proyectos"       → Herramientas SaaS reales
"tienda de ropa old money"           → Tiendas con ese estilo específico
"ecommerce sin shopify"              → Tiendas que NO usan Shopify
"webs con hubspot"                   → Webs que usan HubSpot CRM
"tiendas online sin CRM"             → Tiendas sin ningún sistema CRM
```

---

## 🔑 API KEYS Y SERVICIOS

### Variables de Entorno (.env)
```bash
SERPER_API_KEY=<tu-api-key>      # Búsqueda web (Google)
GEMINI_API_KEY=<tu-api-key>      # Interpretación de prompts con IA
PAGESPEED_API_KEY=<tu-api-key>   # Métricas de rendimiento (opcional)
```

### APIs Utilizadas

| API | Función | Límites |
|-----|---------|---------|
| **Serper** | Búsqueda en Google | ~2,500 búsquedas/mes (free tier) |
| **Gemini 2.0 Flash** | Parser semántico de prompts | Rate limits variables |
| **PageSpeed Insights** | Métricas de rendimiento | 25,000 requests/día (gratis) |

### Binarios Externos (subprocess)

| Herramienta | Función | Comando |
|-------------|---------|---------|
| **wappalyzergo** | Detección de tecnologías web | `wappalyzergo -url [URL] -json` |
| **Playwright** | Browser automation (contactos) | Python library (chromium) |

---

## 🏗️ ARQUITECTURA DEL SISTEMA

### Estructura de Archivos
```
/workspace/
├── config/
│   └── settings.py                    # API keys y configuración (singleton)
├── src/
│   ├── prompt_interpreter/
│   │   ├── gemini_interpreter.py      # Interpreta prompts con Gemini AI
│   │   ├── semantic_parser.py         # Parser semántico avanzado (JSON estructurado)
│   │   ├── intent_detector.py         # Detección de intención del usuario
│   │   └── query_generator.py         # Generador de queries optimizados para Serper
│   ├── web_search/
│   │   └── serper_search.py           # Búsqueda web con Serper API
│   ├── web_analyzer/
│   │   ├── wappalyzer_analyzer.py     # Detección de tecnologías (wappalyzergo)
│   │   ├── pagespeed_analyzer.py      # Métricas con PageSpeed API
│   │   ├── contact_extractor.py       # Extracción de contactos (Playwright)
│   │   ├── hybrid_extractor.py        # ⭐ Sistema híbrido Katana+Playwright
│   │   ├── parallel_analyzer.py       # Análisis masivo con 3 workers
│   │   ├── parallel_extractor.py      # Extracción paralela de contactos
│   │   └── parallel_wappalyzer.py     # Wappalyzer paralelo con 3 workers
│   ├── domain_validator/
│   │   └── validator.py               # Validación de dominios + Schema.org
│   ├── web/
│   │   ├── app.py                     # ⭐ Servidor Flask (API REST)
│   │   └── templates/
│   │       ├── index.html             # Interfaz chat-like principal
│   │       ├── analyzer.html          # Bulk analyzer (hasta 30 dominios)
│   │       └── inspect.html           # Ficha técnica de dominio
│   └── utils/
│       └── helpers.py                 # Funciones de utilidad
├── run_web.py                         # Script para iniciar servidor web
├── requirements.txt                   # Dependencias Python
└── .env                               # Variables de entorno (NO commitear)
```

---

## ⚙️ FLUJO DE BÚSQUEDA (3 FASES)

### FASE 1: Validación de Tipo de Web
```
PROMPT → SemanticParser (Gemini) → QueryGenerator → Serper Search
                                                          ↓
                                              Validación HTML + Schema.org
                                                          ↓
                                              Score de confianza inicial
```
- Analiza contenido HTML de cada web
- Extrae datos Schema.org / JSON-LD
- Verifica metadatos y estructura
- **NO usa Wappalyzer aún** (optimización)

### FASE 2: Validación de Tecnologías (Wappalyzergo)
```
Dominios de Fase 1 → ParallelWappalyzerAnalyzer (3 workers)
                              ↓
                    Detecta: CRM, Chat, Email Marketing, etc.
                              ↓
                    Aplica filtros must_have / must_not
```
- Solo para dominios que pasan Fase 1
- Ejecuta `wappalyzergo -url [URL] -json` via subprocess
- **Timeout 180s**: Si no hay resultados con tecnología, devuelve sin filtro
- **3 workers paralelos** con `ThreadPoolExecutor(3)`

### FASE 3: Extracción de Contactos (Híbrido)
```
Dominios validados → HybridContactExtractor (3 workers)
                              ↓
                    ┌─────────────────────┐
                    │ 1. Katana (7s)      │ ← requests.get() sin JS
                    │    - Footer primero │
                    │    - /contacto      │
                    └─────────────────────┘
                              ↓
                    ¿Encontró email válido?
                    ├── SÍ → SALTAR Playwright (ahorro ~70% tiempo)
                    └── NO → Playwright como fallback
                              ↓
                    ┌─────────────────────┐
                    │ 2. Playwright (15s) │ ← Renderiza JS
                    │    - Triple Salto   │
                    │    - Human simulation│
                    └─────────────────────┘
```

**Prioridad de búsqueda de contactos:**
1. **FOOTER** (90% de emails están aquí)
2. `/contacto`, `/contact`, `/about`, `/legal`, `/aviso-legal`, `/quienes-somos`

**Datos extraídos:**
- Email (con validación de calidad)
- Teléfono (español e internacional)
- Redes sociales (LinkedIn, Instagram, Twitter, Facebook)

---

## 📊 ESTRUCTURA JSON DEL SEMANTIC PARSER

El `SemanticParser` usa Gemini para analizar el prompt y devuelve este JSON:

```json
{
  "prompt_original": "ecommerce de crema facial sin shopify en madrid",
  "prompt_view": "ecommerce crema facial madrid",
  "language": {"label": "es", "confidence": 0.95},
  "intent": {"label": "PROSPECT", "confidence": 0.9},
  "type": {"label": "ecommerce", "confidence": 0.95},
  "type_alternatives": [{"label": "tienda online", "confidence": 0.8}],
  "service": [],
  "niche": ["cosmética", "crema facial"],
  "product_or_service": ["producto_fisico"],
  "business_model": ["B2C"],
  "audience": {"label": "B2C", "confidence": 0.9},
  "scale_hint": {"label": "unknown", "confidence": 0.5},
  "location": {"country": "ES", "region": "Madrid", "city": "Madrid", "confidence": 0.9},
  "quality": [],
  "must_have": [],
  "must_not": ["shopify"],
  "technical_requirements": [],
  "notes": []
}
```

**Campos críticos:**
- `must_have`: Tecnologías que DEBE tener (ej: `["hubspot", "stripe"]`)
- `must_not`: Tecnologías que NO debe tener (ej: `["shopify", "crm"]`)
- `type`: Tipo de negocio (ecommerce, agencia, saas, blog, marketplace, directorio)
- `niche`: Nicho específico del negocio

---

## 🔧 TECNOLOGÍAS DETECTABLES (Wappalyzergo)

```python
DETECTABLE_TECHNOLOGIES = {
    "crm": ["hubspot", "salesforce", "zoho", "pipedrive", "freshsales", ...],
    "email_marketing": ["mailchimp", "klaviyo", "activecampaign", "convertkit", ...],
    "live_chat": ["intercom", "drift", "crisp", "zendesk", "tidio", "tawk", ...],
    "analytics": ["google analytics", "hotjar", "mixpanel", "amplitude", ...],
    "ecommerce_platform": ["shopify", "woocommerce", "magento", "prestashop", ...],
    "payment": ["stripe", "paypal", "klarna", "redsys", "bizum", ...],
    "cms": ["wordpress", "joomla", "drupal", "wix", "squarespace", "webflow", ...],
    "frameworks": ["react", "vue", "angular", "next.js", "nuxt", ...],
    "hosting": ["aws", "google cloud", "azure", "cloudflare", "vercel", ...],
    "marketing_automation": ["marketo", "pardot", "eloqua", ...],
    "ab_testing": ["optimizely", "vwo", "ab tasty", ...],
    "popup_tools": ["optinmonster", "sumo", "privy", ...],
    "reviews": ["trustpilot", "yotpo", "judge.me", ...]
}
```

---

## ✅ VALIDACIÓN DE EMAILS (validate_email_quality)

Función en `hybrid_extractor.py` que descarta emails antes de guardarlos:

```python
def validate_email_quality(email: str) -> tuple[bool, str]:
    """
    Filtros aplicados (ultra rápido con Regex):
    1. HASH/LONGITUD: >25 chars aleatorios o >15 chars con 6+ dígitos
    2. DOMINIOS TÉCNICOS: sentry.io, amazonaws.com, example.com, etc.
    3. PALABRAS CLAVE: noreply, notification, bounce, dev, etc.
    4. EXTENSIONES: .png, .jpg, .js, .css
    5. PLACEHOLDERS: example@domain.com, your@email.com
    
    Returns: (is_valid: bool, reason: str)
    """
```

**Lista negra de dominios (40+):**
- Servicios técnicos: `sentry.io`, `ingest.io`, `amazonaws.com`, `cloudflare.com`
- Plataformas: `wix.com`, `shopify.com`, `herokuapp.com`
- Estándares: `w3.org`, `schema.org`
- Test: `example.com`, `test.com`, `localhost`

---

## 🖥️ INTERFAZ WEB

### Página Principal (`/`) - Chat-like Interface
- Input de prompt con checkboxes para seleccionar datos a extraer:
  - ☑️ Email (seleccionado por defecto)
  - ☐ Teléfono
  - ☐ Redes Sociales
- Selector de máximo de resultados (10, 20, 30, 50)
- Resultados como CSV descargable (botón "CSV")
- Menú "..." por resultado: "No guardar", "Volver a hacer búsqueda"
- Botón "Nuevo Chat" (guarda automáticamente en historial)

### Bulk Analyzer (`/analyzer`)
- Input: Textarea (1 dominio por línea) o CSV upload
- **Límite: 30 dominios máximo**
- Análisis con 3 workers paralelos
- Resultados: Tabla paginada (10/página)
- Botones: "Descargar" (individual), "Inspeccionar"

### Inspect (`/inspect/<domain>`)
- Ficha técnica profesional del dominio
- Secciones: Quick Stats, Contacto, Metadata, SSL, HTTP, Tecnologías, Páginas
- Tooltips explicativos en cada campo
- Descarga JSON

---

## 🚀 CONSTANTES Y CONFIGURACIÓN

```python
# app.py
TECHNOLOGY_FILTER_TIMEOUT = 180    # Segundos antes de fallback sin filtro tech
CONTACT_EXTRACTION_TIMEOUT = 45    # Timeout Playwright por dominio
MAX_ANALYZER_DOMAINS = 30          # Máximo dominios en bulk analyzer
PARALLEL_WORKERS = 3               # Workers concurrentes

# hybrid_extractor.py
MAX_WORKERS = 3                    # Workers para extracción híbrida
KATANA_TIMEOUT = 7                 # Segundos para requests.get() (sin JS)
PLAYWRIGHT_TIMEOUT = 15000         # Milisegundos para Playwright

# parallel_analyzer.py
MAX_WORKERS = 3                    # Workers para análisis masivo
MAX_DOMAINS = 30                   # Límite de dominios
WAPPALYZER_TIMEOUT = 10            # Segundos por dominio en Wappalyzer
PAGE_TIMEOUT = 15000               # Milisegundos para Playwright
```

---

## 📦 DEPENDENCIAS (requirements.txt)

```
# Web Search & Analysis
requests>=2.31.0
beautifulsoup4>=4.12.0

# Browser Automation
playwright>=1.40.0
# Nota: Ejecutar 'playwright install chromium' después de pip install

# AI/LLM
google-generativeai>=0.3.0

# Async support
aiohttp>=3.9.0
asyncio-throttle>=1.0.2

# Web Interface
flask>=3.0.0
flask-cors>=4.0.0

# Utils
python-dotenv>=1.0.0
rich>=13.7.0
pydantic>=2.5.0

# Testing
pytest>=7.4.0
pytest-asyncio>=0.23.0
```

---

## 🔄 COMANDOS ÚTILES

```bash
# Iniciar servidor web
python3 run_web.py

# Instalar dependencias
pip3 install -r requirements.txt

# Instalar Playwright browser
playwright install chromium

# Instalar wappalyzergo (Go)
go install -v github.com/projectdiscovery/wappalyzergo/cmd/wappalyzergo@latest

# Ejecutar tests
python3 -m pytest tests/ -v
```

---

## ⚠️ NOTAS IMPORTANTES PARA DESARROLLO

### 1. Event Loop en Flask
Flask ejecuta búsquedas en threads separados. Para usar `asyncio` (Playwright):
```python
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
try:
    result = loop.run_until_complete(async_function())
finally:
    loop.close()
    asyncio.set_event_loop(None)
```

### 2. Playwright en Codespaces/Cloud
Usar estos argumentos para el browser:
```python
BROWSER_ARGS = [
    '--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage',
    '--disable-gpu', '--disable-blink-features=AutomationControlled'
]
```

### 3. Fallback de Gemini
Si Gemini falla (rate limit, API key inválida), el sistema usa `_local_parse()` como fallback con regex. Siempre debe haber un resultado.

### 4. Almacenamiento Cloud
El usuario prioriza almacenamiento en la nube (Supabase mencionado como futuro). Actualmente usa `localStorage` en frontend para historial.

### 5. Concurrencia
**TODAS las funciones intensivas usan 3 workers paralelos:**
- `asyncio.Semaphore(3)` para I/O-bound (Playwright, aiohttp)
- `ThreadPoolExecutor(3)` para CPU-bound (subprocess de wappalyzergo)

---

## 📝 HISTORIAL DE DECISIONES TÉCNICAS

| Decisión | Razón |
|----------|-------|
| Wappalyzergo en vez de WebTech | Mayor precisión y base de datos actualizada |
| Playwright en vez de Katana | Mejor manejo de JS, más control, menos dependencias |
| Sistema híbrido Katana+Playwright | Optimización: 70% de webs se resuelven sin JS |
| 3 workers paralelos | Balance entre velocidad y recursos |
| Timeout 180s para tecnología | Evitar bloqueos en búsquedas muy específicas |
| Footer primero | 90% de emails están en el footer |
| validate_email_quality() | Evitar guardar emails basura (noreply, hashes, etc.) |

---

## 🎯 PRÓXIMOS PASOS SUGERIDOS (NO IMPLEMENTADOS)

1. **Integración Supabase** para historial persistente
2. **Cache de resultados** para evitar re-análisis
3. **Rate limiting** en el frontend
4. **Exportación a Google Sheets**
5. **Webhooks** para notificaciones
6. **API pública** con autenticación

---

## 📞 CONTACTO Y SOPORTE

- **Branch de desarrollo**: `cursor/detecci-n-de-tipo-de-web-a853`
- **Repositorio**: GitHub (privado)
- **Stack**: Python 3.10+, Flask, Playwright, Gemini AI

---

*Última actualización: Enero 2026*
*Versión del contexto: 2.0*
