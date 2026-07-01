"""
Tests para los módulos de la Fase 2 (modo precisión).

No tocan red ni la API de PageSpeed: se centran en la extracción HTML,
el ADN, el sistema de degradación y el parser del juez.
"""
from __future__ import annotations

import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, "/workspace")

from src.web_analyzer.precision.html_context import (  # noqa: E402
    build_context, render_markdown, extract_clean_body,
)
from src.web_analyzer.precision.dna_extractor import run_dna  # noqa: E402
from src.web_analyzer.precision.precision_phase import (  # noqa: E402
    PrecisionDegradation, PrecisionPhase, PrecisionPhaseResult,
)
from src.web_analyzer.precision.precision_judge import (  # noqa: E402
    _parse_yes_no, judge_domain, JudgeVerdict,
)
from src.web_analyzer.precision.pagespeed_targeted import (  # noqa: E402
    _normalize_categories,
)
from bs4 import BeautifulSoup


SAMPLE_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
  <title>Acme · Bicicletas eléctricas Barcelona</title>
  <meta name="description" content="Tienda online de bicicletas eléctricas">
  <meta property="og:type" content="website">
  <meta property="og:description" content="Las mejores e-bikes urbanas">
  <script type="application/ld+json">
  {"@context":"https://schema.org","@type":"Store","name":"Acme Bikes"}
  </script>
  <!-- This site is optimized with the Yoast SEO plugin v21 -->
  <script src="https://js.stripe.com/v3/"></script>
  <script src="https://cdn.chimpstatic.com/mcjs.js"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    fbq('init', '12345');
  </script>
</head>
<body>
  <header><nav>
    <a href="/inicio">Inicio</a>
    <a href="/tienda">Tienda</a>
    <a href="/contacto">Contacto</a>
  </nav></header>
  <main>
    <h1>Bicicletas eléctricas urbanas</h1>
    <h2>Modelos en stock</h2>
    <p>Vendemos e-bikes premium para Barcelona y alrededores.</p>
    <button>Comprar ahora</button>
    <a href="/demo">Probar demo</a>
    <a href="/share">Compartir esto</a>
    <form action="https://us1.list-manage.com/subscribe/post"></form>
  </main>
  <footer>© 2026 Acme S.L. NIF B12345678 · Barcelona, España</footer>
  <iframe src="https://calendly.com/embed/foo"></iframe>
  <a href="https://linkedin.com/company/acme">LinkedIn</a>
  <a href="https://twitter.com/intent/tweet?text=hi">Tweet</a>
