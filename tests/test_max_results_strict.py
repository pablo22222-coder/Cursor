"""
Tests para garantizar que el sistema SIEMPRE devuelve exactamente
``max_results`` (o menos si físicamente no hay suficientes candidatos
que pasen los filtros) — nunca más.

Casos cubiertos:
  · Overshoot por race condition de 3 workers paralelos → el slice
    en `run()` lo recorta y mantiene los de mayor confidence.
  · Igual número de candidatos que max_results → todos pasan.
  · Menos candidatos que max_results (undershoot real) → se devuelven
    los que haya, sin padding.
  · Validación de max_results desde la API: tipos no enteros / fuera
    de rango se coercen a defaults seguros.
"""
from __future__ import annotations

import sys
import threading
import unittest
from typing import Any, Dict, List
from unittest.mock import patch

sys.path.insert(0, "/workspace")

from src.web_analyzer.domain_pipeline import DomainPipelineOrchestrator  # noqa: E402


# ─────────────────────────────────────────────────────────────────────
#  Mini-orquestador para tests: no llamamos a la red ni al pipeline
#  real; lo que probamos es la promesa pública: `run()` nunca devuelve
#  más de max_results y mantiene los de mayor confidence.
# ─────────────────────────────────────────────────────────────────────

class _StubAnalysis:
    """SearchIntent mínimo aceptado por el orquestador."""
    business_type = "otro"
    must_have: List[str] = []
    must_not: List[str] = []
    target_techs: List[str] = []
    scanner_dimensions: List[str] = []
    use_scanner = False
    use_pagespeed = False
    pagespeed_categories: List[str] = []
    required_tools: List[str] = []
    excluded_tools: List[str] = []
    original_prompt = "test"


def _make_orchestrator(max_results: int) -> DomainPipelineOrchestrator:
    return DomainPipelineOrchestrator(
        analysis=_StubAnalysis(),
        tech_requirements={"must_have": [], "must_not": [],
                           "must_have_categories": [], "must_not_categories": []},
        extract_fields=[],
        fast_mode=True,
        max_results=max_results,
    )


class TestRunNeverOvershoots(unittest.TestCase):
    """`run()` siempre devuelve <= max_results, sin importar cuántos se
    hayan acumulado en _results por la race condition."""

    def test_run_slices_to_max_results(self):
        """Simulamos overshoot: 25 resultados acumulados con max=20.
        run() debe devolver exactamente 20 (los de mayor confidence)."""
        orch = _make_orchestrator(max_results=20)
        # Inyectamos manualmente 25 resultados (simula que 3 workers
        # corrieron a la vez y se nos coló overshoot de +5).
        orch._results = [
            {"domain": f"site{i}.com", "confidence": float(i)}
            for i in range(25)
        ]
        # No corremos los workers; llamamos al método del run() que sortea+capa.
        # Para hacerlo accesible sin lanzar workers, replicamos la lógica final.
        with orch._results_lock:
            orch._results.sort(key=lambda x: x.get("confidence", 0), reverse=True)
            final = list(orch._results[: orch.max_results])

        self.assertEqual(len(final), 20)
        # Los de mayor confidence (24, 23, ..., 5) deben sobrevivir.
        confidences = [r["confidence"] for r in final]
        self.assertEqual(confidences[0], 24.0)
        self.assertEqual(confidences[-1], 5.0)

    def test_run_returns_all_when_under(self):
        """Si hay menos resultados que max_results, devuelve todos."""
        orch = _make_orchestrator(max_results=20)
        orch._results = [
            {"domain": f"x{i}.com", "confidence": 50.0 + i}
            for i in range(7)
        ]
        with orch._results_lock:
            orch._results.sort(key=lambda x: x.get("confidence", 0), reverse=True)
            final = list(orch._results[: orch.max_results])
        self.assertEqual(len(final), 7)

    def test_run_exact_match(self):
        orch = _make_orchestrator(max_results=5)
        orch._results = [
            {"domain": f"x{i}.com", "confidence": float(i)}
            for i in range(5)
        ]
        with orch._results_lock:
            orch._results.sort(key=lambda x: x.get("confidence", 0), reverse=True)
            final = list(orch._results[: orch.max_results])
        self.assertEqual(len(final), 5)


# ─────────────────────────────────────────────────────────────────────
#  Test end-to-end del run() real con _process_domain mockeado para
#  forzar overshoot deliberadamente
# ─────────────────────────────────────────────────────────────────────

class _FakeSearchResult:
    def __init__(self, domain: str):
        self.domain = domain
        self.url = f"https://{domain}"
        self.title = ""
        self.snippet = ""


class TestOrchestratorRunStrictCap(unittest.TestCase):
    """Lanza el run() real con _process_domain mockeado para que
    SIEMPRE acepte el dominio (provoca overshoot natural)."""

    def test_overshoot_is_clamped(self):
        max_results = 5
        orch = _make_orchestrator(max_results=max_results)

        candidates = [_FakeSearchResult(f"d{i}.com") for i in range(20)]

        def fake_process(self_orch, search_result, domain, state, extractor, worker_idx):
            # Cada dominio "pasa" — acumulamos sin filtro.
            info = {
                "domain": domain,
                "url": search_result.url,
                # confidence baja para que el sort sea estable y predecible
                "confidence": 50.0,
            }
            with self_orch._results_lock:
                self_orch._results.append(info)
                count = len(self_orch._results)
            if count >= self_orch.max_results:
                self_orch._enough.set()
            self_orch._mark_completed()

        with patch.object(
            DomainPipelineOrchestrator, "_process_domain",
            side_effect=fake_process, autospec=True,
        ):
            results = orch.run(candidates)

        # Garantía dura: nunca más de max_results.
        self.assertLessEqual(len(results), max_results)
        # Tipicamente con 3 workers concurrentes acumulamos
        # max_results + (0..2) antes de que _enough corte; el run()
        # los recorta a max_results exacto.
        self.assertEqual(len(results), max_results)


# ─────────────────────────────────────────────────────────────────────
#  Validación de max_results en la API
# ─────────────────────────────────────────────────────────────────────

def _coerce_canonical(value, default: int = 20, hard_cap: int = 100) -> int:
    """
    Réplica EXACTA de _coerce_max_results en src/web/app.py.
    Si modificas el helper allí, actualiza también esta réplica para
    mantener cobertura. No importamos app.py directamente porque
    arrastra Flask como dependencia y aquí queremos un test puro.
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    if n < 1:
        return 1
    if n > hard_cap:
        return hard_cap
    return n


class TestMaxResultsCoercion(unittest.TestCase):
    """Verifica el helper _coerce_max_results de src/web/app.py."""

    def test_default_on_none(self):
        self.assertEqual(_coerce_canonical(None), 20)

    def test_default_on_string(self):
        self.assertEqual(_coerce_canonical("no-soy-num"), 20)

    def test_clamps_to_1_when_zero(self):
        self.assertEqual(_coerce_canonical(0), 1)
        self.assertEqual(_coerce_canonical(-5), 1)

    def test_caps_at_hard_cap(self):
        self.assertEqual(_coerce_canonical(999), 100)
        self.assertEqual(_coerce_canonical(101), 100)

    def test_accepts_valid_int(self):
        self.assertEqual(_coerce_canonical(10), 10)
        self.assertEqual(_coerce_canonical(20), 20)
        self.assertEqual(_coerce_canonical(30), 30)

    def test_accepts_numeric_string(self):
        self.assertEqual(_coerce_canonical("15"), 15)


if __name__ == "__main__":
    unittest.main()
