"""
Tests para el ciclo de cada worker:
  · Modo rápido: comprobación de "está viva" (quick_check) entre Fase 1 y Fase 3.
  · Modo precisión: gate de completitud después de Fase 3.

Sin red — los tests del quick_check usan respuestas falsas inyectadas.
"""
from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, "/workspace")

from src.web_analyzer.quick_check import (  # noqa: E402
    is_alive, QuickCheckResult,
    _is_obvious_parking_or_error, _has_meaningful_body,
)
from src.web_analyzer.domain_pipeline import DomainPipelineOrchestrator  # noqa: E402


# ─────────────────────────────────────────────────────────────────────
#  quick_check helpers
# ─────────────────────────────────────────────────────────────────────

class TestQuickCheckHelpers(unittest.TestCase):
    def test_parking_detected(self):
        self.assertEqual(
            _is_obvious_parking_or_error("This domain is parked and for sale"),
            "parking_or_placeholder",
        )

    def test_godaddy_parked(self):
        self.assertEqual(
            _is_obvious_parking_or_error("<html>Buy this domain on GoDaddy</html>"),
            "parking_or_placeholder",
        )

    def test_account_suspended(self):
        self.assertEqual(
            _is_obvious_parking_or_error("<html>Account Suspended</html>"),
            "parking_or_placeholder",
        )

    def test_real_html_passes(self):
        html = "<html><head><title>Real Site</title></head><body>" + ("Hola mundo " * 200) + "</body></html>"
        self.assertIsNone(_is_obvious_parking_or_error(html))

    def test_meaningful_body_with_title(self):
        self.assertTrue(_has_meaningful_body("<html><title>Hello</title></html>"))

    def test_meaningful_body_with_h1(self):
        self.assertTrue(_has_meaningful_body("<html><body><h1>Hi</h1></body></html>"))

    def test_meaningful_body_long_text(self):
        body = "<html><body>" + ("Lorem ipsum " * 50) + "</body></html>"
        self.assertTrue(_has_meaningful_body(body))

    def test_meaningful_body_empty(self):
        self.assertFalse(_has_meaningful_body("<html></html>"))


# ─────────────────────────────────────────────────────────────────────
#  is_alive (con httpx mockeado)
# ─────────────────────────────────────────────────────────────────────

class _FakeResponse:
    def __init__(self, status_code=200, text="", headers=None, url=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {"content-type": "text/html"}
        self.url = url


class _FakeClient:
    def __init__(self, response, *, raise_on_get=None):
        self._response = response
        self._raise = raise_on_get

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, **kwargs):
        if self._raise:
            raise self._raise
        return self._response


