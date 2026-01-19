#!/usr/bin/env python3
"""
Domain Finder - Main Entry Point
Find domains that match your prompt specifications

Usage:
    python main.py "ecommerce de electronica"
    python main.py "agencia de marketing digital en España" --max-results 10
    
For API server:
    python main.py --serve
    
For more options:
    python main.py --help
"""
import asyncio
import argparse
import json
import os
import sys

# Ensure src is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loguru import logger


def setup_logging(verbose: bool = False):
    """Configure logging"""
    logger.remove()
    if verbose:
        logger.add(sys.stderr, level="DEBUG", 
                  format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}")
    else:
        logger.add(sys.stderr, level="WARNING",
                  format="<level>{level}</level> | {message}")


async def run_finder(prompt: str, api_key: str, max_results: int = 20, 
                     include_pagespeed: bool = True, output_json: bool = False):
    """Run the domain finder"""
    from src.core import DomainFinder
    
    finder = DomainFinder(serper_api_key=api_key)
    
    if not output_json:
        print(f"\n🔍 Searching for domains matching: \"{prompt}\"\n")
        print("This may take a minute...")
    
    result = await finder.find(
        prompt=prompt,
        max_results=max_results,
        include_pagespeed=include_pagespeed
    )
    
    if output_json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        # Print summary
        print(f"\n{'='*70}")
        print(f"📊 SEARCH RESULTS")
        print(f"{'='*70}")
        print(f"Prompt: {prompt}")
        print(f"Detected Business Type: {result.parsed_prompt.business_type or 'General'}")
        if result.parsed_prompt.product_category:
            print(f"Product Category: {result.parsed_prompt.product_category}")
        print(f"Domains Found: {result.total_matches}")
        print(f"Time: {result.execution_time_seconds:.1f} seconds")
        
        if result.matched_domains:
            print(f"\n{'='*70}")
            print(f"✅ MATCHING DOMAINS")
            print(f"{'='*70}")
            
            for i, d in enumerate(result.matched_domains, 1):
                print(f"\n{i}. {d.domain}")
                print(f"   URL: {d.url}")
                print(f"   Score: {d.total_score:.2f}")
                if d.detected_business_type:
                    print(f"   Type: {d.detected_business_type}")
                if d.matched_technologies:
                    print(f"   Tech: {', '.join(d.matched_technologies[:3])}")
            
            # Print simple list for copy-paste
            print(f"\n{'='*70}")
            print("📋 DOMAIN LIST (copy-paste ready)")
            print(f"{'='*70}")
            for d in result.matched_domains:
                print(d.domain)
        else:
            print("\n❌ No matching domains found.")
            print("Try adjusting your search prompt or lowering the minimum score.")


def run_server(host: str = "0.0.0.0", port: int = 8000):
    """Run the API server"""
    import uvicorn
    from src.api import app
    
    print(f"\n🚀 Starting Domain Finder API Server")
    print(f"   URL: http://{host}:{port}")
    print(f"   Docs: http://{host}:{port}/docs")
    print(f"\nPress Ctrl+C to stop\n")
    
    uvicorn.run(app, host=host, port=port)


def main():
    parser = argparse.ArgumentParser(
        description="Domain Finder - Find domains that match your specifications",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py "ecommerce de electronica"
  python main.py "tienda de ropa online" --max-results 10
  python main.py "agencia de marketing digital" --json
  python main.py --serve  # Start API server

Environment Variables:
  SERPER_API_KEY    Your Serper API key for web searches
        """
    )
    
    parser.add_argument("prompt", nargs="?", help="Search prompt describing desired websites")
    parser.add_argument("--api-key", help="Serper API key (or set SERPER_API_KEY)")
    parser.add_argument("--max-results", type=int, default=20, help="Max results (default: 20)")
    parser.add_argument("--no-pagespeed", action="store_true", help="Skip PageSpeed analysis")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--serve", action="store_true", help="Start API server")
    parser.add_argument("--host", default="0.0.0.0", help="Server host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Server port (default: 8000)")
    
    args = parser.parse_args()
    
    setup_logging(args.verbose)
    
    # Server mode
    if args.serve:
        run_server(args.host, args.port)
        return
    
    # Search mode
    if not args.prompt:
        parser.print_help()
        print("\n❌ Error: Please provide a search prompt or use --serve for API mode")
        sys.exit(1)
    
    # Get API key
    api_key = args.api_key or os.getenv("SERPER_API_KEY")
    if not api_key:
        print("❌ Error: Serper API key required")
        print("   Set SERPER_API_KEY environment variable or use --api-key")
        sys.exit(1)
    
    # Run search
    asyncio.run(run_finder(
        prompt=args.prompt,
        api_key=api_key,
        max_results=args.max_results,
        include_pagespeed=not args.no_pagespeed,
        output_json=args.json
    ))


if __name__ == "__main__":
    main()
