"""
Funciones de utilidad para el sistema de búsqueda de dominios.
"""
import json
import csv
from typing import List, Dict, Any
from datetime import datetime
from pathlib import Path

from src.domain_validator.validator import ValidationResult


def format_results(results: List[ValidationResult], verbose: bool = False) -> str:
    """
    Formatea los resultados para mostrar en consola.
    
    Args:
        results: Lista de resultados de validación
        verbose: Si mostrar información detallada
        
    Returns:
        String formateado para imprimir
    """
    output = []
    output.append("\n" + "=" * 60)
    output.append("RESULTADOS DE BÚSQUEDA DE DOMINIOS")
    output.append("=" * 60)
    
    valid_results = [r for r in results if r.is_valid]
    invalid_results = [r for r in results if not r.is_valid]
    
    output.append(f"\n✅ Dominios válidos encontrados: {len(valid_results)}")
    output.append(f"❌ Dominios descartados: {len(invalid_results)}")
    output.append("")
    
    if valid_results:
        output.append("-" * 60)
        output.append("DOMINIOS VÁLIDOS:")
        output.append("-" * 60)
        
        for i, result in enumerate(valid_results, 1):
            output.append(f"\n{i}. {result.domain}")
            output.append(f"   URL: {result.url}")
            output.append(f"   Confianza: {result.confidence_score:.1f}%")
            
            if verbose:
                if result.page_title:
                    output.append(f"   Título: {result.page_title[:60]}...")
                if result.validation_reasons:
                    output.append(f"   Razones: {', '.join(result.validation_reasons[:3])}")
                if result.detected_keywords:
                    output.append(f"   Keywords: {', '.join(result.detected_keywords[:5])}")
                if result.tech_profile:
                    techs = []
                    if result.tech_profile.get("ecommerce_platform"):
                        techs.extend(result.tech_profile["ecommerce_platform"])
                    if result.tech_profile.get("cms"):
                        techs.extend(result.tech_profile["cms"])
                    if techs:
                        output.append(f"   Tecnologías: {', '.join(techs)}")
    
    return "\n".join(output)


def export_to_json(results: List[ValidationResult], filepath: str = None) -> str:
    """
    Exporta los resultados a un archivo JSON.
    
    Args:
        results: Lista de resultados
        filepath: Ruta del archivo (si no se especifica, genera uno automático)
        
    Returns:
        Ruta del archivo creado
    """
    if filepath is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = f"domain_results_{timestamp}.json"
    
    data = {
        "generated_at": datetime.now().isoformat(),
        "total_results": len(results),
        "valid_count": len([r for r in results if r.is_valid]),
        "results": [r.to_dict() for r in results]
    }
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    return filepath


def export_to_csv(results: List[ValidationResult], filepath: str = None) -> str:
    """
    Exporta los resultados a un archivo CSV.
    
    Args:
        results: Lista de resultados
        filepath: Ruta del archivo
        
    Returns:
        Ruta del archivo creado
    """
    if filepath is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = f"domain_results_{timestamp}.csv"
    
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        
        # Headers
        writer.writerow([
            "Domain", "URL", "Is Valid", "Confidence Score",
            "Page Title", "Keywords", "Validation Reasons", "Rejection Reasons"
        ])
        
        # Data
        for result in results:
            writer.writerow([
                result.domain,
                result.url,
                result.is_valid,
                f"{result.confidence_score:.1f}",
                result.page_title,
                ", ".join(result.detected_keywords[:5]),
                ", ".join(result.validation_reasons[:3]),
                ", ".join(result.rejection_reasons[:3])
            ])
    
    return filepath


def extract_domains_only(results: List[ValidationResult], only_valid: bool = True) -> List[str]:
    """
    Extrae solo los dominios de los resultados.
    
    Args:
        results: Lista de resultados
        only_valid: Si solo incluir dominios válidos
        
    Returns:
        Lista de dominios
    """
    if only_valid:
        return [r.domain for r in results if r.is_valid]
    return [r.domain for r in results]


def summarize_technologies(results: List[ValidationResult]) -> Dict[str, int]:
    """
    Genera un resumen de las tecnologías encontradas.
    """
    tech_count = {}
    
    for result in results:
        if result.tech_profile:
            for category in ["cms", "ecommerce_platform", "frameworks", "analytics"]:
                techs = result.tech_profile.get(category, [])
                for tech in techs:
                    tech_count[tech] = tech_count.get(tech, 0) + 1
    
    # Ordenar por frecuencia
    return dict(sorted(tech_count.items(), key=lambda x: x[1], reverse=True))


def calculate_stats(results: List[ValidationResult]) -> Dict[str, Any]:
    """
    Calcula estadísticas de los resultados.
    """
    valid = [r for r in results if r.is_valid]
    invalid = [r for r in results if not r.is_valid]
    
    avg_confidence = sum(r.confidence_score for r in valid) / len(valid) if valid else 0
    
    ecommerce_count = sum(1 for r in valid if r.tech_profile and r.tech_profile.get("is_ecommerce"))
    saas_count = sum(1 for r in valid if r.tech_profile and r.tech_profile.get("is_saas"))
    cms_count = sum(1 for r in valid if r.tech_profile and r.tech_profile.get("is_cms_based"))
    
    return {
        "total_analyzed": len(results),
        "valid_count": len(valid),
        "invalid_count": len(invalid),
        "validation_rate": (len(valid) / len(results) * 100) if results else 0,
        "average_confidence": avg_confidence,
        "ecommerce_count": ecommerce_count,
        "saas_count": saas_count,
        "cms_count": cms_count
    }
