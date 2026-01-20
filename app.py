#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Domain Finder - Interfaz Web con Streamlit
"""
import streamlit as st
import sys
import os

# Añadir el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.main import DomainFinder
from src.prompt_analyzer import PromptAnalyzer

# Configuración de la página
st.set_page_config(
    page_title="Domain Finder",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS personalizado
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1E88E5;
        text-align: center;
        margin-bottom: 1rem;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #666;
        text-align: center;
        margin-bottom: 2rem;
    }
    .domain-card {
        background-color: #f8f9fa;
        border-radius: 10px;
        padding: 1rem;
        margin-bottom: 1rem;
        border-left: 4px solid #1E88E5;
    }
    .score-high {
        color: #28a745;
        font-weight: bold;
    }
    .score-medium {
        color: #ffc107;
        font-weight: bold;
    }
    .score-low {
        color: #dc3545;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# Header
st.markdown('<p class="main-header">🔍 Domain Finder</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-header">Encuentra webs que SEAN lo que buscas, no webs que hablen de eso</p>', unsafe_allow_html=True)

# Sidebar con configuración
st.sidebar.header("⚙️ Configuración")

max_results = st.sidebar.slider(
    "Número de resultados",
    min_value=5,
    max_value=30,
    value=10,
    step=5
)

min_score = st.sidebar.slider(
    "Puntuación mínima",
    min_value=10,
    max_value=80,
    value=30,
    step=10,
    help="Solo muestra dominios con esta puntuación mínima de coincidencia"
)

validate_tech = st.sidebar.checkbox(
    "Analizar tecnologías (WebTech)",
    value=True,
    help="Detecta CMS, plataformas de ecommerce, pagos, etc."
)

analyze_pagespeed = st.sidebar.checkbox(
    "Analizar PageSpeed",
    value=False,
    help="Analiza métricas de rendimiento y SEO (más lento)"
)

# Área principal
st.markdown("### 📝 ¿Qué tipo de webs buscas?")

# Input del prompt
prompt = st.text_input(
    "Escribe tu búsqueda",
    placeholder="Ejemplo: ecommerce de electrónica, agencia de marketing digital, tienda de ropa old money...",
    label_visibility="collapsed"
)

# Ejemplos de prompts
st.markdown("**Ejemplos:** `ecommerce de crema facial` · `agencia de marketing digital` · `saas de gestión de proyectos` · `tienda de ropa old money`")

# Botón de búsqueda
col1, col2, col3 = st.columns([1, 1, 1])
with col2:
    search_button = st.button("🔍 Buscar Dominios", type="primary", use_container_width=True)

# Separador
st.markdown("---")

# Ejecutar búsqueda
if search_button and prompt:
    # Mostrar análisis del prompt
    with st.expander("📊 Análisis del Prompt", expanded=True):
        analyzer = PromptAnalyzer()
        intent = analyzer.analyze(prompt)
        
        # Mostrar prompt limpio si es diferente
        if intent.cleaned_prompt != intent.original_prompt.lower():
            st.info(f"🧹 **Prompt limpio:** {intent.cleaned_prompt}")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Tipo de Negocio", intent.business_type.value.upper())
        with col2:
            st.metric("Nicho", intent.niche or "No detectado")
        with col3:
            st.metric("Producto/Servicio", intent.product_service or "No detectado")
        with col4:
            st.metric("Confianza", f"{intent.confidence}%")
        
        # Mostrar exclusiones y requisitos si existen
        if intent.exclusions or intent.requirements:
            col1, col2 = st.columns(2)
            with col1:
                if intent.exclusions:
                    st.warning(f"❌ **Excluir:** {', '.join(intent.exclusions)}")
            with col2:
                if intent.requirements:
                    st.success(f"✅ **Requiere:** {', '.join(intent.requirements)}")
    
    # Buscar dominios
    with st.spinner("🔍 Buscando dominios..."):
        finder = DomainFinder()
        
        try:
            domains = finder.find(
                prompt=prompt,
                max_results=max_results,
                validate_tech=validate_tech,
                analyze_pagespeed=analyze_pagespeed,
                min_match_score=min_score
            )
            
            if domains:
                st.success(f"✅ Encontrados {len(domains)} dominios que cumplen tu búsqueda")
                
                # Mostrar resultados
                st.markdown("### 🌐 Dominios Encontrados")
                
                for i, domain in enumerate(domains):
                    with st.container():
                        # Score color
                        if domain.analysis:
                            score = domain.analysis.match_score
                            if score >= 60:
                                score_class = "score-high"
                            elif score >= 40:
                                score_class = "score-medium"
                            else:
                                score_class = "score-low"
                        else:
                            score = 0
                            score_class = "score-low"
                        
                        # Card del dominio
                        col1, col2 = st.columns([3, 1])
                        
                        with col1:
                            st.markdown(f"#### {i+1}. [{domain.domain}]({domain.url})")
                            if domain.title:
                                st.markdown(f"**{domain.title}**")
                            if domain.description:
                                st.markdown(f"_{domain.description[:200]}..._" if len(domain.description or "") > 200 else f"_{domain.description}_")
                        
                        with col2:
                            st.metric("Score", f"{score}/100")
                        
                        # Detalles expandibles
                        if domain.analysis:
                            with st.expander("Ver detalles"):
                                det_col1, det_col2 = st.columns(2)
                                
                                with det_col1:
                                    st.markdown("**Tipo detectado:**")
                                    st.write(domain.analysis.detected_business_type.value)
                                    
                                    if domain.analysis.match_reasons:
                                        st.markdown("**Razones de coincidencia:**")
                                        for reason in domain.analysis.match_reasons:
                                            st.write(f"• {reason}")
                                
                                with det_col2:
                                    if domain.analysis.tech_stack:
                                        tech = domain.analysis.tech_stack
                                        st.markdown("**Tecnologías detectadas:**")
                                        if tech.cms:
                                            st.write(f"• CMS: {tech.cms}")
                                        if tech.ecommerce_platform:
                                            st.write(f"• Ecommerce: {tech.ecommerce_platform}")
                                        if tech.payment_processors:
                                            st.write(f"• Pagos: {', '.join(tech.payment_processors)}")
                                        if tech.analytics:
                                            st.write(f"• Analytics: {', '.join(tech.analytics)}")
                                        if tech.all_technologies.get("detected"):
                                            st.write(f"• Otras: {', '.join(tech.all_technologies['detected'][:5])}")
                                    
                                    if domain.analysis.pagespeed:
                                        ps = domain.analysis.pagespeed
                                        st.markdown("**Métricas PageSpeed:**")
                                        if ps.performance_score:
                                            st.write(f"• Performance: {ps.performance_score}/100")
                                        if ps.seo_score:
                                            st.write(f"• SEO: {ps.seo_score}/100")
                                        if ps.is_mobile_friendly:
                                            st.write("• ✅ Mobile Friendly")
                        
                        st.markdown("---")
            else:
                st.warning("⚠️ No se encontraron dominios que cumplan tu búsqueda. Intenta con términos más específicos o reduce la puntuación mínima.")
                
        except Exception as e:
            st.error(f"❌ Error durante la búsqueda: {str(e)}")

elif search_button and not prompt:
    st.warning("⚠️ Por favor, escribe qué tipo de webs buscas")

# Footer
st.markdown("---")
st.markdown(
    "<p style='text-align: center; color: #888;'>Domain Finder v1.0 | Powered by Serper, WebTech & PageSpeed APIs</p>",
    unsafe_allow_html=True
)
