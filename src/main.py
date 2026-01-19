"""
Domain Finder - Sistema principal de búsqueda de dominios.

Este sistema encuentra webs que SEAN lo que describe el prompt,
no webs que hablen de eso.
"""
from typing import List, Optional
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from .models.domain import Domain, PromptIntent
from .prompt_analyzer import PromptAnalyzer
from .search import SerperClient, QueryGenerator
from .validators import DomainValidator


console = Console()


class DomainFinder:
    """
    Sistema principal de búsqueda de dominios.
    
    Flujo:
    1. Analiza el prompt para entender qué busca el usuario
    2. Genera queries inteligentes para encontrar webs reales
    3. Busca en Google usando Serper
    4. Valida los dominios usando WebTech y PageSpeed
    5. Filtra y devuelve solo los que cumplen el prompt
    """
    
    def __init__(self):
        """Inicializa el buscador."""
        self.prompt_analyzer = PromptAnalyzer()
        self.query_generator = QueryGenerator()
        self.serper_client = SerperClient()
        self.domain_validator = DomainValidator()
    
    def find(
        self,
        prompt: str,
        max_results: int = 10,
        validate_tech: bool = True,
        analyze_pagespeed: bool = False,
        min_match_score: int = 40
    ) -> List[Domain]:
        """
        Encuentra dominios que cumplan con el prompt.
        
        Args:
            prompt: Descripción de las webs a buscar
            max_results: Número máximo de resultados a devolver
            validate_tech: Si validar con WebTech
            analyze_pagespeed: Si analizar con PageSpeed
            min_match_score: Puntuación mínima para incluir un resultado
            
        Returns:
            Lista de Domain que cumplen el prompt
        """
        # 1. Analizar el prompt
        console.print(Panel(f"[bold blue]Analizando prompt:[/] {prompt}"))
        intent = self.prompt_analyzer.analyze(prompt)
        
        self._print_intent(intent)
        
        # 2. Generar queries de búsqueda
        queries = self.query_generator.generate_queries(intent)
        if not queries:
            queries = intent.search_queries
        
        console.print(f"\n[bold]Queries generadas:[/]")
        for q in queries:
            console.print(f"  • {q}")
        
        # 3. Buscar en Google
        console.print(f"\n[bold]Buscando en Google...[/]")
        domains = self.serper_client.search_multiple(queries, num_results_per_query=10)
        
        console.print(f"[green]Encontrados {len(domains)} dominios únicos[/]")
        
        if not domains:
            return []
        
        # 4. Validar dominios
        if validate_tech:
            console.print(f"\n[bold]Validando dominios...[/]")
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("Analizando...", total=len(domains))
                
                validated_domains = []
                for domain in domains:
                    progress.update(task, description=f"Analizando {domain.domain}...")
                    validated = self.domain_validator.validate(
                        domain, intent, analyze_pagespeed
                    )
                    validated_domains.append(validated)
                    progress.advance(task)
                
                domains = validated_domains
        
        # 5. Filtrar por puntuación
        matching = [d for d in domains if d.analysis and d.analysis.match_score >= min_match_score]
        
        # Ordenar por puntuación
        matching.sort(
            key=lambda d: d.analysis.match_score if d.analysis else 0,
            reverse=True
        )
        
        # Limitar resultados
        matching = matching[:max_results]
        
        return matching
    
    def _print_intent(self, intent: PromptIntent):
        """Imprime el análisis del prompt."""
        console.print(f"\n[bold]Análisis del prompt:[/]")
        console.print(f"  • Tipo de negocio: [cyan]{intent.business_type.value}[/]")
        
        if intent.niche:
            console.print(f"  • Nicho: [cyan]{intent.niche}[/]")
        
        if intent.product_service:
            console.print(f"  • Producto/servicio: [cyan]{intent.product_service}[/]")
        
        if intent.characteristics:
            console.print(f"  • Características: [cyan]{', '.join(intent.characteristics)}[/]")
        
        if intent.metrics_to_analyze:
            console.print(f"  • Métricas a analizar: [cyan]{', '.join(intent.metrics_to_analyze)}[/]")
        
        console.print(f"  • Confianza: [cyan]{intent.confidence}%[/]")
    
    def print_results(self, domains: List[Domain]):
        """
        Imprime los resultados de forma formateada.
        
        Args:
            domains: Lista de dominios a imprimir
        """
        if not domains:
            console.print("[yellow]No se encontraron dominios que cumplan el prompt.[/]")
            return
        
        table = Table(title="Dominios Encontrados")
        
        table.add_column("Dominio", style="cyan", no_wrap=True)
        table.add_column("Tipo Detectado", style="magenta")
        table.add_column("Score", justify="center", style="green")
        table.add_column("Razones", style="white")
        
        for domain in domains:
            if domain.analysis:
                reasons = domain.analysis.match_reasons[:2]
                reasons_str = "\n".join(reasons) if reasons else "-"
                
                table.add_row(
                    domain.domain,
                    domain.analysis.detected_business_type.value,
                    str(domain.analysis.match_score),
                    reasons_str
                )
            else:
                table.add_row(domain.domain, "-", "-", "-")
        
        console.print(table)
    
    def get_detailed_report(self, domains: List[Domain]) -> dict:
        """
        Genera un reporte detallado de los resultados.
        
        Args:
            domains: Lista de dominios
            
        Returns:
            Diccionario con el reporte
        """
        report = {
            "total_found": len(domains),
            "domains": []
        }
        
        for domain in domains:
            domain_report = {
                "url": domain.url,
                "domain": domain.domain,
                "title": domain.title,
                "description": domain.description,
            }
            
            if domain.analysis:
                domain_report["analysis"] = {
                    "detected_type": domain.analysis.detected_business_type.value,
                    "match_score": domain.analysis.match_score,
                    "match_reasons": domain.analysis.match_reasons,
                    "detection_reasons": domain.analysis.detection_reasons,
                }
                
                if domain.analysis.tech_stack:
                    tech = domain.analysis.tech_stack
                    domain_report["tech_stack"] = {
                        "cms": tech.cms,
                        "ecommerce_platform": tech.ecommerce_platform,
                        "payment_processors": tech.payment_processors,
                        "analytics": tech.analytics,
                    }
                
                if domain.analysis.pagespeed:
                    ps = domain.analysis.pagespeed
                    domain_report["pagespeed"] = {
                        "performance": ps.performance_score,
                        "seo": ps.seo_score,
                        "mobile_friendly": ps.is_mobile_friendly,
                    }
            
            report["domains"].append(domain_report)
        
        return report


def find_domains(
    prompt: str,
    max_results: int = 10,
    validate_tech: bool = True,
    analyze_pagespeed: bool = False
) -> List[Domain]:
    """
    Función principal para encontrar dominios.
    
    Args:
        prompt: Descripción de las webs a buscar
        max_results: Número máximo de resultados
        validate_tech: Si validar tecnologías
        analyze_pagespeed: Si analizar métricas de PageSpeed
        
    Returns:
        Lista de dominios que cumplen el prompt
    """
    finder = DomainFinder()
    return finder.find(
        prompt,
        max_results=max_results,
        validate_tech=validate_tech,
        analyze_pagespeed=analyze_pagespeed
    )
