"""
TechScanner — Controlador del análisis técnico de un dominio en modo precisión.

Orquesta dos motores en serie:

  Paso A — Detección rápida con Wappalyzer (4s timeout/web).
  Paso B — Análisis forense con DNA dirigido (5s timeout/web), SOLO sobre
           las tecnologías de target_techs que Wappalyzer no haya detectado.

El resultado es un objeto consolidado con un "Diccionario de Pruebas" por
cada tecnología pedida y métricas adicionales (todas las tecnologías
detectadas por Wappalyzer y los hallazgos completos del ADN, útiles para
el juez final).
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from src.web_analyzer.precision.dna_extractor import run_dna
from src.web_analyzer.wappalyzer_analyzer import WappalyzerAnalyzer, WappalyzerProfile


# Timeouts duros pedidos por especificación.
WAPPALYZER_TIMEOUT_SECONDS = 4
DNA_TIMEOUT_SECONDS = 5


# ─────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────

def _normalize_target(t: str) -> str:
    return (t or "").strip()


def _wappalyzer_has(profile: Optional[WappalyzerProfile], target: str) -> Optional[str]:
    """Si Wappalyzer detectó algo que case con `target`, devuelve el nombre exacto."""
    if profile is None or not profile.analysis_success:
        return None
    target_lc = target.lower().strip()
    if not target_lc:
        return None
    for tech_name in profile.all_technologies_names:
        if not isinstance(tech_name, str):
            continue
        if target_lc in tech_name.lower() or tech_name.lower() in target_lc:
            return tech_name
    return None


def _category_check(profile: Optional[WappalyzerProfile], target_lc: str) -> Optional[str]:
    """
    Si target es una categoría (cms, crm, analytics...), comprueba flags.
    Devuelve un string con la primera coincidencia o None.
    """
    if profile is None or not profile.analysis_success:
        return None
    cat_map = {
        "crm": ("has_crm", "crm"),
        "email": ("has_email_marketing", "email_marketing"),
        "email marketing": ("has_email_marketing", "email_marketing"),
        "email_marketing": ("has_email_marketing", "email_marketing"),
        "live chat": ("has_live_chat", "live_chat"),
        "live_chat": ("has_live_chat", "live_chat"),
        "chat": ("has_live_chat", "live_chat"),
        "analytics": ("has_analytics", "analytics"),
        "ecommerce": ("has_ecommerce", "ecommerce"),
        "cms": ("has_cms", "cms"),
        "payment": ("has_payment", "payment"),
        "payments": ("has_payment", "payment"),
    }
    if target_lc not in cat_map:
        return None
    flag_attr, list_attr = cat_map[target_lc]
    if not getattr(profile, flag_attr, False):
        return None
    items = getattr(profile, list_attr, []) or []
    if items:
        return f"{target_lc}: {', '.join(items[:3])}"
    return target_lc


def _run_wappalyzer_with_timeout(url: str, timeout: float) -> Optional[WappalyzerProfile]:
    """
    Ejecuta WappalyzerAnalyzer.analyze() con un timeout duro envolvente.
    Devuelve el profile si terminó a tiempo, None si excedió o falló.
    """
    analyzer = WappalyzerAnalyzer(timeout=int(timeout), wappalyzer_path="wappalyzergo")
    result_holder: Dict[str, Any] = {"profile": None, "error": None}

    def _runner():
        try:
            result_holder["profile"] = analyzer.analyze(url)
        except Exception as exc:  # pragma: no cover — defensivo
            result_holder["error"] = f"{type(exc).__name__}:{exc}"

    th = threading.Thread(target=_runner, daemon=True)
    started = time.monotonic()
    th.start()
    th.join(timeout=timeout)
    elapsed = time.monotonic() - started

    if th.is_alive():
        # No abortamos el thread (Python no puede cancelar threads de forma
        # segura), pero lo dejamos en daemon=True para que muera con el proceso.
        return None
    if result_holder.get("error"):
        return None
    profile = result_holder.get("profile")
    if isinstance(profile, WappalyzerProfile) and profile.analysis_success:
        return profile
    # Aunque analysis_success sea False puede traer info útil, pero el caller
    # querrá ignorarla; devolvemos None para que se use el fallback DNA.
    return profile if isinstance(profile, WappalyzerProfile) else None


def _run_dna_with_timeout(
    html: str,
    base_url: str,
    target_techs: List[str],
    timeout: float,
) -> Dict[str, Any]:
    """Ejecuta run_dna() en un thread con timeout duro."""
    holder: Dict[str, Any] = {"out": None, "error": None}

    def _runner():
        try:
            holder["out"] = run_dna(html, base_url, target_techs=target_techs or None)
        except Exception as exc:  # pragma: no cover — defensivo
            holder["error"] = f"{type(exc).__name__}:{exc}"

    th = threading.Thread(target=_runner, daemon=True)
    th.start()
    th.join(timeout=timeout)
    if th.is_alive() or holder.get("error") or not isinstance(holder.get("out"), dict):
        return {
            "dna_status": "timeout" if th.is_alive() else "error",
            "evidence_found": {"scripts": [], "iframes": [], "globals": [],
                               "comments": [], "forms": []},
            "social_profiles": [],
            "raw_footprint": [],
            "matched_targets": {},
        }
    return holder["out"]


# ─────────────────────────────────────────────────────────────────────
#  API pública
# ─────────────────────────────────────────────────────────────────────

def scan_technologies(
    url: str,
    *,
    html: Optional[str] = None,
    target_techs: Optional[List[str]] = None,
    relevant_dimensions: Optional[List[str]] = None,
    wappalyzer_timeout: float = WAPPALYZER_TIMEOUT_SECONDS,
    dna_timeout: float = DNA_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """
    Escanea las tecnologías de una URL siguiendo el orden Wappalyzer → DNA.

    Args:
        url: URL del dominio.
        html: HTML ya descargado (recomendado pasarlo desde la fase de
              extracción de contexto para no descargar dos veces).
        target_techs: Lista de tecnologías/categorías que necesita confirmar
                      el caller. Si está vacía o contiene "ALL" se reportan
                      todas las evidencias.
        relevant_dimensions: Las dimensiones del DNA que deben usarse.
                             Si es None se usan todas. Reservado para
                             optimizaciones futuras (la implementación
                             actual del DNA ya filtra por target_techs).

    Returns:
        Diccionario con la siguiente forma::

            {
              "tech_stage_active": True,
              "targets_requested": [...],
              "wappalyzer_status": "success" | "timeout" | "error" | "skipped",
              "wappalyzer_all_techs": [...],
              "wappalyzer_categories": {...},
              "dna_status": "success" | "timeout" | "skipped" | "error",
              "dna_evidence": {...},
              "social_profiles": [...],
              "raw_footprint": [...],
              "technologies_confirmed": {
                  "<TechName>": {
                      "found": True,
                      "source": "wappalyzer" | "dna_script" | "dna_iframe"
                                | "dna_global" | "dna_comment" | "dna_form",
                      "evidence": "<snippet o URL>",
                  },
                  ...
              },
              "all_targets_met": bool,
              "wappalyzer_time_ms": ...,
              "dna_time_ms": ...,
            }
    """
    targets_norm: List[str] = []
    if target_techs:
        for t in target_techs:
            if not t:
                continue
            tt = _normalize_target(t)
            if tt and tt not in targets_norm:
                targets_norm.append(tt)

    # Nota: si la lista está vacía o es "ALL" se mantiene comportamiento de
    # "reportar todo" — pero `technologies_confirmed` solo se rellena para
    # los targets concretos.
    targets_for_dna = targets_norm or ["ALL"]
    has_concrete_targets = bool(targets_norm) and not all(
        t.lower() == "all" for t in targets_norm
    )

    # ── Paso A · Wappalyzer ───────────────────────────────────────
    t0 = time.monotonic()
    wappalyzer_profile = _run_wappalyzer_with_timeout(url, wappalyzer_timeout)
    wappalyzer_time_ms = (time.monotonic() - t0) * 1000

    if wappalyzer_profile is None:
        wappalyzer_status = "timeout"
        wappalyzer_all_techs: List[str] = []
        wappalyzer_categories: Dict[str, List[str]] = {}
    else:
        wappalyzer_status = "success" if wappalyzer_profile.analysis_success else "error"
        wappalyzer_all_techs = list(wappalyzer_profile.all_technologies_names)
        wappalyzer_categories = {
            "cms":               wappalyzer_profile.cms,
            "ecommerce":         wappalyzer_profile.ecommerce,
            "crm":               wappalyzer_profile.crm,
            "email_marketing":   wappalyzer_profile.email_marketing,
            "analytics":         wappalyzer_profile.analytics,
            "live_chat":         wappalyzer_profile.live_chat,
            "payment":           wappalyzer_profile.payment,
            "frameworks":        wappalyzer_profile.frameworks,
            "cdn":               wappalyzer_profile.cdn,
            "hosting":           wappalyzer_profile.hosting,
            "security":          wappalyzer_profile.security,
        }

    # ── Construcción del diccionario de pruebas (parte Wappalyzer) ──
    technologies_confirmed: Dict[str, Dict[str, Any]] = {}
    pending_for_dna: List[str] = []

    if has_concrete_targets:
        for target in targets_norm:
            tech_match = _wappalyzer_has(wappalyzer_profile, target)
            if tech_match is None:
                cat_evidence = _category_check(wappalyzer_profile, target.lower())
                if cat_evidence is not None:
                    tech_match = cat_evidence
            if tech_match is not None:
                technologies_confirmed[target] = {
                    "found": True,
                    "source": "wappalyzer",
                    "evidence": tech_match,
                }
            else:
                technologies_confirmed[target] = {
                    "found": False,
                    "source": None,
                    "evidence": None,
                }
                pending_for_dna.append(target)

    # ── Paso B · DNA dirigido ──────────────────────────────────────
    # Solo se ejecuta si:
    #   · hay targets sin confirmar por Wappalyzer (modo dirigido), o
    #   · no hay targets concretos y queremos un footprint completo.
    dna_result: Dict[str, Any] = {}
    dna_time_ms = 0.0

    need_dna = bool(html)
    if has_concrete_targets and not pending_for_dna:
        # Wappalyzer ya cubrió todos los objetivos: no es necesario DNA.
        # Pero seguimos lanzándolo si tenemos HTML — los hallazgos extra
        # alimentan al juez final. Decisión de diseño: ahorramos el coste y
        # marcamos skipped cuando todos los targets concretos están cubiertos.
        need_dna = False
        dna_result = {
            "dna_status": "skipped",
            "reason": "all_targets_covered_by_wappalyzer",
            "evidence_found": {"scripts": [], "iframes": [], "globals": [],
                               "comments": [], "forms": []},
            "social_profiles": [],
            "raw_footprint": [],
            "matched_targets": {},
        }

    if need_dna:
        dna_targets = pending_for_dna if has_concrete_targets else targets_for_dna
        t1 = time.monotonic()
        dna_result = _run_dna_with_timeout(html or "", url, dna_targets, dna_timeout)
        dna_time_ms = (time.monotonic() - t1) * 1000

        # Mapear evidencias del DNA → technologies_confirmed
        if has_concrete_targets and dna_result.get("dna_status") == "success":
            matched: Dict[str, Any] = dna_result.get("matched_targets") or {}
            for target in pending_for_dna:
                evidences = matched.get(target.lower()) or []
                if not evidences:
                    continue
                # Elegimos la evidencia más informativa (script > form > iframe > global > comment).
                best, source = _pick_best_evidence(evidences)
                technologies_confirmed[target] = {
                    "found": True,
                    "source": source,
                    "evidence": best,
                }

    all_targets_met = bool(targets_norm) and all(
        v.get("found") for v in technologies_confirmed.values()
    )

    return {
        "tech_stage_active": True,
        "targets_requested": targets_norm,
        "wappalyzer_status": wappalyzer_status,
        "wappalyzer_time_ms": round(wappalyzer_time_ms, 1),
        "wappalyzer_all_techs": wappalyzer_all_techs,
        "wappalyzer_categories": wappalyzer_categories,
        "dna_status": dna_result.get("dna_status", "skipped"),
        "dna_time_ms": round(dna_time_ms, 1),
        "dna_evidence": dna_result.get("evidence_found", {}),
        "social_profiles": dna_result.get("social_profiles", []),
        "raw_footprint": dna_result.get("raw_footprint", []),
        "technologies_confirmed": technologies_confirmed,
        "all_targets_met": all_targets_met,
        "relevant_dimensions": relevant_dimensions or [],
    }


def _pick_best_evidence(evidences: List[Dict[str, Any]]) -> "tuple[str, str]":
    """De entre varias evidencias DNA, devuelve (texto, etiqueta_de_fuente)."""
    # Orden de preferencia.
    def _kind(ev: Dict[str, Any]) -> str:
        if "host" in ev and "action" in ev:
            return "dna_form"
        if "host" in ev and "url" in ev:
            return "dna_script_or_iframe"
        if "global" in ev:
            return "dna_global"
        if "tech" in ev and "snippet" in ev:
            return "dna_comment"
        return "dna_other"

    priorities = ["dna_script_or_iframe", "dna_form", "dna_global", "dna_comment", "dna_other"]
    sorted_evs = sorted(evidences, key=lambda e: priorities.index(_kind(e))
                        if _kind(e) in priorities else len(priorities))
    best = sorted_evs[0]
    kind = _kind(best)
    if kind == "dna_script_or_iframe":
        return best.get("url") or best.get("host") or "", "dna_script"
    if kind == "dna_form":
        return best.get("action") or best.get("host") or "", "dna_form"
    if kind == "dna_global":
        return best.get("snippet") or best.get("global") or "", "dna_global"
    if kind == "dna_comment":
        return best.get("snippet") or "", "dna_comment"
    return str(best), "dna_other"


__all__ = [
    "scan_technologies",
    "WAPPALYZER_TIMEOUT_SECONDS",
    "DNA_TIMEOUT_SECONDS",
]
