"""
Interfaz web para Domain Finder.
Servidor Flask con API REST y frontend moderno.
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
from src.web_search.serper_search import SerperSearch
from src.domain_validator.validator import DomainValidator
from src.utils.helpers import export_to_json, export_to_csv


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
        min_confidence = data.get('min_confidence', 50)
        
        if not prompt:
            return jsonify({"error": "El prompt es requerido"}), 400
        
        # Iniciar búsqueda en thread separado
        def run_search():
            search_state["is_searching"] = True
            search_state["progress"] = 0
            search_state["status"] = "Iniciando búsqueda..."
            search_state["results"] = []
            
            try:
                # 1. Analizar prompt
                search_state["status"] = "Analizando prompt..."
                search_state["progress"] = 10
                
                interpreter = GeminiInterpreter()
                analysis = interpreter.analyze_prompt(prompt)
                
                search_state["analysis"] = {
                    "business_type": analysis.business_type,
                    "product_category": analysis.product_category,
                    "service_type": analysis.service_type,
                    "niche": analysis.niche,
                    "queries_count": len(analysis.search_queries),
                    "queries": analysis.search_queries[:5]
                }
                search_state["progress"] = 25
                
                # 2. Buscar webs
                search_state["status"] = "Buscando webs..."
                searcher = SerperSearch()
                search_results = searcher.search(analysis, max_results=max_results * 3)
                search_state["progress"] = 50
                search_state["status"] = f"Encontrados {len(search_results)} resultados"
                
                if not search_results:
                    search_state["status"] = "No se encontraron resultados"
                    search_state["progress"] = 100
                    search_state["is_searching"] = False
                    return
                
                # 3. Validar dominios
                search_state["status"] = "Validando dominios..."
                validator = DomainValidator(use_webtech=True, use_pagespeed=False)
                
                validated = []
                total = len(search_results)
                for i, sr in enumerate(search_results):
                    try:
                        result = validator.validate(sr, analysis)
                        if result.is_valid and result.confidence_score >= min_confidence:
                            validated.append({
                                "domain": result.domain,
                                "url": result.url,
                                "confidence": round(result.confidence_score, 1),
                                "title": result.page_title[:60] + "..." if len(result.page_title) > 60 else result.page_title,
                                "reasons": result.validation_reasons[:2],
                                "tech": result.tech_profile.get("ecommerce_platform", []) if result.tech_profile else [],
                                "is_ecommerce": result.tech_profile.get("is_ecommerce", False) if result.tech_profile else False
                            })
                            
                            if len(validated) >= max_results:
                                break
                    except:
                        pass
                    
                    progress = 50 + int((i / total) * 45)
                    search_state["progress"] = min(progress, 95)
                    search_state["status"] = f"Validando... {i+1}/{total}"
                
                # Ordenar por confianza
                validated.sort(key=lambda x: x["confidence"], reverse=True)
                search_state["results"] = validated[:max_results]
                search_state["status"] = f"Completado: {len(validated)} dominios válidos"
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
            writer.writerow(['Dominio', 'URL', 'Confianza', 'Título'])
            for r in search_state["results"]:
                writer.writerow([r['domain'], r['url'], r['confidence'], r.get('title', '')])
            
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
