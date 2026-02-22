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
from src.utils.helpers import export_to_json, export_to_csv

# Timeout para fallback sin filtro de tecnología (segundos)
TECHNOLOGY_FILTER_TIMEOUT = 180
# Timeout para extracción de contactos con Playwright (segundos)
CONTACT_EXTRACTION_TIMEOUT = 45


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
    
    @app.route('/')
    def index():
        """Página principal."""
        return render_template('index.html')
    
    @app.route('/api/search', methods=['POST'])
    def search():
        """Endpoint para iniciar búsqueda de dominios."""
        if search_state["is_searching"]:
            return jsonify({"error": "Ya hay una búsqueda en progreso"}), 400
        
        data = request.json
        prompt = data.get('prompt', '').strip()
        max_results = data.get('max_results', 20)
        extract_contacts = data.get('extract_contacts', True)
        
        if not prompt:
            return jsonify({"error": "El prompt es requerido"}), 400
        
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
                
                # === FASE 2: Verificar tecnologías con Wappalyzer ===
                validated_with_tech = []
                validated_without_tech = []
                
                start_time = time.time()
                wappalyzer = WappalyzerAnalyzer() if has_tech_filters else None
                
                search_state["status"] = "Fase 2: Analizando tecnologías..."
                total_phase2 = len(phase1_passed)
                
                for i, item in enumerate(phase1_passed):
                    elapsed = time.time() - start_time
                    
                    result = item["validation_result"]
                    sr = item["search_result"]
                    
                    # Extraer info de schema si existe
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
                    
                    # Siempre guardar en la lista sin filtro de tech
                    validated_without_tech.append(domain_info.copy())
                    
                    # Si hay filtros de tecnología, verificar con Wappalyzer
                    if has_tech_filters and wappalyzer:
                        try:
                            wap_profile = wappalyzer.analyze(sr.url)
                            
                            if wap_profile.analysis_success:
                                domain_info["tech_profile"] = {
                                    "all_techs": wap_profile.all_technologies_names[:10],
                                    "crm": wap_profile.crm,
                                    "email": wap_profile.email_marketing,
                                    "chat": wap_profile.live_chat,
                                    "analytics": wap_profile.analytics,
                                    "ecommerce": wap_profile.ecommerce,
                                    "cms": wap_profile.cms
                                }
                                domain_info["tech"] = wap_profile.ecommerce[:3]
                                domain_info["is_ecommerce"] = wap_profile.has_ecommerce
                                
                                # Verificar requisitos de tecnología
                                meets_tech, tech_reason = wappalyzer.check_technology_requirements(
                                    wap_profile,
                                    must_have=analysis.required_tools if hasattr(analysis, 'required_tools') else [],
                                    must_not=analysis.excluded_tools if hasattr(analysis, 'excluded_tools') else []
                                )
                                
                                if meets_tech:
                                    domain_info["tech_match"] = True
                                    if tech_reason:
                                        domain_info["reasons"].append(f"Tech: {tech_reason}")
                                    validated_with_tech.append(domain_info)
                        except Exception as e:
                            pass
                    
                    # Actualizar progreso
                    progress = 65 + int((i / total_phase2) * 30)
                    search_state["progress"] = min(progress, 95)
                    
                    # Mostrar estado actual
                    if has_tech_filters:
                        search_state["status"] = f"Fase 2: {i+1}/{total_phase2} | Con tech: {len(validated_with_tech)}"
                    else:
                        search_state["status"] = f"Fase 2: {i+1}/{total_phase2}"
                    
                    # Verificar timeout
                    if has_tech_filters and elapsed >= TECHNOLOGY_FILTER_TIMEOUT and len(validated_with_tech) == 0:
                        search_state["status"] = f"⚠️ Timeout ({TECHNOLOGY_FILTER_TIMEOUT}s): usando resultados sin filtro de tecnología"
                        break
                
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
                
                # === FASE 3: Extraer datos de contacto con Playwright ===
                if extract_contacts and final_results:
                    search_state["status"] = "Fase 3: Extrayendo datos de contacto..."
                    print(f"[Fase 3] Iniciando extracción de contactos para {len(final_results)} dominios")
                    
                    total_contacts = len(final_results)
                    for i, domain_info in enumerate(final_results):
                        domain_url = domain_info["url"]
                        print(f"[Fase 3] Procesando {i+1}/{total_contacts}: {domain_url}")
                        search_state["status"] = f"Fase 3: Contactos {i+1}/{total_contacts}..."
                        
                        try:
                            # Crear nuevo extractor para cada dominio (evita problemas de estado)
                            extractor = ContactExtractor(timeout=CONTACT_EXTRACTION_TIMEOUT)
                            
                            # Extracción con Playwright (campos dinámicos)
                            contact_data = extractor.extract(
                                domain_url,
                                fields=['email', 'phone', 'social', 'title']
                            )
                            
                            print(f"[Fase 3] {domain_url} -> email={contact_data.email}, social={len(contact_data.social_media)}")
                            
                            # Añadir datos de contacto al resultado
                            domain_info["contact"] = {
                                "email": contact_data.email,
                                "phone": contact_data.phone,
                                "title": contact_data.title,
                                "linkedin": contact_data.linkedin,
                                "instagram": contact_data.instagram,
                                "twitter": contact_data.twitter,
                                "facebook": contact_data.facebook,
                                "youtube": contact_data.youtube,
                                "tiktok": contact_data.tiktok,
                                "social_media": contact_data.social_media,
                                "extraction_success": contact_data.extraction_success,
                                "partial_data": contact_data.partial_data,
                                "source": contact_data.source
                            }
                            
                            # Actualizar título si encontramos uno mejor
                            if contact_data.title and (not domain_info.get("title") or len(contact_data.title) > len(domain_info.get("title", ""))):
                                domain_info["title"] = contact_data.title
                                
                        except Exception as e:
                            print(f"[Fase 3] ERROR en {domain_url}: {str(e)}")
                            # Si falla, dejar el campo de contactos con N/A
                            domain_info["contact"] = {
                                "email": None,
                                "phone": None,
                                "title": None,
                                "linkedin": None,
                                "instagram": None,
                                "twitter": None,
                                "facebook": None,
                                "youtube": None,
                                "tiktok": None,
                                "social_media": [],
                                "extraction_success": False,
                                "partial_data": False,
                                "source": "error",
                                "error": str(e)
                            }
                        
                        # Actualizar progreso
                        progress = 90 + int(((i + 1) / total_contacts) * 10)
                        search_state["progress"] = min(progress, 99)
                    
                    print(f"[Fase 3] Completada extracción de contactos")
                else:
                    # Si no se extraen contactos, añadir estructura vacía
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
            
            # Headers con datos de contacto
            headers = [
                'Dominio', 'URL', 'Confianza', 'Título',
                'Email', 'Teléfono', 
                'LinkedIn', 'Instagram', 'Twitter', 'Facebook', 'YouTube', 'TikTok'
            ]
            writer.writerow(headers)
            
            for r in search_state["results"]:
                contact = r.get('contact', {}) or {}
                row = [
                    r['domain'],
                    r['url'],
                    r['confidence'],
                    r.get('title', ''),
                    contact.get('email', '') or '',
                    contact.get('phone', '') or '',
                    contact.get('linkedin', '') or '',
                    contact.get('instagram', '') or '',
                    contact.get('twitter', '') or '',
                    contact.get('facebook', '') or '',
                    contact.get('youtube', '') or '',
                    contact.get('tiktok', '') or ''
                ]
                writer.writerow(row)
            
            return Response(
                output.getvalue(),
                mimetype='text/csv',
                headers={'Content-Disposition': 'attachment;filename=dominios.csv'}
            )
        
        return jsonify({"error": "Formato no soportado"}), 400
    
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
