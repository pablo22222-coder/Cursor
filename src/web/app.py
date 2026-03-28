"""
Interfaz web para Domain Finder.
Servidor Flask con API REST y frontend moderno.

Implementa validación en tres fases:
1. Validación de tipo de web (metadata, HTML, Schema.org)
2. Validación de tecnologías con Wappalyzergo
3. Extracción de datos de contacto con Katana

Si no hay resultados con tecnologías después de 180s, 
devuelve los mejores resultados sin filtro de tecnología.
"""
import sys
import os
import json
import webbrowser
import threading
from flask import Flask, render_template, request, jsonify, Response
from flask_cors import CORS
import time

# Añadir el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.prompt_interpreter.gemini_interpreter import GeminiInterpreter
from src.prompt_interpreter.intent_detector import IntentDetector
from src.prompt_interpreter.query_generator import QueryGenerator
from src.prompt_interpreter.semantic_parser import SemanticParser, get_technology_requirements
from src.web_search.serper_search import SerperSearch
from src.domain_validator.validator import DomainValidator
from src.web_analyzer.wappalyzer_analyzer import WappalyzerAnalyzer
from src.web_analyzer.contact_extractor import ContactExtractor
from src.web_analyzer.domain_analyzer import DomainAnalyzer
from src.web_analyzer.parallel_analyzer import analyze_domains_parallel, MAX_DOMAINS as PARALLEL_MAX_DOMAINS
from src.web_analyzer.parallel_extractor import extract_contacts_parallel
from src.web_analyzer.parallel_wappalyzer import analyze_technologies_parallel, ParallelWappalyzerAnalyzer
from src.web_analyzer.hybrid_extractor import extract_contacts_hybrid
from src.utils.helpers import export_to_json, export_to_csv

# Timeout para fallback sin filtro de tecnología (segundos)
TECHNOLOGY_FILTER_TIMEOUT = 180
# Timeout para extracción de contactos con Playwright (segundos)
CONTACT_EXTRACTION_TIMEOUT = 45
# Máximo de dominios para análisis masivo
MAX_ANALYZER_DOMAINS = 30
# Workers paralelos
PARALLEL_WORKERS = 3


