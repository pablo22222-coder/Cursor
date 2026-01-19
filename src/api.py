"""
FastAPI REST API for Domain Finder
Professional API for finding domains that match prompt specifications
"""
import os
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Query, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import asyncio
from loguru import logger

from .core import DomainFinder, FinderResult
from .config.settings import settings


# API Models
class SearchRequest(BaseModel):
    """Request model for domain search"""
    prompt: str = Field(..., description="Natural language description of desired websites", 
                       example="ecommerce de electronica en España")
    max_results: int = Field(default=20, ge=1, le=100, 
                            description="Maximum number of results to return")
    include_pagespeed: bool = Field(default=True, 
                                   description="Include PageSpeed metrics analysis")
    min_score: Optional[float] = Field(default=None, ge=0.0, le=1.0,
                                       description="Minimum match score threshold")


class QuickSearchRequest(BaseModel):
    """Request model for quick search"""
    prompt: str = Field(..., description="Natural language description")
    max_results: int = Field(default=10, ge=1, le=50)


class AnalyzeRequest(BaseModel):
    """Request model for single domain analysis"""
    domain: str = Field(..., description="Domain to analyze", example="example.com")


class VerifyRequest(BaseModel):
    """Request model for domain verification"""
    domain: str = Field(..., description="Domain to verify")
    prompt: str = Field(..., description="Prompt to verify against")


class DomainMatch(BaseModel):
    """Response model for a matched domain"""
    domain: str
    url: str
    score: float
    business_type: Optional[str]
    technologies: List[str]
    match_reasons: List[str]


class SearchResponse(BaseModel):
    """Response model for search results"""
    success: bool
    prompt: str
    total_matches: int
    execution_time_seconds: float
    matched_domains: List[DomainMatch]
    errors: List[str] = []


class QuickSearchResponse(BaseModel):
    """Response model for quick search"""
    success: bool
    domains: List[str]


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    version: str
    serper_configured: bool
    pagespeed_configured: bool


# Create FastAPI app
app = FastAPI(
    title="Domain Finder API",
    description="""
    Professional API for finding domains that match your specifications.
    
    ## Features
    - **Intelligent Search**: Find websites that ARE what you describe, not websites that talk ABOUT it
    - **Technology Detection**: Analyze websites to detect CMS, ecommerce platforms, frameworks
    - **Performance Metrics**: Get PageSpeed Insights data for found domains
    - **Business Type Detection**: Automatically detect if a site is ecommerce, SaaS, agency, etc.
    
    ## Examples
    - "ecommerce de electronica" → Finds actual online electronics stores
    - "agencia de marketing digital en Madrid" → Finds marketing agencies
    - "tienda de ropa old money" → Finds fashion stores with specific style
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global finder instance (lazy initialization)
_finder: Optional[DomainFinder] = None


def get_finder(api_key: Optional[str] = None) -> DomainFinder:
    """Get or create DomainFinder instance"""
    global _finder
    
    key = api_key or os.getenv("SERPER_API_KEY") or settings.api.serper_api_key
    
    if _finder is None or (api_key and api_key != _finder.search_engine.api_key):
        _finder = DomainFinder(serper_api_key=key)
    
    return _finder


# API Endpoints
@app.get("/", response_model=HealthResponse)
async def root():
    """API root - health check"""
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        serper_configured=bool(settings.api.serper_api_key or os.getenv("SERPER_API_KEY")),
        pagespeed_configured=bool(settings.api.pagespeed_api_key)
    )


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return await root()


@app.post("/search", response_model=SearchResponse)
async def search_domains(
    request: SearchRequest,
    x_serper_api_key: Optional[str] = Header(None, description="Serper API key")
):
    """
    Search for domains matching the prompt specification
    
    This is the main endpoint for finding domains. It will:
    1. Parse your prompt to understand what type of website you're looking for
    2. Search the web for potential matches
    3. Analyze each candidate with WebTech and PageSpeed
    4. Return only domains that truly match your criteria
    """
    try:
        finder = get_finder(x_serper_api_key)
        
        if not finder.search_engine.api_key:
            raise HTTPException(
                status_code=401,
                detail="Serper API key required. Set SERPER_API_KEY env var or pass X-Serper-Api-Key header"
            )
        
        result = await finder.find(
            prompt=request.prompt,
            max_results=request.max_results,
            include_pagespeed=request.include_pagespeed,
            min_score=request.min_score
        )
        
        # Convert to response model
        matched = []
        for domain in result.matched_domains:
            matched.append(DomainMatch(
                domain=domain.domain,
                url=domain.url,
                score=round(domain.total_score, 3),
                business_type=domain.detected_business_type,
                technologies=domain.matched_technologies,
                match_reasons=domain.match_reasons
            ))
        
        return SearchResponse(
            success=True,
            prompt=request.prompt,
            total_matches=result.total_matches,
            execution_time_seconds=round(result.execution_time_seconds, 2),
            matched_domains=matched,
            errors=result.errors
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/quick-search", response_model=QuickSearchResponse)
async def quick_search(
    request: QuickSearchRequest,
    x_serper_api_key: Optional[str] = Header(None)
):
    """
    Quick search - returns just domain names without detailed analysis
    Faster but less accurate than full search
    """
    try:
        finder = get_finder(x_serper_api_key)
        
        if not finder.search_engine.api_key:
            raise HTTPException(status_code=401, detail="Serper API key required")
        
        domains = await finder.quick_find(request.prompt, request.max_results)
        
        return QuickSearchResponse(success=True, domains=domains)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Quick search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/analyze")
async def analyze_domain(
    request: AnalyzeRequest,
    x_serper_api_key: Optional[str] = Header(None)
):
    """
    Analyze a single domain in detail
    Returns technology stack, performance metrics, and business type detection
    """
    try:
        finder = get_finder(x_serper_api_key)
        analysis = await finder.analyze_domain(request.domain)
        
        return {
            "success": True,
            "domain": request.domain,
            "analysis": analysis.to_dict()
        }
        
    except Exception as e:
        logger.error(f"Analysis error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/verify")
async def verify_domain(
    request: VerifyRequest,
    x_serper_api_key: Optional[str] = Header(None)
):
    """
    Verify if a specific domain matches a prompt
    Useful for checking if a known domain fits your criteria
    """
    try:
        finder = get_finder(x_serper_api_key)
        result = await finder.verify_domain(request.domain, request.prompt)
        
        return {
            "success": True,
            "domain": request.domain,
            "prompt": request.prompt,
            "is_match": result.is_match,
            "score": round(result.total_score, 3),
            "verification": result.to_dict()
        }
        
    except Exception as e:
        logger.error(f"Verification error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/business-types")
async def list_business_types():
    """
    List all supported business types and their detection criteria
    """
    from .config.settings import BUSINESS_TYPE_SIGNATURES
    
    types = {}
    for btype, config in BUSINESS_TYPE_SIGNATURES.items():
        types[btype] = {
            "keywords": config.get("keywords", [])[:5],
            "technologies": config.get("technologies", [])[:5],
            "description": f"Websites that are {btype}s"
        }
    
    return {"business_types": types}


@app.get("/product-categories")
async def list_product_categories():
    """
    List all supported product categories
    """
    from .config.settings import PRODUCT_CATEGORIES
    
    return {"product_categories": PRODUCT_CATEGORIES}


# Error handlers
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": str(exc)}
    )


# Run with: uvicorn src.api:app --reload
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
