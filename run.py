#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script principal para ejecutar Domain Finder.

Uso:
    python run.py "ecommerce de crema facial"
    python run.py "agencia de marketing digital" --pagespeed
    python run.py "saas de gestión de proyectos" --results 20
"""
import argparse
import json
import sys

# Añadir el directorio raíz al path
sys.path.insert(0, '/workspace')

from src.main import DomainFinder


def main():
    parser = argparse.ArgumentParser(
        description="Encuentra dominios que cumplan con tu prompt"
    )
    
    parser.add_argument(
        "prompt",
        type=str,
        help="Descripción de las webs que buscas (ej: 'ecommerce de electrónica')"
    )
    
    parser.add_argument(
        "--results", "-r",
        type=int,
        default=10,
        help="Número máximo de resultados (default: 10)"
    )
    
    parser.add_argument(
        "--pagespeed", "-p",
        action="store_true",
        help="Analizar métricas de PageSpeed (más lento pero más info)"
    )
    
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="No validar tecnologías (más rápido pero menos preciso)"
    )
    
    parser.add_argument(
        "--min-score", "-s",
        type=int,
        default=40,
        help="Puntuación mínima para incluir un resultado (default: 40)"
    )
    
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Salida en formato JSON"
    )
    
    args = parser.parse_args()
    
    # Crear el buscador
    finder = DomainFinder()
    
    # Buscar dominios
    domains = finder.find(
        prompt=args.prompt,
        max_results=args.results,
        validate_tech=not args.no_validate,
        analyze_pagespeed=args.pagespeed,
        min_match_score=args.min_score
    )
    
    # Mostrar resultados
    if args.json:
        report = finder.get_detailed_report(domains)
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print("\n" + "="*60)
        finder.print_results(domains)
        print("="*60)
        
        if domains:
            print(f"\n✅ Encontrados {len(domains)} dominios que cumplen el prompt")
        else:
            print("\n❌ No se encontraron dominios que cumplan el prompt")
            print("   Intenta con un prompt más específico o reduce el min-score")


if __name__ == "__main__":
    main()
