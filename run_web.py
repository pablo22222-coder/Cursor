#!/usr/bin/env python3
"""
Script para iniciar la interfaz web de Domain Finder.

Uso:
    python run_web.py
    python run_web.py --port 8080
    python run_web.py --no-browser
"""
import argparse
import sys
import os
from pathlib import Path

# ── CRÍTICO: cargar .env ANTES de cualquier otro import del proyecto ──────────
# Si dotenv se carga tarde, os.getenv() en los providers devuelve '' y los LLM
# se marcan como no disponibles aunque la API key esté correctamente en .env.
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path, override=True)
        print(f"[Entorno] .env cargado desde {_env_path}")
    else:
        load_dotenv(override=True)   # busca automáticamente
except ImportError:
    print("[Entorno] ⚠️  python-dotenv no instalado — las API keys deben estar en variables de sistema")

# Añadir el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.web.app import run_server


def main():
    parser = argparse.ArgumentParser(description='Iniciar Domain Finder Web Interface')
    parser.add_argument('--host', default='127.0.0.1', help='Host (default: 127.0.0.1)')
    parser.add_argument('--port', '-p', type=int, default=5000, help='Puerto (default: 5000)')
    parser.add_argument('--no-browser', action='store_true', help='No abrir navegador automáticamente')
    
    args = parser.parse_args()
    
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║              🔍 DOMAIN FINDER                             ║
    ║                                                           ║
    ║   Interfaz web para búsqueda inteligente de dominios      ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    
    run_server(
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser
    )


if __name__ == '__main__':
    main()
