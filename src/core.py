"""
Domain Finder Core - Main orchestration module
Coordinates prompt parsing, searching, analysis, and verification
"""
import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from loguru import logger

from .config.settings import settings
from .modules.prompt_parser import PromptParser, ParsedPrompt
from .modules.search_engine import SearchEngine, SearchResult
from .modules.web_analyzer import WebAnalyzer, WebAnalysis
from .modules.domain_verifier import DomainVerifier, VerificationResult


@dataclass
class FinderResult:
    """Complete result of a domain finding operation"""
    prompt: str
    parsed_prompt: ParsedPrompt
    total_searched: int
    total_analyzed: int
    total_matches: int
    matched_domains: List[VerificationResult]
    rejected_domains: List[VerificationResult]
    execution_time_seconds: float
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt": self.prompt,
            "parsed_prompt": self.parsed_prompt.to_dict(),
            "summary": {
                "total_searched": self.total_searched,
                "total_analyzed": self.total_analyzed,
                "total_matches": self.total_matches,
                "execution_time_seconds": round(self.execution_time_seconds, 2)
            },
            "matched_domains": [d.to_dict() for d in self.matched_domains],
            "rejected_domains": [d.to_dict() for d in self.rejected_domains[:10]],  # Limit rejected
            "timestamp": self.timestamp,
            "errors": self.errors
        }
    
    def get_domains_list(self) -> List[str]:
        """Get simple list of matched domain names"""
        return [d.domain for d in self.matched_domains]
    
    def get_urls_list(self) -> List[str]:
        """Get simple list of matched URLs"""
        return [d.url for d in self.matched_domains]


class DomainFinder:
    """
    Main class that orchestrates the entire domain finding process
    
    Usage:
        finder = DomainFinder(serper_api_key="your_key")
        result = await finder.find("ecommerce de electronica en España")
        print(result.get_domains_list())
    """
    
    def __init__(self, serper_api_key: Optional[str] = None):
        """
        Initialize the Domain Finder
        
        Args:
            serper_api_key: Serper API key for web searches
        """
        self.parser = PromptParser()
        self.search_engine = SearchEngine(api_key=serper_api_key)
        self.analyzer = WebAnalyzer()
        self.verifier = DomainVerifier(analyzer=self.analyzer)
        
        logger.info("DomainFinder initialized")
    
    async def find(self, prompt: str, 
                   max_results: int = 20,
                   include_pagespeed: bool = True,
                   min_score: Optional[float] = None) -> FinderResult:
        """
        Find domains that match the given prompt
        
        Args:
            prompt: Natural language description of desired websites
            max_results: Maximum number of matching domains to return
            include_pagespeed: Whether to include PageSpeed analysis
            min_score: Minimum score threshold (defaults to settings)
            
        Returns:
            FinderResult with matched and rejected domains
        """
        start_time = asyncio.get_event_loop().time()
        errors = []
        
        logger.info(f"Starting domain search for: {prompt}")
        
        # Step 1: Parse the prompt
        try:
            parsed_prompt = self.parser.parse(prompt)
            logger.info(f"Parsed prompt: type={parsed_prompt.business_type}, "
                       f"product={parsed_prompt.product_category}")
        except Exception as e:
            logger.error(f"Prompt parsing error: {e}")
            errors.append(f"Parsing error: {str(e)}")
            parsed_prompt = ParsedPrompt(original_prompt=prompt)
        
        # Step 2: Search for potential domains
        try:
            search_results = await self.search_engine.search(parsed_prompt)
            logger.info(f"Found {len(search_results)} potential domains")
        except Exception as e:
            logger.error(f"Search error: {e}")
            errors.append(f"Search error: {str(e)}")
            search_results = []
        
        # Step 3: Verify and score domains
        verification_results = []
        if search_results:
            try:
                verification_results = await self.verifier.verify_batch(
                    search_results[:max_results * 2],  # Verify more than needed
                    parsed_prompt,
                    include_pagespeed=include_pagespeed
                )
            except Exception as e:
                logger.error(f"Verification error: {e}")
                errors.append(f"Verification error: {str(e)}")
        
        # Step 4: Filter matches
        threshold = min_score or settings.scoring.minimum_score_threshold
        matched = [r for r in verification_results if r.is_match and r.total_score >= threshold]
        rejected = [r for r in verification_results if not r.is_match or r.total_score < threshold]
        
        # Limit to requested max
        matched = matched[:max_results]
        
        # Calculate execution time
        end_time = asyncio.get_event_loop().time()
        execution_time = end_time - start_time
        
        result = FinderResult(
            prompt=prompt,
            parsed_prompt=parsed_prompt,
            total_searched=len(search_results),
            total_analyzed=len(verification_results),
            total_matches=len(matched),
            matched_domains=matched,
            rejected_domains=rejected,
            execution_time_seconds=execution_time,
            errors=errors
        )
        
        logger.info(f"Search complete: {len(matched)} matches found in {execution_time:.2f}s")
        
        return result
    
    async def quick_find(self, prompt: str, max_results: int = 10) -> List[str]:
        """
        Quick find - returns just a list of matching domain names
        Faster but less detailed analysis
        """
        result = await self.find(prompt, max_results=max_results, include_pagespeed=False)
        return result.get_domains_list()
    
    async def analyze_domain(self, domain: str) -> WebAnalysis:
        """
        Analyze a single domain in detail
        """
        url = domain if domain.startswith("http") else f"https://{domain}"
        return await self.analyzer.analyze(url, include_pagespeed=True)
    
    async def verify_domain(self, domain: str, prompt: str) -> VerificationResult:
        """
        Verify if a specific domain matches a prompt
        """
        # Parse prompt
        parsed_prompt = self.parser.parse(prompt)
        
        # Create a search result for the domain
        url = domain if domain.startswith("http") else f"https://{domain}"
        search_result = SearchResult(
            url=url,
            domain=domain.replace("https://", "").replace("http://", "").replace("www.", ""),
            title="",
            snippet="",
            position=1,
            query_used=prompt
        )
        
        # Verify
        return await self.verifier.verify(search_result, parsed_prompt)


# Convenience function for simple usage
async def find_domains(prompt: str, 
                       serper_api_key: str,
                       max_results: int = 20) -> FinderResult:
    """
    Convenience function to find domains matching a prompt
    
    Args:
        prompt: Description of desired websites
        serper_api_key: Serper API key
        max_results: Maximum results to return
        
    Returns:
        FinderResult with matching domains
    """
    finder = DomainFinder(serper_api_key=serper_api_key)
    return await finder.find(prompt, max_results=max_results)


# Factory function
def create_domain_finder(serper_api_key: Optional[str] = None) -> DomainFinder:
    """Create a DomainFinder instance"""
    return DomainFinder(serper_api_key=serper_api_key)
