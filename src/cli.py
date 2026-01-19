#!/usr/bin/env python3
"""
Domain Finder CLI
Command-line interface for finding domains that match prompt specifications
"""
import asyncio
import argparse
import json
import sys
import os
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger
from tqdm import tqdm


def setup_logging(verbose: bool = False):
    """Configure logging"""
    logger.remove()
    level = "DEBUG" if verbose else "INFO"
    logger.add(sys.stderr, level=level, format="<level>{level}</level> | {message}")


async def run_search(args):
    """Run domain search"""
    from src.core import DomainFinder
    
    # Get API key
    api_key = args.api_key or os.getenv("SERPER_API_KEY")
    if not api_key:
        print("Error: Serper API key required. Use --api-key or set SERPER_API_KEY env var")
        sys.exit(1)
    
    finder = DomainFinder(serper_api_key=api_key)
    
    print(f"\n🔍 Searching for: {args.prompt}\n")
    
    result = await finder.find(
        prompt=args.prompt,
        max_results=args.max_results,
        include_pagespeed=not args.no_pagespeed,
        min_score=args.min_score
    )
    
    # Output results
    if args.output_format == "json":
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(f"{'='*60}")
        print(f"📊 RESULTS SUMMARY")
        print(f"{'='*60}")
        print(f"Prompt: {result.prompt}")
        print(f"Business Type Detected: {result.parsed_prompt.business_type or 'N/A'}")
        print(f"Product Category: {result.parsed_prompt.product_category or 'N/A'}")
        print(f"Total Searched: {result.total_searched}")
        print(f"Total Analyzed: {result.total_analyzed}")
        print(f"Total Matches: {result.total_matches}")
        print(f"Execution Time: {result.execution_time_seconds:.2f}s")
        
        if result.errors:
            print(f"\n⚠️ Errors: {', '.join(result.errors)}")
        
        print(f"\n{'='*60}")
        print(f"✅ MATCHED DOMAINS ({len(result.matched_domains)})")
        print(f"{'='*60}")
        
        for i, domain in enumerate(result.matched_domains, 1):
            print(f"\n{i}. {domain.domain}")
            print(f"   URL: {domain.url}")
            print(f"   Score: {domain.total_score:.3f}")
            print(f"   Type: {domain.detected_business_type or 'Unknown'}")
            if domain.matched_technologies:
                print(f"   Technologies: {', '.join(domain.matched_technologies[:5])}")
            if domain.match_reasons:
                print(f"   Reasons: {', '.join(domain.match_reasons[:3])}")
        
        if args.show_rejected and result.rejected_domains:
            print(f"\n{'='*60}")
            print(f"❌ REJECTED DOMAINS (Top 5)")
            print(f"{'='*60}")
            
            for domain in result.rejected_domains[:5]:
                print(f"\n• {domain.domain}")
                print(f"  Score: {domain.total_score:.3f}")
                if domain.rejection_reasons:
                    print(f"  Reasons: {', '.join(domain.rejection_reasons[:2])}")
        
        # Simple domain list at the end
        if result.matched_domains:
            print(f"\n{'='*60}")
            print(f"📋 DOMAIN LIST (copy-paste ready)")
            print(f"{'='*60}")
            for domain in result.matched_domains:
                print(domain.domain)


