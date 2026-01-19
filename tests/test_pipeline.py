import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import Settings
from core.pipeline import DomainPipeline
from providers.pagespeed_client import PageSpeedMetrics
from providers.serper_client import SerperSearchResult
from utils.http import FetchResult


class StubSerperClient:
    def search(self, query, num_results, gl, hl, timeout):
        return [
            SerperSearchResult(
                title="Demo Shop",
                link="https://example.com",
                snippet="Electronic shop",
            )
        ]


class StubPageSpeedClient:
    def analyze(self, url, strategy, timeout):
        return PageSpeedMetrics(performance=30.0, seo=90.0, accessibility=90.0)


class StubWebTechClient:
    def detect(self, url, timeout):
        return ["Shopify"]


def stub_fetcher(url, timeout, max_bytes, user_agent):
    html = """
    <html>
      <head><title>Electronica Store</title></head>
      <body>
        <h1>Electronica</h1>
        <button>Add to cart</button>
        <a href="/checkout">Checkout</a>
      </body>
    </html>
    """
    return FetchResult(
        url=url,
        status_code=200,
        ok=True,
        text=html,
        content_type="text/html",
    )


class TestPipeline(unittest.TestCase):
    def test_pipeline_matches_prompt(self) -> None:
        settings = Settings(
            serper_api_key="test",
            pagespeed_api_key="test",
            serper_endpoint="https://example",
            pagespeed_endpoint="https://example",
            serper_gl="es",
            serper_hl="es",
            serper_num=10,
            request_timeout=1,
            max_content_bytes=20000,
            max_results=5,
            max_pagespeed_calls=1,
            pagespeed_strategy="mobile",
            min_score=50.0,
            user_agent="test-agent",
        )
        pipeline = DomainPipeline(
            settings=settings,
            serper_client=StubSerperClient(),
            pagespeed_client=StubPageSpeedClient(),
            webtech_client=StubWebTechClient(),
            fetcher=stub_fetcher,
        )

        results = pipeline.run("ecommerce de electronica con carga lenta", max_results=1)

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].matched)


if __name__ == "__main__":
    unittest.main()
