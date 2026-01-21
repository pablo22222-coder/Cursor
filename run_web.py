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