async def run_analyze(args):
    """Run single domain analysis"""
    from src.core import DomainFinder
    
    finder = DomainFinder()
    
    print(f"\n🔬 Analyzing: {args.domain}\n")
    
    analysis = await finder.analyze_domain(args.domain)
    
    if args.output_format == "json":
        print(json.dumps(analysis.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(f"{'='*60}")
        print(f"📊 ANALYSIS: {analysis.domain}")
        print(f"{'='*60}")
        print(f"URL: {analysis.url}")
        print(f"Detected Business Type: {analysis.detected_business_type or 'Unknown'}")
        print(f"Confidence: {analysis.business_type_confidence:.2f}")
        print(f"CMS: {analysis.detected_cms or 'N/A'}")
        print(f"Ecommerce Platform: {analysis.detected_ecommerce_platform or 'N/A'}")
        print(f"Has Payment Processor: {'Yes' if analysis.has_payment_processor else 'No'}")
        print(f"Has Analytics: {'Yes' if analysis.has_analytics else 'No'}")
        print(f"Has Marketing Tools: {'Yes' if analysis.has_marketing_tools else 'No'}")
        
        if analysis.technologies:
            print(f"\nTechnologies Detected ({len(analysis.technologies)}):")
            for tech in analysis.technologies[:15]:
                print(f"  • {tech.name} ({tech.category})")
        
        if analysis.pagespeed_metrics:
            m = analysis.pagespeed_metrics
            print(f"\nPageSpeed Metrics:")
            print(f"  Performance: {m.performance_score:.0f}/100")
            print(f"  SEO: {m.seo_score:.0f}/100")
            print(f"  Accessibility: {m.accessibility_score:.0f}/100")
            print(f"  Best Practices: {m.best_practices_score:.0f}/100")
            print(f"  Mobile Friendly: {'Yes' if m.is_mobile_friendly else 'No'}")
            print(f"  HTTPS: {'Yes' if m.has_https else 'No'}")
        
        if analysis.analysis_errors:
            print(f"\n⚠️ Errors: {', '.join(analysis.analysis_errors)}")


async def run_verify(args):
    """Run domain verification"""
    from src.core import DomainFinder
    
    finder = DomainFinder()
    
    print(f"\n🔍 Verifying: {args.domain}")
    print(f"Against prompt: {args.prompt}\n")
    
    result = await finder.verify_domain(args.domain, args.prompt)
    
    if args.output_format == "json":
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(f"{'='*60}")
        print(f"{'✅ MATCH' if result.is_match else '❌ NO MATCH'}")
        print(f"{'='*60}")
        print(f"Domain: {result.domain}")
        print(f"Score: {result.total_score:.3f}")
        print(f"Threshold: 0.60")
        print(f"\nScore Breakdown:")
        print(f"  Technology: {result.technology_score:.3f}")
        print(f"  Content: {result.content_score:.3f}")
        print(f"  Metrics: {result.metrics_score:.3f}")
        print(f"  Quality: {result.quality_score:.3f}")
        
        print(f"\nDetected Type: {result.detected_business_type or 'Unknown'}")
        print(f"Type Matches: {'Yes' if result.business_type_matches else 'No'}")
        
        if result.match_reasons:
            print(f"\n✅ Match Reasons:")
            for reason in result.match_reasons:
                print(f"  • {reason}")
        
        if result.rejection_reasons:
            print(f"\n❌ Rejection Reasons:")
            for reason in result.rejection_reasons:
                print(f"  • {reason}")


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Domain Finder - Find domains that match your specifications",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s search "ecommerce de electronica"
  %(prog)s search "agencia de marketing digital" --max-results 10
  %(prog)s analyze example.com
  %(prog)s verify example.com "ecommerce de moda"
        """
    )
    
    parser.add_argument("-v", "--verbose", action="store_true", 
                       help="Enable verbose logging")
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Search command
    search_parser = subparsers.add_parser("search", help="Search for domains matching a prompt")
    search_parser.add_argument("prompt", help="Natural language description of desired websites")
    search_parser.add_argument("--api-key", help="Serper API key (or set SERPER_API_KEY env var)")
    search_parser.add_argument("--max-results", type=int, default=20, 
                              help="Maximum results to return (default: 20)")
    search_parser.add_argument("--min-score", type=float, 
                              help="Minimum match score (0.0-1.0)")
    search_parser.add_argument("--no-pagespeed", action="store_true",
                              help="Skip PageSpeed analysis (faster)")
    search_parser.add_argument("--show-rejected", action="store_true",
                              help="Show rejected domains")
    search_parser.add_argument("--output-format", choices=["text", "json"], 
                              default="text", help="Output format")
    
    # Analyze command
    analyze_parser = subparsers.add_parser("analyze", help="Analyze a single domain")
    analyze_parser.add_argument("domain", help="Domain to analyze")
    analyze_parser.add_argument("--output-format", choices=["text", "json"], 
                               default="text", help="Output format")
    
    # Verify command
    verify_parser = subparsers.add_parser("verify", help="Verify if domain matches prompt")
    verify_parser.add_argument("domain", help="Domain to verify")
    verify_parser.add_argument("prompt", help="Prompt to verify against")
    verify_parser.add_argument("--output-format", choices=["text", "json"], 
                              default="text", help="Output format")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    setup_logging(args.verbose)
    
    # Run the appropriate command
    if args.command == "search":
        asyncio.run(run_search(args))
    elif args.command == "analyze":
        asyncio.run(run_analyze(args))
    elif args.command == "verify":
        asyncio.run(run_verify(args))


if __name__ == "__main__":
    main()