def create_app():
    """Crea y configura la aplicación Flask."""
    app = Flask(__name__, 
                template_folder='templates',
                static_folder='static')
    CORS(app)
    
    # Estado global para búsquedas en progreso
    search_state = {
        "is_searching": False,
        "progress": 0,
        "status": "",
        "results": [],
        "analysis": None
    }
    
    # Estado global para análisis de dominios
    analyzer_state = {
        "is_analyzing": False,
        "progress": 0,
        "status": "",
        "detail": "",
        "results": [],
        "current_domain": ""
    }
    
    @app.route('/')
    def index():
        """Página principal."""
        return render_template('index.html')
    
    @app.route('/analyzer')
    def analyzer():
        """Página del analizador de dominios."""
        return render_template('analyzer.html')
    
    @app.route('/inspect/<path:domain>')
    def inspect(domain):
        """Página de inspección de un dominio - Ficha técnica profesional."""
        # Buscar resultado en analyzer_state
        result = None
        for r in analyzer_state["results"]:
            if r.get("domain") == domain:
                result = r
                break
        
        if not result:
            # Si no está en memoria, hacer análisis en tiempo real con parallel analyzer
            try:
                results = analyze_domains_parallel([domain])
                result = results[0] if results else {"domain": domain, "error": "No results", "success": False}
            except Exception as e:
                result = {"domain": domain, "error": str(e), "success": False}
        
        return render_template('inspect.html', domain=domain, data=result)
    
    @app.route('/api/analyzer/start', methods=['POST'])
    def start_analyzer():
        """Inicia análisis masivo de dominios con 3 workers paralelos."""
        if analyzer_state["is_analyzing"]:
            return jsonify({"error": "Ya hay un análisis en progreso"}), 400
        
        data = request.json
        domains = data.get('domains', [])
        
        if not domains:
            return jsonify({"error": "No se proporcionaron dominios"}), 400
        
        # Limitar a 30 dominios (REGLA DE NEGOCIO ESTRICTA)
        domains = [d.strip() for d in domains if d.strip()][:PARALLEL_MAX_DOMAINS]
        
        def on_progress(progress, status, completed, total):
            """Callback para actualizar progreso en tiempo real."""
            analyzer_state["progress"] = progress
            analyzer_state["status"] = status
            analyzer_state["detail"] = f"{completed} / {total} dominios (3 workers)"
        
        def run_parallel_analysis():
            analyzer_state["is_analyzing"] = True
            analyzer_state["progress"] = 0
            analyzer_state["status"] = "Iniciando 3 workers..."
            analyzer_state["detail"] = f"0 / {len(domains)} dominios"
            analyzer_state["results"] = []
            
            try:
                # Análisis paralelo con 3 workers
                results = analyze_domains_parallel(domains, on_progress=on_progress)
                analyzer_state["results"] = results
                
                analyzer_state["status"] = f"✓ {len(results)} dominios analizados"
                analyzer_state["progress"] = 100
                
            except Exception as e:
                analyzer_state["status"] = f"Error: {str(e)}"
                analyzer_state["progress"] = 100
            finally:
                analyzer_state["is_analyzing"] = False
        
        thread = threading.Thread(target=run_parallel_analysis)
        thread.start()
        
        return jsonify({
            "message": "Análisis iniciado con 3 workers",
            "domains": len(domains),
            "max_domains": PARALLEL_MAX_DOMAINS
        })
    
    @app.route('/api/analyzer/status')
    def analyzer_status():
        """Estado del análisis en curso."""
        return jsonify({
            "is_analyzing": analyzer_state["is_analyzing"],
            "progress": analyzer_state["progress"],
            "status": analyzer_state["status"],
            "detail": analyzer_state["detail"],
            "current_domain": analyzer_state["current_domain"],
            "results_count": len(analyzer_state["results"])
        })
    
    @app.route('/api/analyzer/results')
    def analyzer_results():
        """Resultados del análisis."""
        return jsonify({
            "results": analyzer_state["results"]
        })
    
    @app.route('/api/search', methods=['POST'])
    def search():
        """Endpoint para iniciar búsqueda de dominios."""
        if search_state["is_searching"]:
            return jsonify({"error": "Ya hay una búsqueda en progreso"}), 400
        
        data = request.json
        prompt = data.get('prompt', '').strip()
        max_results = data.get('max_results', 20)
        extract_fields = data.get('extract_fields', ['email'])  # Por defecto solo email
        # "fast" → solo Katana 15s | "precise" → Katana + Playwright (por defecto)
        extraction_mode = data.get('extraction_mode', 'precise')
        fast_mode = extraction_mode == 'fast'
        
        if not prompt:
            return jsonify({"error": "El prompt es requerido"}), 400
        
        # Solo extraer contactos si hay campos solicitados
        extract_contacts = len(extract_fields) > 0
        
        # Iniciar búsqueda en thread separado
        def run_search():
            search_state["is_searching"] = True
            search_state["progress"] = 0
            search_state["status"] = "Iniciando búsqueda..."
            search_state["results"] = []
            
            try:
                # 1. Analizar prompt con parser semántico
                search_state["status"] = "Analizando prompt..."
                search_state["progress"] = 5
                
                # Usar el parser semántico para obtener requisitos de tecnología
                semantic_parser = SemanticParser()
                parsed_prompt = semantic_parser.parse(prompt)
                tech_requirements = get_technology_requirements(parsed_prompt)
                
                # Determinar si hay filtros de tecnología
                has_tech_filters = bool(
                    tech_requirements.get("must_have") or 
                    tech_requirements.get("must_not") or
                    tech_requirements.get("must_have_categories") or
                    tech_requirements.get("must_not_categories")
                )
                
                search_state["progress"] = 10
                
                # Usar el intérprete para el análisis completo
                interpreter = GeminiInterpreter()
                analysis = interpreter.analyze_prompt(prompt)
                
                # Añadir requisitos de tecnología al análisis
                if tech_requirements.get("must_have") or tech_requirements.get("must_have_categories"):
                    analysis.required_tools = (
                        tech_requirements.get("must_have", []) + 
                        tech_requirements.get("must_have_categories", [])
                    )
                if tech_requirements.get("must_not") or tech_requirements.get("must_not_categories"):
                    analysis.excluded_tools = (
                        tech_requirements.get("must_not", []) + 
                        tech_requirements.get("must_not_categories", [])
                    )
                
                search_state["analysis"] = {
                    "business_type": analysis.business_type,
                    "product_category": analysis.product_category,
                    "service_type": analysis.service_type,
                    "niche": analysis.niche,
                    "queries_count": len(analysis.search_queries),
                    "queries": analysis.search_queries[:5],
                    "tech_must_have": analysis.required_tools if hasattr(analysis, 'required_tools') else [],
                    "tech_must_not": analysis.excluded_tools if hasattr(analysis, 'excluded_tools') else []
                }
                search_state["progress"] = 25
                
                # 2. Buscar webs
                search_state["status"] = "Buscando webs..."
                searcher = SerperSearch()
                search_results = searcher.search(analysis, max_results=max_results * 3)
                search_state["progress"] = 45
                search_state["status"] = f"Encontrados {len(search_results)} resultados"
                
                if not search_results:
                    search_state["status"] = "No se encontraron resultados"
                    search_state["progress"] = 100
                    search_state["is_searching"] = False
                    return
                
                # 3. Validación en dos fases
                search_state["status"] = "Fase 1: Validando tipo de web..."
                
                # Fase 1: Validar sin filtro de tecnología (solo tipo de web)
                validator = DomainValidator(use_wappalyzer=False, use_pagespeed=False)
                
                # Dominios que pasan la primera fase
                phase1_passed = []
                total = len(search_results)
                
                for i, sr in enumerate(search_results):
                    try:
                        result = validator.validate(sr, analysis)
                        if result.analysis_complete and result.confidence_score >= 40:
                            phase1_passed.append({
                                "search_result": sr,
                                "validation_result": result,
                                "confidence": result.confidence_score
                            })
                    except:
                        pass
                    
                    progress = 45 + int((i / total) * 20)
                    search_state["progress"] = min(progress, 65)
                    search_state["status"] = f"Fase 1: {i+1}/{total}"
                
                search_state["status"] = f"Fase 1 completada: {len(phase1_passed)} candidatos"
                
                if not phase1_passed:
                    search_state["status"] = "No se encontraron webs del tipo solicitado"
                    search_state["progress"] = 100
                    search_state["is_searching"] = False
                    return
                
                # Ordenar por confianza
                phase1_passed.sort(key=lambda x: x["confidence"], reverse=True)
                
                # === FASE 2: Verificar tecnologías con 3 WORKERS PARALELOS ===
                validated_with_tech = []
                validated_without_tech = []
                
                search_state["status"] = "Fase 2: Preparando análisis de tecnologías..."
                
                # Preparar lista de dominios para análisis
                domains_to_analyze = []
                for item in phase1_passed:
                    result = item["validation_result"]
                    
                    schema_info = {}
                    if result.schema_data:
                        schema_info = {
                            "types": result.schema_data.get("types", [])[:3],
                            "is_ecommerce": result.schema_data.get("is_ecommerce", False),
                            "is_service": result.schema_data.get("is_service_business", False),
                            "has_products": result.schema_data.get("has_products", False),
                            "product_count": result.schema_data.get("product_count", 0),
                            "has_reviews": result.schema_data.get("has_reviews", False),
                            "rating": result.schema_data.get("aggregate_rating")
                        }
                    
                    domain_info = {
                        "domain": result.domain,
                        "url": result.url,
                        "confidence": round(result.confidence_score, 1),
                        "title": result.page_title[:60] + "..." if len(result.page_title) > 60 else result.page_title,
                        "reasons": result.validation_reasons[:3],
                        "tech": [],
                        "tech_profile": None,
                        "is_ecommerce": False,
                        "schema": schema_info,
                        "tech_match": False
                    }
                    domains_to_analyze.append(domain_info)
                
                # Si hay filtros de tecnología, analizar con Wappalyzer en PARALELO
                if has_tech_filters and domains_to_analyze:
                    search_state["status"] = "Fase 2: Wappalyzer (3 workers paralelos)..."
                    print(f"[Fase 2] Iniciando análisis PARALELO de {len(domains_to_analyze)} dominios")
                    
                    def on_wappalyzer_progress(progress, status, completed, total):
                        phase2_progress = 65 + int((progress / 100) * 25)
                        search_state["progress"] = min(phase2_progress, 90)
                        search_state["status"] = f"Fase 2: {completed}/{total} - 3 workers"
                    
                    try:
                        # Análisis PARALELO con 3 workers
                        analyzed_domains = analyze_technologies_parallel(
                            domains_to_analyze,
                            on_progress=on_wappalyzer_progress
                        )
                        
                        # Clasificar resultados
                        parallel_wappalyzer = ParallelWappalyzerAnalyzer()
                        must_have = analysis.required_tools if hasattr(analysis, 'required_tools') else []
                        must_not = analysis.excluded_tools if hasattr(analysis, 'excluded_tools') else []
                        
                        for domain_info in analyzed_domains:
                            validated_without_tech.append(domain_info.copy())
                            
                            if parallel_wappalyzer.check_tech_requirements(domain_info, must_have, must_not):
                                domain_info["tech_match"] = True
                                validated_with_tech.append(domain_info)
                        
                        print(f"[Fase 2] Análisis PARALELO completado: {len(validated_with_tech)} cumplen requisitos")
                        
                    except Exception as e:
                        print(f"[Fase 2] ERROR en análisis paralelo: {str(e)}")
                        validated_without_tech = domains_to_analyze
                else:
                    # Sin filtros de tecnología, usar lista directamente
                    validated_without_tech = domains_to_analyze
                    search_state["progress"] = 90
                
                # === Determinar resultados finales ===
                final_results = []
                if has_tech_filters:
                    if len(validated_with_tech) > 0:
                        validated_with_tech.sort(key=lambda x: x["confidence"], reverse=True)
                        final_results = validated_with_tech[:max_results]
                        search_state["status"] = f"✓ {len(final_results)} dominios con tecnología requerida"
                    else:
                        validated_without_tech.sort(key=lambda x: x["confidence"], reverse=True)
                        final_results = validated_without_tech[:max_results]
                        search_state["status"] = f"⚠️ {len(final_results)} dominios (sin filtro de tecnología)"
                else:
                    validated_without_tech.sort(key=lambda x: x["confidence"], reverse=True)
                    final_results = validated_without_tech[:max_results]
                    search_state["status"] = f"✓ {len(final_results)} dominios encontrados"
                
                search_state["progress"] = 90
                
                # === FASE 3: EXTRACCIÓN DE CONTACTOS - 3 WORKERS ===
                if extract_contacts and final_results and extract_fields:
                    fields_msg = ", ".join(extract_fields).replace("social", "RRSS")
                    if fast_mode:
                        mode_label = "⚡ Modo Rápido (Katana, 15s/dominio)"
                    else:
                        mode_label = "⚡ Katana + 🔍 Playwright"
                    search_state["status"] = f"Fase 3: {mode_label} ({fields_msg})..."
                    print(f"[Fase 3] Iniciando extracción para {len(final_results)} dominios")
                    print(f"[Fase 3] Modo: {'Rápido (solo Katana, 15s)' if fast_mode else 'Preciso (Katana → Playwright)'}")
                    
                    def on_hybrid_progress(progress, status, completed, total):
                        """Callback para progreso híbrido."""
                        phase3_progress = 90 + int((progress / 100) * 10)
                        search_state["progress"] = min(phase3_progress, 99)
                        search_state["status"] = f"Fase 3: {status} ({completed}/{total})"
                    
                    try:
                        final_results = extract_contacts_hybrid(
                            final_results,
                            fields=extract_fields,
                            on_progress=on_hybrid_progress,
                            fast_mode=fast_mode
                        )
                        
                        # Añadir fields_requested y contar estadísticas
                        katana_count = 0
                        playwright_count = 0
                        for domain_info in final_results:
                            if domain_info.get("contact"):
                                domain_info["contact"]["fields_requested"] = extract_fields
                                method = domain_info["contact"].get("extraction_method", "")
                                if method == "katana":
                                    katana_count += 1
                                elif method in ["playwright", "both"]:
                                    playwright_count += 1
                        
                        print(f"[Fase 3] ✓ Completado: {katana_count} Katana (⚡), {playwright_count} Playwright (🔍)")
                        
                    except Exception as e:
                        print(f"[Fase 3] ERROR en extracción híbrida: {str(e)}")
                        for domain_info in final_results:
                            if not domain_info.get("contact"):
                                domain_info["contact"] = {
                                    "email": None, "phone": None,
                                    "all_emails": [], "all_phones": [],
                                    "social_media": [], "extraction_success": False,
                                    "extraction_method": "error", "source": str(e)[:50],
                                    "fields_requested": extract_fields
                                }
                else:
                    for domain_info in final_results:
                        domain_info["contact"] = None
                
                search_state["results"] = final_results
                search_state["status"] = f"✓ Completado: {len(final_results)} dominios encontrados"
                search_state["progress"] = 100
                
            except Exception as e:
                search_state["status"] = f"Error: {str(e)}"
                search_state["progress"] = 100
            finally:
                search_state["is_searching"] = False
        
        thread = threading.Thread(target=run_search)
        thread.start()
        
        return jsonify({"message": "Búsqueda iniciada"})
    
    @app.route('/api/status')
    def status():
        """Endpoint para obtener estado de la búsqueda."""
        return jsonify({
            "is_searching": search_state["is_searching"],
            "progress": search_state["progress"],
            "status": search_state["status"],
            "results_count": len(search_state["results"]),
            "analysis": search_state["analysis"]
        })
    
    @app.route('/api/results')
    def results():
        """Endpoint para obtener resultados."""
        return jsonify({
            "results": search_state["results"],
            "analysis": search_state["analysis"]
        })
    
    @app.route('/api/analyze', methods=['POST'])
    def analyze_prompt():
        """Endpoint para solo analizar el prompt sin buscar."""
        data = request.json
        prompt = data.get('prompt', '').strip()
        
        if not prompt:
            return jsonify({"error": "El prompt es requerido"}), 400
        
        try:
            detector = IntentDetector()
            intent = detector.detect(prompt)
            
            return jsonify({
                "business_type": intent.business_type,
                "confidence": round(intent.business_type_confidence * 100, 1),
                "product_category": intent.product_category,
                "service_type": intent.service_type,
                "industry": intent.industry,
                "niche": intent.niche,
                "style": intent.style,
                "location": intent.location,
                "target_audience": intent.target_audience,
                "price_range": intent.price_range,
                "main_keywords": intent.main_keywords
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    @app.route('/api/export/<format>')
    def export_results(format):
        """Endpoint para exportar resultados."""
        if not search_state["results"]:
            return jsonify({"error": "No hay resultados para exportar"}), 400
        
        if format == 'json':
            return Response(
                json.dumps(search_state["results"], indent=2, ensure_ascii=False),
                mimetype='application/json',
                headers={'Content-Disposition': 'attachment;filename=dominios.json'}
            )
        elif format == 'csv':
            import csv
            import io
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Detectar qué campos se extrajeron
            first_contact = None
            for r in search_state["results"]:
                if r.get('contact'):
                    first_contact = r['contact']
                    break
            
            fields_requested = first_contact.get('fields_requested', []) if first_contact else []
            
            # Headers dinámicos basados en campos extraídos
            headers = ['Dominio', 'URL', 'Confianza', 'Título']
            
            if 'email' in fields_requested:
                headers.extend(['Email', 'Emails_Adicionales'])
            if 'phone' in fields_requested:
                headers.extend(['Teléfono', 'Teléfonos_Adicionales'])
            if 'social' in fields_requested:
                headers.extend(['LinkedIn', 'Instagram', 'Twitter', 'Facebook', 'YouTube', 'TikTok', 'Otras_RRSS'])
            
            writer.writerow(headers)
            
            for r in search_state["results"]:
                contact = r.get('contact', {}) or {}
                
                # Base row
                row = [
                    r['domain'],
                    r['url'],
                    r['confidence'],
                    r.get('title', '')
                ]
                
                # Email columns
                if 'email' in fields_requested:
                    all_emails = contact.get('all_emails', []) or []
                    main_email = contact.get('email', '')
                    extra_emails = [e for e in all_emails if e != main_email]
                    row.extend([
                        main_email or 'N/A',
                        '; '.join(extra_emails) if extra_emails else ''
                    ])
                
                # Phone columns
                if 'phone' in fields_requested:
                    all_phones = contact.get('all_phones', []) or []
                    main_phone = contact.get('phone', '')
                    extra_phones = [p for p in all_phones if p != main_phone]
                    row.extend([
                        main_phone or 'N/A',
                        '; '.join(extra_phones) if extra_phones else ''
                    ])
                
                # Social media columns
                if 'social' in fields_requested:
                    social_media = contact.get('social_media', []) or []
                    social_by_platform = {}
                    other_social = []
                    
                    for sm in social_media:
                        platform = sm.get('platform', 'other')
                        url = sm.get('url', '')
                        if platform in ['linkedin', 'instagram', 'twitter', 'facebook', 'youtube', 'tiktok']:
                            social_by_platform[platform] = url
                        else:
                            other_social.append(url)
                    
                    row.extend([
                        social_by_platform.get('linkedin', ''),
                        social_by_platform.get('instagram', ''),
                        social_by_platform.get('twitter', ''),
                        social_by_platform.get('facebook', ''),
                        social_by_platform.get('youtube', ''),
                        social_by_platform.get('tiktok', ''),
                        '; '.join(other_social) if other_social else ''
                    ])
                
                writer.writerow(row)
            
            return Response(
                output.getvalue(),
                mimetype='text/csv',
                headers={'Content-Disposition': 'attachment;filename=dominios.csv'}
            )
        
        return jsonify({"error": "Formato no soportado"}), 400
    
    @app.route('/api/export/marketing')
    def export_marketing_csv():
        """
        Endpoint para exportar CSV personalizado para herramientas de marketing.
        Compatible con Mailchimp, HubSpot, ActiveCampaign, Brevo, etc.
        
        Query params:
        - fields: comma-separated list of fields (domain,url,email,phone,social)
        """
        import csv
        import io
        
        # Get requested fields
        fields_param = request.args.get('fields', '')
        requested_fields = [f.strip() for f in fields_param.split(',') if f.strip()]
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Si no hay campos, devolver CSV vacío (solo headers vacíos)
        if not requested_fields:
            writer.writerow([])
            return Response(
                output.getvalue(),
                mimetype='text/csv',
                headers={'Content-Disposition': 'attachment;filename=leads_marketing.csv'}
            )
        
        # Build headers based on selected fields
        # Use marketing-friendly column names
        headers = []
        if 'domain' in requested_fields:
            headers.append('Domain')
        if 'url' in requested_fields:
            headers.append('Website')
        if 'email' in requested_fields:
            headers.append('Email')
        if 'phone' in requested_fields:
            headers.append('Phone')
        if 'social' in requested_fields:
            headers.extend(['LinkedIn', 'Instagram', 'Twitter', 'Facebook', 'YouTube', 'TikTok'])
        
        writer.writerow(headers)
        
        # Write data rows
        for r in search_state["results"]:
            contact = r.get('contact', {}) or {}
            row = []
            
            if 'domain' in requested_fields:
                row.append(r.get('domain', ''))
            
            if 'url' in requested_fields:
                row.append(r.get('url', ''))
            
            if 'email' in requested_fields:
                email = contact.get('email', '')
                row.append(email if email else '')
            
            if 'phone' in requested_fields:
                phone = contact.get('phone', '')
                row.append(phone if phone else '')
            
            if 'social' in requested_fields:
                social_media = contact.get('social_media', []) or []
                social_by_platform = {
                    'linkedin': '', 'instagram': '', 'twitter': '',
                    'facebook': '', 'youtube': '', 'tiktok': ''
                }
                
                for sm in social_media:
                    platform = sm.get('platform', '')
                    url = sm.get('url', '')
                    if platform in social_by_platform:
                        social_by_platform[platform] = url
                
                row.extend([
                    social_by_platform['linkedin'],
                    social_by_platform['instagram'],
                    social_by_platform['twitter'],
                    social_by_platform['facebook'],
                    social_by_platform['youtube'],
                    social_by_platform['tiktok']
                ])
            
            writer.writerow(row)
        
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment;filename=leads_marketing.csv'}
        )
    
    return app


def run_server(host='127.0.0.1', port=5000, open_browser=True):
    """Inicia el servidor y abre el navegador."""
    app = create_app()
    
    url = f"http://{host}:{port}"
    print(f"\n🚀 Domain Finder iniciado en: {url}\n")
    
    if open_browser:
        # Abrir navegador después de un pequeño delay
        def open_browser_delayed():
            time.sleep(1.5)
            webbrowser.open(url)
        
        threading.Thread(target=open_browser_delayed).start()
    
    # Ejecutar servidor
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == '__main__':
    run_server()
