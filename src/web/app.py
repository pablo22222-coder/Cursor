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

from src.prompt_interpreter.intent_detector import IntentDetector
from src.services.ai_interpreter import AIInterpreter, SearchIntent
from src.web_search.serper_search import SerperSearch, SearchResult
from src.domain_validator.validator import DomainValidator
from src.web_analyzer.parallel_analyzer import analyze_domains_parallel, MAX_DOMAINS as PARALLEL_MAX_DOMAINS
from src.web_analyzer.hybrid_extractor import extract_contacts_hybrid
from src.web_analyzer.domain_pipeline import DomainPipelineOrchestrator, NUM_WORKERS
from src.utils.resource_throttle import reset_throttle, get_throttle
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
        "analysis": None,
        # Estado individual de cada worker (actualizado en tiempo real)
        "workers": [
            {"worker_id": i + 1, "phase": "idle", "phase_label": "En espera", "domain": "", "detail": ""}
            for i in range(NUM_WORKERS)
        ],
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
            search_state["status"] = "Analizando prompt..."
            search_state["results"] = []
            search_state["workers"] = [
                {"worker_id": i + 1, "phase": "idle", "phase_label": "En espera", "domain": "", "detail": ""}
                for i in range(NUM_WORKERS)
            ]

            try:
                # ── PASO 0: Interpretar prompt con AIManager ──────────────
                search_state["progress"] = 5
                search_state["status"] = "Analizando prompt con IA..."

                intent: SearchIntent = AIInterpreter().interpret(prompt)

                search_state["progress"] = 20
                search_state["analysis"] = {
                    "business_type":   intent.business_type,
                    "product_category":intent.product_category,
                    "service_type":    intent.service_type,
                    "niche":           intent.niche,
                    "queries_count":   len(intent.search_queries),
                    "queries":         intent.search_queries[:5],
                    "tech_must_have":  intent.must_have,
                    "tech_must_not":   intent.must_not,
                    "provider_used":   intent.provider_used,
                    "confidence":      intent.confidence,
                    "notes":           intent.analysis_notes,
                }

                # Build tech_requirements dict compatible with pipeline
                tech_requirements = {
                    "must_have":            intent.must_have,
                    "must_not":             intent.must_not,
                    "must_have_categories": [],
                    "must_not_categories":  [],
                }

                # ── PASO 1: Obtener candidatos con Serper ─────────────────
                search_state["status"] = f"Buscando con {len(intent.search_queries)} queries generadas por IA..."
                searcher = SerperSearch()
                search_results = searcher.search(intent, max_results=max_results * 3)
                search_state["progress"] = 35
                search_state["status"] = f"Candidatos obtenidos: {len(search_results)} — Lanzando 3 workers..."

                if not search_results:
                    search_state["status"] = "No se encontraron resultados"
                    search_state["progress"] = 100
                    search_state["is_searching"] = False
                    return

                # ── PASO 2: Pipeline autónomo por dominio con 3 workers ───
                # Cada worker toma un dominio de la cola y ejecuta:
                #   Fase 1 (validación) → Fase 2 (tech) → Fase 3 (contacto)
                def on_pipeline_progress(worker_states, completed, total):
                    # Actualizar estado de cada worker en tiempo real
                    search_state["workers"] = worker_states

                    # Progreso global: 35-99% durante el pipeline
                    if total > 0:
                        pipeline_pct = int((completed / total) * 100)
                        global_progress = 35 + int(pipeline_pct * 0.64)
                        search_state["progress"] = min(global_progress, 99)

                    # Construir mensaje de estado con resumen de los 3 workers
                    active = [
                        w for w in worker_states
                        if w["phase"] not in ("idle", "done", "rejected", "error")
                    ]
                    if active:
                        parts = [
                            f"W{w['worker_id']}: [{w['phase_label']}] {w['domain']}"
                            for w in active[:3]
                        ]
                        search_state["status"] = "  |  ".join(parts)
                    else:
                        search_state["status"] = f"Procesando... {completed}/{total}"

                # Crear throttle fresco para esta búsqueda
                throttle = reset_throttle()

                orchestrator = DomainPipelineOrchestrator(
                    analysis=intent,
                    tech_requirements=tech_requirements,
                    extract_fields=extract_fields if extract_contacts else [],
                    fast_mode=fast_mode,
                    max_results=max_results,
                    on_progress=on_pipeline_progress,
                    throttle=throttle,
                )

                final_results = orchestrator.run(search_results)

                if not final_results:
                    search_state["status"] = "No se encontraron webs del tipo solicitado"
                    search_state["progress"] = 100
                    search_state["is_searching"] = False
                    return

                search_state["results"] = final_results
                search_state["status"] = f"✓ Completado: {len(final_results)} dominios encontrados"
                search_state["progress"] = 100

            except Exception as e:
                search_state["status"] = f"Error: {str(e)}"
                search_state["progress"] = 100
            finally:
                search_state["is_searching"] = False
                # Resetear workers a idle al terminar
                search_state["workers"] = [
                    {"worker_id": i + 1, "phase": "idle", "phase_label": "En espera", "domain": "", "detail": ""}
                    for i in range(NUM_WORKERS)
                ]

        thread = threading.Thread(target=run_search)
        thread.start()
        
        return jsonify({"message": "Búsqueda iniciada"})
    
    @app.route('/api/status')
    def status():
        """Endpoint para obtener estado de la búsqueda."""
        throttle_data = get_throttle().status_dict()
        return jsonify({
            "is_searching":  search_state["is_searching"],
            "progress":      search_state["progress"],
            "status":        search_state["status"],
            "results_count": len(search_state["results"]),
            "analysis":      search_state["analysis"],
            "workers":       search_state.get("workers", []),
            "throttle":      throttle_data,
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
