"""
Precision-mode pipeline (Fase 2).

Conjunto de módulos que solo se usan cuando el extractor está en `fast_mode=False`
(modo de precisión) tanto en el flujo de descripción de web como en el de
descripción de producto. Cubre:

  - html_context     → descarga HTML con httpx + extracción de capas con BS4/lxml
  - dna_extractor    → 6 dimensiones de huella técnica (sin base de datos)
  - tech_scanner     → controlador Wappalyzer + DNA dirigido
  - pagespeed_targeted → PageSpeed Insights enfocado a las dimensiones pedidas
  - precision_judge  → veredicto SI/NO con Groq como auditor final

Ningún módulo depende de Playwright ni navegadores headless.
"""