</body>
</html>
"""


class TestHTMLContext(unittest.TestCase):
    def test_build_context_extracts_layers(self):
        ctx = build_context("https://example.com/foo", html=SAMPLE_HTML)
        self.assertTrue(ctx.success, ctx.error)
        self.assertEqual(ctx.domain, "example.com")
        self.assertEqual(ctx.lang, "es")
        self.assertIn("Acme", ctx.title)
        self.assertEqual(ctx.og_type, "website")
        self.assertEqual(ctx.meta_description,
                         "Tienda online de bicicletas eléctricas")
        # Capa 2
        self.assertIn("Inicio", ctx.nav_links)
        self.assertEqual(ctx.h1, ["Bicicletas eléctricas urbanas"])
        self.assertEqual(ctx.h2, ["Modelos en stock"])
        # Capa 3
        self.assertIn("Store", ctx.schema_types)
        self.assertTrue(any("Comprar" in c for c in ctx.cta_texts))
        self.assertIn("NIF", ctx.footer_text)
        # Body limpio (Acme está en footer/header — eliminados; conservamos el texto principal)
        self.assertIn("Bicicletas", ctx.body_text)
        self.assertIn("Comprar ahora", ctx.body_text)
        # Raw HTML guardado
        self.assertEqual(ctx.raw_html, SAMPLE_HTML)

    def test_render_markdown_format(self):
        ctx = build_context("https://example.com", html=SAMPLE_HTML)
        md = render_markdown(ctx)
        self.assertIn("[CONTEXTO DEL SITIO WEB]", md)
        self.assertIn("DOMINIO: example.com", md)
        self.assertIn("[ESTRUCTURA DE NEGOCIO]", md)
        self.assertIn("[SEÑALES SEMÁNTICAS]", md)
        self.assertIn("[CUERPO DE TEXTO (RESUMEN)]", md)

    def test_empty_html_returns_error(self):
        ctx = build_context("https://example.com", html="")
        self.assertFalse(ctx.success)
        self.assertEqual(ctx.error, "empty_html")

    def test_extract_clean_body_decomposes_noise(self):
        soup = BeautifulSoup(SAMPLE_HTML, "lxml")
        body = extract_clean_body(soup, max_chars=1000)
        # No debería haber rastros de scripts ni footer
        self.assertNotIn("fbq", body)
        self.assertNotIn("Yoast", body)
        # El nav también se elimina
        self.assertNotIn("Inicio", body)


class TestDNA(unittest.TestCase):
    def test_dna_all_mode_detects_third_parties(self):
        out = run_dna(SAMPLE_HTML, "https://example.com", target_techs=["ALL"])
        self.assertEqual(out["dna_status"], "success")
        self.assertEqual(out["mode"], "all")
        scripts = out["evidence_found"]["scripts"]
        self.assertTrue(any(e["host"] == "js.stripe.com" for e in scripts))
        forms = out["evidence_found"]["forms"]
        self.assertTrue(any("list-manage.com" in e["host"] for e in forms))
        self.assertTrue(any(c["tech"] == "Yoast SEO"
                             for c in out["evidence_found"]["comments"]))
        self.assertTrue(any(g["global"] == "fbq"
                             for g in out["evidence_found"]["globals"]))
        # Sociales: linkedin sí, twitter intent no
        platforms = [s["platform"] for s in out["social_profiles"]]
        self.assertIn("linkedin", platforms)
        self.assertNotIn("twitter", platforms)

    def test_dna_targeted_filters_results(self):
        out = run_dna(SAMPLE_HTML, "https://example.com",
                       target_techs=["Stripe"])
        self.assertEqual(out["mode"], "targeted")
        self.assertIn("stripe", out["matched_targets"])
        # Mailchimp no debería estar en scripts ni forms
        scripts = out["evidence_found"]["scripts"]
        self.assertFalse(any("chimpstatic" in e["host"] for e in scripts))

    def test_dna_skipped_on_empty_html(self):
        out = run_dna("", "https://example.com", target_techs=["Stripe"])
        self.assertEqual(out["dna_status"], "skipped")


class TestDegradation(unittest.TestCase):
    def test_starts_at_zero(self):
        d = PrecisionDegradation()
        self.assertEqual(d.level, 0)
        self.assertFalse(d.pagespeed_disabled)
        self.assertEqual(d.relax_level, 0)

    def test_progressive_levels(self):
        d = PrecisionDegradation(stuck_seconds_per_level=10.0,
                                  pagespeed_drop_at_level=3)
        d._last_pass_at = time.monotonic() - 9
        d.mark_check()
        self.assertEqual(d.level, 0)

        d._last_pass_at = time.monotonic() - 12
        d.mark_check()
        self.assertEqual(d.level, 1)

        d._last_pass_at = time.monotonic() - 25
        d.mark_check()
        self.assertGreaterEqual(d.level, 2)

        d._last_pass_at = time.monotonic() - 40
        d.mark_check()
        self.assertGreaterEqual(d.level, 3)
        self.assertTrue(d.pagespeed_disabled)
        # relax_level se capa a 2
        self.assertEqual(d.relax_level, 2)

    def test_mark_pass_resets_clock(self):
        d = PrecisionDegradation(stuck_seconds_per_level=10.0)
        d._last_pass_at = time.monotonic() - 50
        d.mark_check()
        self.assertGreaterEqual(d.level, 4)
        d.mark_pass()
        # Aún sigue en nivel alto (no bajamos automáticamente),
        # pero el cronómetro se resetea.
        self.assertLess(time.monotonic() - d._last_pass_at, 1.0)

    # ── Degradación por CONTEO de rechazos (lo que pidió el usuario) ──

    def test_count_based_bumps_level(self):
        """Tras N rechazos consecutivos sube un nivel, sin depender del
        tiempo (determinista)."""
        d = PrecisionDegradation(stuck_rejections_per_level=5,
                                  stuck_seconds_per_level=99999)  # tiempo desactivado
        for _ in range(4):
            d.mark_reject()
        self.assertEqual(d.level, 0)   # aún no llega al umbral
        d.mark_reject()                # 5º rechazo → sube
        self.assertEqual(d.level, 1)

    def test_count_based_multiple_levels(self):
        d = PrecisionDegradation(stuck_rejections_per_level=3,
                                  stuck_seconds_per_level=99999,
                                  pagespeed_drop_at_level=3)
        for _ in range(3):
            d.mark_reject()
        self.assertEqual(d.level, 1)
        for _ in range(3):
            d.mark_reject()
        self.assertEqual(d.level, 2)
        for _ in range(3):
            d.mark_reject()
        self.assertEqual(d.level, 3)
        self.assertTrue(d.pagespeed_disabled)

    def test_pass_resets_rejection_counter(self):
        """Un aprobado resetea el contador de rechazos consecutivos:
        la calidad no se degrada si vamos encontrando webs."""
        d = PrecisionDegradation(stuck_rejections_per_level=5,
                                  stuck_seconds_per_level=99999)
        for _ in range(4):
            d.mark_reject()
        d.mark_pass()                  # reset
        for _ in range(4):
            d.mark_reject()
        self.assertEqual(d.level, 0)   # nunca llegó a 5 seguidos

    def test_count_never_exceeds_max_level(self):
        d = PrecisionDegradation(stuck_rejections_per_level=1,
                                  stuck_seconds_per_level=99999,
                                  max_level=4)
        for _ in range(50):
            d.mark_reject()
        self.assertEqual(d.level, 4)

    def test_status_dict_reports_rejections(self):
        d = PrecisionDegradation(stuck_rejections_per_level=100,
                                  stuck_seconds_per_level=99999)
        d.mark_reject(); d.mark_reject()
        st = d.status_dict()
        self.assertEqual(st["rejections"], 2)
        self.assertEqual(st["rejections_since_level"], 2)
        self.assertIn("level", st)
        self.assertIn("pagespeed_disabled", st)


class TestJudgeParser(unittest.TestCase):
    def test_parse_yes_no(self):
        self.assertTrue(_parse_yes_no("SI"))
        self.assertTrue(_parse_yes_no("Sí"))
        self.assertTrue(_parse_yes_no("YES"))
        self.assertTrue(_parse_yes_no(" SI \n"))
        self.assertFalse(_parse_yes_no("NO"))
        self.assertFalse(_parse_yes_no("No, esta web no encaja."))
        self.assertIsNone(_parse_yes_no(""))
        self.assertIsNone(_parse_yes_no("quizás"))

    def test_judge_with_mocked_ai(self):
        from src.services.providers.base_provider import AIResponse

        def fake_complete(task, prompt, system_prompt="", *, json_mode=True):
            return AIResponse(text="SI", provider="stub", model="stub")

        with patch(
            "src.web_analyzer.precision.precision_judge.complete_for_task",
            side_effect=fake_complete,
        ):
            v = judge_domain(
                user_prompt="ecommerce de e-bikes",
                domain="acme.com",
                html_markdown="contenido",
                tech_findings=None,
                pagespeed_report=None,
                relax_level=0,
            )
        self.assertTrue(v.passed)
        self.assertEqual(v.provider, "stub")
        self.assertEqual(v.score, 3)

    def test_judge_no_response(self):
        from src.services.providers.base_provider import AIResponse

        def fake_complete(task, prompt, system_prompt="", *, json_mode=True):
            return AIResponse(text="NO", provider="stub", model="stub")

        with patch(
            "src.web_analyzer.precision.precision_judge.complete_for_task",
            side_effect=fake_complete,
        ):
            v = judge_domain(
                user_prompt="x", domain="a.com", html_markdown="x",
            )
        self.assertFalse(v.passed)
        self.assertEqual(v.score, 0)


class TestPagespeedHelpers(unittest.TestCase):
    def test_normalize_categories_keeps_only_valid(self):
        self.assertEqual(_normalize_categories(["performance", "seo"]),
                         ["performance", "seo"])
        # Sinónimos / ruido se filtran
        self.assertIn("accessibility",
                      _normalize_categories(["A11Y", "performance"]))
        # ALL → todas
        out = _normalize_categories(["ALL"])
        self.assertIn("performance", out)
        self.assertIn("seo", out)
        # Vacío → todas
        out = _normalize_categories([])
        self.assertIn("performance", out)


class TestPrecisionPhaseSkip(unittest.TestCase):
    def test_run_with_empty_url_returns_error(self):
        from types import SimpleNamespace
        intent = SimpleNamespace(
            original_prompt="prompt",
            target_techs=[], scanner_dimensions=[],
            use_scanner=False, use_pagespeed=False,
            pagespeed_categories=[],
        )
        phase = PrecisionPhase(intent=intent)
        result = phase.run("acme.com", "")
        self.assertFalse(result.passed)
        self.assertEqual(result.error, "empty_url")
        self.assertEqual(result.stage_at_failure, "html")


if __name__ == "__main__":
    unittest.main()