class TestIsAlive(unittest.TestCase):
    def test_alive_real_site(self):
        html = "<html><head><title>Acme</title></head><body>" + ("text " * 200) + "</body></html>"
        fake = _FakeClient(_FakeResponse(200, html, url="https://acme.com/"))
        with patch("src.web_analyzer.quick_check.httpx") as mocked_httpx:
            mocked_httpx.Client = lambda **kw: fake
            mocked_httpx.TimeoutException = type("T", (Exception,), {})
            mocked_httpx.RequestError = type("R", (Exception,), {})
            mocked_httpx.RemoteProtocolError = type("RP", (Exception,), {})
            r = is_alive("https://acme.com")
        self.assertTrue(r.alive, r.reason)
        self.assertEqual(r.status_code, 200)

    def test_404_rejected(self):
        fake = _FakeClient(_FakeResponse(404, "<html>Not Found</html>"))
        with patch("src.web_analyzer.quick_check.httpx") as mh:
            mh.Client = lambda **kw: fake
            mh.TimeoutException = type("T", (Exception,), {})
            mh.RequestError = type("R", (Exception,), {})
            mh.RemoteProtocolError = type("RP", (Exception,), {})
            r = is_alive("https://broken.com")
        self.assertFalse(r.alive)
        self.assertIn("http_404", r.reason)

    def test_parking_rejected(self):
        # >1024 bytes para que pase MIN_BODY_BYTES y aún así detectemos parking.
        filler = "x" * 1500
        html = (
            "<html><head><title>Parked</title></head>"
            f"<body>This domain is parked and for sale. {filler}</body></html>"
        )
        fake = _FakeClient(_FakeResponse(200, html, url="https://parked.com"))
        with patch("src.web_analyzer.quick_check.httpx") as mh:
            mh.Client = lambda **kw: fake
            mh.TimeoutException = type("T", (Exception,), {})
            mh.RequestError = type("R", (Exception,), {})
            mh.RemoteProtocolError = type("RP", (Exception,), {})
            r = is_alive("https://parked.com")
        self.assertFalse(r.alive)
        self.assertEqual(r.reason, "parking_or_placeholder")

    def test_tiny_html_rejected(self):
        fake = _FakeClient(_FakeResponse(200, "<html></html>", url="https://tiny.com"))
        with patch("src.web_analyzer.quick_check.httpx") as mh:
            mh.Client = lambda **kw: fake
            mh.TimeoutException = type("T", (Exception,), {})
            mh.RequestError = type("R", (Exception,), {})
            mh.RemoteProtocolError = type("RP", (Exception,), {})
            r = is_alive("https://tiny.com")
        self.assertFalse(r.alive)
        self.assertTrue(r.reason.startswith("empty_or_tiny_html"))

    def test_non_html_rejected(self):
        fake = _FakeClient(_FakeResponse(
            200, "%PDF-1.4 binary content",
            headers={"content-type": "application/pdf"}, url="https://pdf.com"
        ))
        with patch("src.web_analyzer.quick_check.httpx") as mh:
            mh.Client = lambda **kw: fake
            mh.TimeoutException = type("T", (Exception,), {})
            mh.RequestError = type("R", (Exception,), {})
            mh.RemoteProtocolError = type("RP", (Exception,), {})
            r = is_alive("https://pdf.com")
        self.assertFalse(r.alive)
        self.assertTrue(r.reason.startswith("non_html_content"))

    def test_empty_url(self):
        r = is_alive("")
        self.assertFalse(r.alive)
        self.assertEqual(r.reason, "empty_url")


# ─────────────────────────────────────────────────────────────────────
#  Gate de completitud (modo precisión)
# ─────────────────────────────────────────────────────────────────────

class TestPrecisionCompletenessGate(unittest.TestCase):
    """Tests del helper estático _missing_required_fields."""

    def setUp(self):
        self.fn = DomainPipelineOrchestrator._missing_required_fields

    def test_no_fields_requested_returns_empty(self):
        self.assertEqual(self.fn({"email": None}, []), [])

    def test_no_contact_returns_all_fields(self):
        self.assertEqual(
            self.fn(None, ["email", "phone", "social"]),
            ["email", "phone", "social"],
        )

    def test_all_fields_present(self):
        contact = {
            "email": "info@acme.com",
            "phone": "+34 600 000 000",
            "social_media": [{"platform": "linkedin", "url": "x"}],
        }
        self.assertEqual(self.fn(contact, ["email", "phone", "social"]), [])

    def test_missing_phone_only(self):
        contact = {
            "email": "info@acme.com",
            "phone": "",
            "social_media": [{"platform": "x", "url": "y"}],
        }
        self.assertEqual(self.fn(contact, ["email", "phone", "social"]), ["phone"])

    def test_missing_social_only(self):
        contact = {
            "email": "info@acme.com",
            "phone": "+34 600 000 000",
            "social_media": [],
        }
        self.assertEqual(self.fn(contact, ["email", "phone", "social"]), ["social"])

    def test_email_whitespace_treated_as_missing(self):
        contact = {"email": "   ", "phone": "+34 ...", "social_media": [{"platform": "x", "url": "y"}]}
        self.assertEqual(self.fn(contact, ["email", "phone", "social"]), ["email"])

    def test_only_subset_requested(self):
        contact = {"email": "a@b.com", "phone": None, "social_media": []}
        # El usuario pidió solo email — el resto da igual.
        self.assertEqual(self.fn(contact, ["email"]), [])

    def test_multiple_missing(self):
        contact = {"email": None, "phone": None, "social_media": []}
        self.assertEqual(
            self.fn(contact, ["email", "phone", "social"]),
            ["email", "phone", "social"],
        )


if __name__ == "__main__":
    unittest.main()
