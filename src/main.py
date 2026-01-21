"""
Domain Finder - Sistema principal de búsqueda de dominios.

Este software encuentra webs que SEAN lo que describe el prompt,
no webs que hablen sobre el tema.

Uso:
    python -m src.main "ecommerce de electrónica"
    python -m src.main "agencia de marketing digital en Madrid"
    python -m src.main "saas de gestión de proyectos"
"""
import sys
import argparse
import json
from typing import List, Optional
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.panel import Panel

# Añadir el directorio raíz al path
sys.path.insert(0, '/workspace')

from config.settings import get_settings
from src.prompt_interpreter.gemini_interpreter import GeminiInterpreter, PromptAnalysis
from src.web_search.serper_search import SerperSearch, SearchResult
from src.web_analyzer.webtech_analyzer import WebTechAnalyzer
from src.web_analyzer.pagespeed_analyzer import PageSpeedAnalyzer
from src.domain_validator.validator import DomainValidator, ValidationResult
from src.utils.helpers import format_results, export_to_json, export_to_csv, calculate_stats


console = Console()


class DomainFinder:
    """
    Sistema principal para encontrar dominios basados en un prompt.
    
    Flujo:
    1. Interpreta el prompt con Gemini
    2. Busca webs con Serper usando queries inteligentes
    3. Valida cada web para confirmar que ES lo que se busca
    4. Retorna dominios válidos ordenados por confianza
    """
    
    def __init__(self, 
                 use_webtech: bool = True,
                 use_pagespeed: bool = False,
                 verbose: bool = True):
        """
        Args:
            use_webtech: Usar WebTech para análisis de tecnologías
            use_pagespeed: Usar PageSpeed para métricas (más lento)
            verbose: Mostrar progreso detallado
        """
        self.settings = get_settings()
        self.verbose = verbose
        
        # Inicializar componentes
        self.interpreter = GeminiInterpreter()
        self.searcher = SerperSearch()
        self.validator = DomainValidator(
            use_webtech=use_webtech,
            use_pagespeed=use_pagespeed
        )
    
    def find_domains(self, 
                    prompt: str, 
                    max_results: int = 20,
                    min_confidence: float = 50.0) -> List[ValidationResult]:
        """
        Encuentra dominios que cumplan con el prompt.
        
        Args:
            prompt: Descripción de qué tipo de webs buscar
            max_results: Número máximo de dominios válidos a retornar
            min_confidence: Confianza mínima para considerar un dominio válido
            
        Returns:
            Lista de ValidationResult ordenados por confianza
        """
        if self.verbose:
            console.print(Panel(f"[bold blue]Buscando:[/bold blue] {prompt}", 
                               title="Domain Finder", border_style="blue"))
        
        # 1. Interpretar el prompt con Gemini
        if self.verbose:
            console.print("\n[yellow]📝 Analizando prompt con Gemini...[/yellow]")
        
        analysis = self.interpreter.analyze_prompt(prompt)
        
        if self.verbose:
            self._show_analysis(analysis)
        
        # 2. Buscar webs con Serper
        if self.verbose:
            console.print("\n[yellow]🔍 Buscando webs con Serper...[/yellow]")
        
        search_results = self._execute_searches(analysis, max_results * 3)  # Buscar más para filtrar
        
        if self.verbose:
            console.print(f"   Encontrados [green]{len(search_results)}[/green] resultados únicos")
        
        if not search_results:
            console.print("[red]No se encontraron resultados[/red]")
            return []
        
        # 3. Validar dominios
        if self.verbose:
            console.print("\n[yellow]✅ Validando dominios...[/yellow]")
        
        validated_results = self._validate_domains(search_results, analysis)
        
        # 4. Filtrar y ordenar
        valid_results = [r for r in validated_results 
                        if r.is_valid and r.confidence_score >= min_confidence]
        valid_results.sort(key=lambda x: x.confidence_score, reverse=True)
        
        # Limitar resultados
        valid_results = valid_results[:max_results]
        
        if self.verbose:
            self._show_results(valid_results, validated_results)
        
        return valid_results
    
    def _execute_searches(self, analysis: PromptAnalysis, max_results: int) -> List[SearchResult]:
        """Ejecuta las búsquedas en Serper."""
        results = []
        
        # Búsqueda principal con las queries generadas
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            console=console,
            transient=True
        ) as progress:
            task = progress.add_task("Buscando...", total=len(analysis.search_queries))
            
            main_results = self.searcher.search(analysis, max_results=max_results)
            results.extend(main_results)
            progress.update(task, advance=len(analysis.search_queries))
        
        # Si no hay suficientes resultados, usar búsqueda con operadores
        if len(results) < max_results // 2:
            operator_results = self.searcher.search_with_operators(analysis, max_results=max_results // 2)
            
            # Añadir solo dominios nuevos
            existing_domains = {r.domain for r in results}
            for r in operator_results:
                if r.domain not in existing_domains:
                    results.append(r)
                    existing_domains.add(r.domain)
        
        return results[:max_results]
    
    def _validate_domains(self, search_results: List[SearchResult], 
                         analysis: PromptAnalysis) -> List[ValidationResult]:
        """Valida los dominios encontrados."""
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            console=console,
            transient=True
        ) as progress:
            task = progress.add_task("Validando dominios...", total=len(search_results))
            
            results = []
            for sr in search_results:
                try:
                    result = self.validator.validate(sr, analysis)
                    results.append(result)
                except Exception as e:
                    results.append(ValidationResult(
                        domain=sr.domain,
                        url=sr.url,
                        error_message=str(e)
                    ))
                progress.update(task, advance=1)
        
        return results
    
    def _show_analysis(self, analysis: PromptAnalysis):
        """Muestra el análisis del prompt."""
        table = Table(title="Análisis del Prompt", show_header=False, border_style="cyan")
        table.add_column("Campo", style="cyan")
        table.add_column("Valor", style="white")
        
        table.add_row("Tipo de negocio", analysis.business_type)
        if analysis.product_category:
            table.add_row("Categoría producto", analysis.product_category)
        if analysis.service_type:
            table.add_row("Tipo servicio", analysis.service_type)
        if analysis.niche:
            table.add_row("Nicho", analysis.niche)
        table.add_row("Queries generadas", str(len(analysis.search_queries)))
        
        console.print(table)
        
        if analysis.search_queries:
            console.print("\n[dim]Queries de búsqueda:[/dim]")
            for i, q in enumerate(analysis.search_queries[:5], 1):
                console.print(f"   {i}. {q}")
    
    def _show_results(self, valid_results: List[ValidationResult], 
                     all_results: List[ValidationResult]):
        """Muestra los resultados finales."""
        stats = calculate_stats(all_results)
        
        console.print(f"\n[green]✅ Dominios válidos: {len(valid_results)}[/green]")
        console.print(f"[red]❌ Descartados: {stats['invalid_count']}[/red]")
        console.print(f"[dim]Tasa de validación: {stats['validation_rate']:.1f}%[/dim]")
        
        if valid_results:
            table = Table(title="\nDominios Encontrados", border_style="green")
            table.add_column("#", style="dim", width=3)
            table.add_column("Dominio", style="green")
            table.add_column("Confianza", style="cyan", justify="right")
            table.add_column("Tipo", style="yellow")
            table.add_column("Razón", style="dim")
            
            for i, r in enumerate(valid_results, 1):
                # Determinar tipo
                tipo = "Web"
                if r.tech_profile:
                    if r.tech_profile.get("is_ecommerce"):
                        tipo = "Ecommerce"
                    elif r.tech_profile.get("is_saas"):
                        tipo = "SaaS"
                    elif r.tech_profile.get("is_cms_based"):
                        tipo = "CMS"
                
                razon = r.validation_reasons[0] if r.validation_reasons else ""
                
                table.add_row(
                    str(i),
                    r.domain,
                    f"{r.confidence_score:.0f}%",
                    tipo,
                    razon[:40]
                )
            
            console.print(table)


