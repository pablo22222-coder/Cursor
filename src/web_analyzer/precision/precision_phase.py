"""
PrecisionPhase — orquestador de la Fase 2 en modo precisión.

Encapsula la lógica completa de la fase para que `domain_pipeline.py` solo
tenga que llamar a `PrecisionPhase.run(domain, url, intent, ...)` y
recibir un resultado consolidado: pasa o no pasa, qué información se
recolectó, con qué motivo se rechazó, etc.

Entrada (lo que ya tiene el pipeline):
  · domain, url
  · `intent` (SearchIntent) con los flags de routing ya rellenados
  · `degradation` (PrecisionDegradation) — sistema de relajación progresiva

Salida: PrecisionPhaseResult con:
  · passed (bool)
  · stage_at_failure ("html" | "judge" | "...")
  · html_context (dict)
  · tech_findings (dict | None)
  · pagespeed_report (dict | None)
  · verdict (JudgeVerdict)
  · pagespeed_used (bool)
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.web_analyzer.precision.html_context import (
    HTMLContext,
    build_context,
    render_markdown,
    TOTAL_TIMEOUT_SECONDS as HTML_PHASE_TOTAL_TIMEOUT,
)
from src.web_analyzer.precision.tech_scanner import scan_technologies
from src.web_analyzer.precision.pagespeed_targeted import (
    run_pagespeed,
    PAGESPEED_TIMEOUT_SECONDS,
)
from src.web_analyzer.precision.precision_judge import judge_domain, JudgeVerdict


# ─────────────────────────────────────────────────────────────────────
#  Sistema de degradación progresiva
# ─────────────────────────────────────────────────────────────────────

@dataclass
class PrecisionDegradation:
    """
    Estado compartido entre los workers de la Fase 2 que va relajando
    los criterios cuando lleva mucho tiempo sin encontrar dominios que
    pasen el filtro.

    Niveles:
      0 — Estricto: PageSpeed activo si la IA lo pidió. Juez estricto.
      1 — Relajado L1: el juez recibe modo de relajación nivel 1.
      2 — Relajado L2: el juez recibe nivel 2 (más permisivo).
      3 — PageSpeed OFF: aunque la IA lo pidiera, se desactiva.
      4 — Modo emergencia: solo HTML + relajación máxima.
    """
    stuck_seconds_per_level: float = 45.0
    pagespeed_drop_at_level: int = 3
    max_level: int = 4

    _level: int = 0
    _last_pass_at: float = field(default_factory=time.monotonic)
    _started_at: float = field(default_factory=time.monotonic)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _passes: int = 0

    def mark_pass(self):
        with self._lock:
            self._passes += 1
            self._last_pass_at = time.monotonic()

    def mark_check(self):
        """Cada worker llama aquí antes de procesar un dominio para que
        el nivel se ajuste si llevamos demasiado tiempo sin nada."""
        with self._lock:
            now = time.monotonic()
            stuck = now - self._last_pass_at
            target_level = min(self.max_level, int(stuck / self.stuck_seconds_per_level))
            if target_level > self._level:
                self._level = target_level
                # Reset del cronómetro al subir de nivel para no
                # encadenar saltos en cascada.
                self._last_pass_at = now

    @property
    def level(self) -> int:
        with self._lock:
            return self._level

    @property
    def relax_level(self) -> int:
        """Nivel de relajación que se le pasa al juez."""
        with self._lock:
            return min(self._level, 2)

    @property
    def pagespeed_disabled(self) -> bool:
        with self._lock:
            return self._level >= self.pagespeed_drop_at_level

    def status_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "level": self._level,
                "passes": self._passes,
                "stuck_seconds": round(time.monotonic() - self._last_pass_at, 1),
                "pagespeed_disabled": self._level >= self.pagespeed_drop_at_level,
            }


# ─────────────────────────────────────────────────────────────────────
#  Resultado consolidado
# ─────────────────────────────────────────────────────────────────────

@dataclass
class PrecisionPhaseResult:
    domain: str
    url: str
    passed: bool = False
    skipped: bool = False
    skip_reason: Optional[str] = None
    stage_at_failure: Optional[str] = None
    error: Optional[str] = None
    elapsed_ms: float = 0.0

    html_context: Optional[Dict[str, Any]] = None
    tech_findings: Optional[Dict[str, Any]] = None
    pagespeed_report: Optional[Dict[str, Any]] = None
    verdict: Optional[Dict[str, Any]] = None

    relax_level: int = 0
    degradation_level: int = 0
    pagespeed_used: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "url": self.url,
            "passed": self.passed,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "stage_at_failure": self.stage_at_failure,
            "error": self.error,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "html_context": self.html_context,
            "tech_findings": self.tech_findings,
            "pagespeed_report": self.pagespeed_report,
            "verdict": self.verdict,
            "relax_level": self.relax_level,
            "degradation_level": self.degradation_level,
            "pagespeed_used": self.pagespeed_used,
        }


# ─────────────────────────────────────────────────────────────────────
#  Helpers internos
# ─────────────────────────────────────────────────────────────────────

def _run_pagespeed_with_thread_timeout(
    url: str,
    *,
    categories: List[str],
    strategy: str,
    timeout: float,
) -> Dict[str, Any]:
    """Envuelve run_pagespeed en un thread por si requests no respeta el timeout."""
    holder: Dict[str, Any] = {"out": None}

    def _runner():
        try:
            holder["out"] = run_pagespeed(
                url, categories=categories, strategy=strategy, timeout=timeout,
            )
        except Exception as exc:
            holder["out"] = {
                "available": False, "ran": False,
                "fallback_reason": "exception",
                "error": f"{type(exc).__name__}: {str(exc)[:120]}",
                "scores": {}, "core_web_vitals": {}, "blocks": {},
                "categories_requested": categories,
                "strategy": strategy,
                "elapsed_ms": 0.0,
            }

    th = threading.Thread(target=_runner, daemon=True)
    th.start()
    th.join(timeout=timeout + 5)  # margen extra sobre el timeout HTTP
    if th.is_alive() or not isinstance(holder.get("out"), dict):
        return {
            "available": False, "ran": False,
            "fallback_reason": "thread_timeout",
            "error": f"PageSpeed thread excedió {timeout + 5}s",
            "scores": {}, "core_web_vitals": {}, "blocks": {},
            "categories_requested": categories, "strategy": strategy,
            "elapsed_ms": 0.0,
        }
    return holder["out"]


# ─────────────────────────────────────────────────────────────────────
#  Controlador principal
# ─────────────────────────────────────────────────────────────────────

class PrecisionPhase:
    """Encapsula la Fase 2 completa para un dominio."""

    def __init__(
        self,
        intent,
        degradation: Optional[PrecisionDegradation] = None,
        *,
        on_stage: Optional[callable] = None,
    ):
        self.intent = intent
        self.degradation = degradation or PrecisionDegradation()
        # callback(stage_name: str, message: str) para actualizar UI/estado
        self.on_stage = on_stage

    # ──────────────────────────────────────────────────────────────
    def run(self, domain: str, url: str) -> PrecisionPhaseResult:
        started = time.monotonic()
        result = PrecisionPhaseResult(domain=domain, url=url)
        result.degradation_level = self.degradation.level
        result.relax_level = self.degradation.relax_level

        if not url:
            result.error = "empty_url"
            result.stage_at_failure = "html"
            result.elapsed_ms = (time.monotonic() - started) * 1000
            return result

        self.degradation.mark_check()
        result.degradation_level = self.degradation.level
        result.relax_level = self.degradation.relax_level

        # ── 1) Descarga + extracción de capas ──────────────────────
        if self.on_stage:
            try:
                self.on_stage("html_fetch", "Descargando HTML con httpx...")
            except Exception:
                pass

        ctx: HTMLContext = build_context(url)
        result.html_context = ctx.to_dict()

        # Si no tenemos HTML útil, no podemos juzgar.
        if not ctx.html_length:
            result.stage_at_failure = "html"
            result.error = ctx.error or "no_html"
            result.elapsed_ms = (time.monotonic() - started) * 1000
            return result

        # ── 2) Tech scanner (opcional) ─────────────────────────────
        tech_findings: Optional[Dict[str, Any]] = None
        if self._should_run_scanner():
            if self.on_stage:
                try:
                    self.on_stage("tech_scanner", "Wappalyzer + ADN...")
                except Exception:
                    pass
            try:
                tech_findings = scan_technologies(
                    url,
                    html=ctx.raw_html,
                    target_techs=list(self.intent.target_techs or []),
                    relevant_dimensions=list(self.intent.scanner_dimensions or []),
                )
            except Exception as exc:
                tech_findings = {
                    "tech_stage_active": True,
                    "wappalyzer_status": "error",
                    "dna_status": "error",
                    "error": f"{type(exc).__name__}: {str(exc)[:120]}",
                    "wappalyzer_all_techs": [],
                    "wappalyzer_categories": {},
                    "dna_evidence": {},
                    "social_profiles": [],
                    "raw_footprint": [],
                    "technologies_confirmed": {},
                    "all_targets_met": False,
                    "targets_requested": list(self.intent.target_techs or []),
                }
        result.tech_findings = tech_findings

        # ── 3) PageSpeed (opcional + degradable) ───────────────────
        pagespeed_report: Optional[Dict[str, Any]] = None
        ps_active = self._should_run_pagespeed()
        if ps_active:
            if self.on_stage:
                try:
                    self.on_stage("pagespeed", "PageSpeed Insights...")
                except Exception:
                    pass
            pagespeed_report = _run_pagespeed_with_thread_timeout(
                url,
                categories=list(self.intent.pagespeed_categories or ["performance"]),
                strategy="mobile",
                timeout=PAGESPEED_TIMEOUT_SECONDS,
            )
        result.pagespeed_report = pagespeed_report
        result.pagespeed_used = bool(pagespeed_report and pagespeed_report.get("ran"))

        # ── 4) Veredicto IA ────────────────────────────────────────
        if self.on_stage:
            try:
                self.on_stage("judge", "Auditor IA...")
            except Exception:
                pass
        markdown = render_markdown(ctx)
        verdict: JudgeVerdict = judge_domain(
            user_prompt=getattr(self.intent, "original_prompt", "") or "",
            domain=domain,
            html_markdown=markdown,
            tech_findings=tech_findings,
            pagespeed_report=pagespeed_report,
            relax_level=self.degradation.relax_level,
        )
        result.verdict = verdict.to_dict()

        if not verdict.passed:
            result.stage_at_failure = "judge"
            result.passed = False
        else:
            result.passed = True
            self.degradation.mark_pass()

        result.elapsed_ms = (time.monotonic() - started) * 1000
        return result

    # ──────────────────────────────────────────────────────────────
    #  Decisiones internas
    # ──────────────────────────────────────────────────────────────

    def _should_run_scanner(self) -> bool:
        # La IA decide; degradación nunca lo apaga (es barato).
        return bool(getattr(self.intent, "use_scanner", False))

    def _should_run_pagespeed(self) -> bool:
        if not bool(getattr(self.intent, "use_pagespeed", False)):
            return False
        if self.degradation.pagespeed_disabled:
            return False
        return True

__all__ = [
    "PrecisionPhase",
    "PrecisionPhaseResult",
    "PrecisionDegradation",
]