def main():
    """Punto de entrada principal."""
    parser = argparse.ArgumentParser(
        description="Encuentra dominios que cumplan con las especificaciones del prompt",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python -m src.main "ecommerce de electrónica"
  python -m src.main "agencia de marketing digital" --max-results 30
  python -m src.main "saas de gestión de proyectos" --export json
  python -m src.main "tienda de ropa old money" --min-confidence 60
        """
    )
    
    parser.add_argument(
        "prompt",
        help="Descripción del tipo de webs a buscar"
    )
    
    parser.add_argument(
        "--max-results", "-n",
        type=int,
        default=20,
        help="Número máximo de dominios a retornar (default: 20)"
    )
    
    parser.add_argument(
        "--min-confidence", "-c",
        type=float,
        default=50.0,
        help="Confianza mínima para considerar válido (0-100, default: 50)"
    )
    
    parser.add_argument(
        "--export", "-e",
        choices=["json", "csv", "both"],
        help="Exportar resultados a archivo"
    )
    
    parser.add_argument(
        "--use-pagespeed",
        action="store_true",
        help="Usar PageSpeed API para análisis de rendimiento (más lento)"
    )
    
    parser.add_argument(
        "--no-webtech",
        action="store_true",
        help="No usar WebTech para análisis de tecnologías"
    )
    
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Modo silencioso, solo mostrar dominios"
    )
    
    args = parser.parse_args()
    
    # Crear buscador
    finder = DomainFinder(
        use_webtech=not args.no_webtech,
        use_pagespeed=args.use_pagespeed,
        verbose=not args.quiet
    )
    
    # Buscar dominios
    results = finder.find_domains(
        prompt=args.prompt,
        max_results=args.max_results,
        min_confidence=args.min_confidence
    )
    
    # Exportar si se solicita
    if args.export:
        if args.export in ["json", "both"]:
            filepath = export_to_json(results)
            console.print(f"\n[dim]Exportado a: {filepath}[/dim]")
        if args.export in ["csv", "both"]:
            filepath = export_to_csv(results)
            console.print(f"[dim]Exportado a: {filepath}[/dim]")
    
    # En modo silencioso, solo listar dominios
    if args.quiet and results:
        for r in results:
            print(r.domain)
    
    return results


if __name__ == "__main__":
    main()
