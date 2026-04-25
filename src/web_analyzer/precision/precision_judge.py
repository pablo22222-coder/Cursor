"""
PrecisionJudge — último filtro de la Fase 2.

Recibe el contexto HTML estructurado, los hallazgos del Tech Scanner y
el informe de PageSpeed, y le pide a la IA un veredicto SI/NO sobre si
ese dominio cumple con lo que pidió el usuario y es suficientemente
fiable y profesional como para pasar a la Fase 3.

La IA es Groq (Llama 3 70B / 8B) por defecto, con fallback al resto de
providers de AIManager si Groq falla o no está disponible.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.services.ai_manager import get_ai_manager


# ─────────────────────────────────────────────────────────────────────
#  Prompt del Auditor
# ─────────────────────────────────────────────────────────────────────

_JUDGE_SYSTEM_PROMPT = """\
ROL
Eres un Auditor de Calidad y Relevancia Web. Tu misión es actuar como
el último filtro de seguridad y pertinencia antes de procesar un
dominio.

OBJETIVO
Determinar si el dominio analizado cumple con los estándares de
fiabilidad técnica y, sobre todo, si encaja con la necesidad específica
del usuario.

CONTEXTO DE ENTRADA (VARIABLES)
Para tomar tu decisión, dispones de:
1. [Prompt del usuario / prompt creado por la IA] — describe la web
   ideal o el comprador ideal del producto. Es tu métrica principal de
   éxito.
2. [HTML de la web] — contenido y estructura visual del sitio,
   resumido en formato Markdown.
3. [Análisis Wappalyzer / ADN] — tecnologías detectadas (puede estar
   vacío si la fase no se activó o si no se encontraron evidencias).
4. [Análisis PageSpeed] — salud técnica y seguridad (puede estar vacío
   si la fase no se activó o si la API falló).

CRITERIOS DE DECISIÓN
Responderás "SI" únicamente si se cumplen estas tres condiciones:

  · Relevancia: el contenido del HTML y las tecnologías detectadas
    coinciden con lo que el usuario solicitó en su prompt. No seas
    super estricto: estás filtrando para un software automatizado, no
    quieres bloquear webs que claramente encajan aunque no coincidan
    al 100% con cada palabra del prompt.

  · Fiabilidad: la web no presenta señales de abandono, errores
    críticos de servidor o vulnerabilidades de seguridad graves
    según PageSpeed.

  · Profesionalismo: el sitio tiene una estructura mínima que
    demuestra que es una entidad activa y no un dominio aparcado
    (parking) o un template vacío.

Responderás "NO" si el sitio es irrelevante para el usuario, inseguro
o técnicamente deficiente.

REGLA DE ORO DE SALIDA (SIN EXCEPCIONES)
Tu respuesta debe ser exclusivamente UNA palabra: "SI" o "NO".
Está estrictamente prohibido añadir explicaciones, puntuaciones,
comentarios o cualquier tipo de formato adicional.
"""


# Sentinel para indicar al juez "no se ejecutó esta sub-fase".
_EMPTY_PLACEHOLDER = "(no ejecutado para este dominio)"


# ─────────────────────────────────────────────────────────────────────
#  Dataclass del veredicto
# ─────────────────────────────────────────────────────────────────────

@dataclass
class JudgeVerdict:
    """Salida del auditor."""
    passed: bool = False
    raw_response: str = ""
    provider: str = ""
    elapsed_ms: float = 0.0
    error: Optional[str] = None
    # Severidad: 0 = NO claro, 1 = NO al desempate, 2 = SI relajado, 3 = SI claro.
    score: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "raw_response": self.raw_response,
            "provider": self.provider,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "error": self.error,
            "score": self.score,
        }


# ─────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────

def _summarize_tech(tech_findings: Optional[Dict[str, Any]]) -> str:
    if not tech_findings or not tech_findings.get("tech_stage_active"):
        return _EMPTY_PLACEHOLDER
    parts: List[str] = []
    wapp_status = tech_findings.get("wappalyzer_status")
    if wapp_status:
        techs = tech_findings.get("wappalyzer_all_techs") or []
        if techs:
            parts.append("Wappalyzer detectó: " + ", ".join(techs[:25]))
        else:
            parts.append(f"Wappalyzer ({wapp_status}): sin tecnologías detectadas")
    confirmed = tech_findings.get("technologies_confirmed") or {}
    if confirmed:
        lines = []
        for tech_name, info in confirmed.items():
            ok = info.get("found")
            if ok:
                ev = (info.get("evidence") or "")[:120]
                src = info.get("source") or "?"
                lines.append(f"  · {tech_name}: SI ({src}) — {ev}")
            else:
                lines.append(f"  · {tech_name}: NO (sin evidencia)")
        if lines:
            parts.append("Targets pedidos:\n" + "\n".join(lines))
    socials = tech_findings.get("social_profiles") or []
    if socials:
        parts.append("Perfiles sociales: " + ", ".join(
            f"{s.get('platform')}={s.get('url')}" for s in socials[:6]
        ))
    raw_fp = tech_findings.get("raw_footprint") or []
    if raw_fp:
        parts.append("Dominios externos: " + ", ".join(raw_fp[:15]))
    return "\n".join(parts) if parts else _EMPTY_PLACEHOLDER


def _summarize_pagespeed(ps: Optional[Dict[str, Any]]) -> str:
    if not ps or not ps.get("ran"):
        if ps and ps.get("fallback_reason"):
            return f"({ps.get('fallback_reason')})"
        return _EMPTY_PLACEHOLDER
    parts: List[str] = []
    scores = ps.get("scores") or {}
    if scores:
        readable = ", ".join(
            f"{k}={v}" for k, v in scores.items() if v is not None
        )
        if readable:
            parts.append(f"Scores Lighthouse: {readable}")
    cwv = ps.get("core_web_vitals") or {}
    if cwv:
        cwv_short = {k: v for k, v in cwv.items() if v is not None}
        if cwv_short:
            parts.append(f"Core Web Vitals (CrUX): {json.dumps(cwv_short, ensure_ascii=False)[:300]}")
    blocks = ps.get("blocks") or {}
    if blocks:
        # Para cada bloque nos quedamos con un resumen muy corto.
        for block_name, block_data in blocks.items():
            if not block_data:
                continue
            try:
                serialized = json.dumps(block_data, ensure_ascii=False)
            except Exception:
                serialized = str(block_data)
            parts.append(f"[{block_name}]: {serialized[:400]}")
    return "\n".join(parts) if parts else _EMPTY_PLACEHOLDER


def _build_user_prompt(
    user_prompt: str,
    domain: str,
    html_markdown: str,
    tech_summary: str,
    pagespeed_summary: str,
) -> str:
    return (
        f"[PROMPT DEL USUARIO]\n{user_prompt.strip()}\n\n"
        f"[DOMINIO ANALIZADO]\n{domain}\n\n"
        f"[HTML DE LA WEB — formato Markdown]\n{html_markdown.strip()}\n\n"
        f"[ANÁLISIS WAPPALYZER / ADN]\n{tech_summary.strip()}\n\n"
        f"[ANÁLISIS PAGESPEED]\n{pagespeed_summary.strip()}\n\n"
        "Respuesta:"
    )


_RE_YES = re.compile(r"\b(?:s[ií]|si|yes)\b", re.IGNORECASE)
_RE_NO  = re.compile(r"\bno\b", re.IGNORECASE)


def _parse_yes_no(text: str) -> Optional[bool]:
    """Devuelve True (SI), False (NO) o None si no es interpretable."""
    if not text:
        return None
    t = text.strip()
    # Coger la primera palabra "limpia"
    head = re.sub(r"[^\wáéíóúñ]", " ", t, flags=re.IGNORECASE).strip().split()
    if not head:
        return None
    first = head[0].lower()
    if first in ("si", "sí", "yes"):
        return True
    if first == "no":
        return False
    # Fallback: buscar la primera mención clara
    if _RE_YES.search(t) and not _RE_NO.search(t):
        return True
    if _RE_NO.search(t) and not _RE_YES.search(t):
        return False
    return None


# ─────────────────────────────────────────────────────────────────────
#  API pública
# ─────────────────────────────────────────────────────────────────────

def judge_domain(
    *,
    user_prompt: str,
    domain: str,
    html_markdown: str,
    tech_findings: Optional[Dict[str, Any]] = None,
    pagespeed_report: Optional[Dict[str, Any]] = None,
    relax_level: int = 0,
) -> JudgeVerdict:
    """
    Llama al auditor IA y devuelve un JudgeVerdict.

    relax_level: nivel de relajación de criterios.
        0  → veredicto estricto (default).
        1+ → se le indica al juez que afloje y solo descarte casos
             claramente irrelevantes/inseguros. El sistema de
             degradación progresiva del pipeline va subiendo este
             número cuando lleva mucho tiempo sin encontrar webs.
    """
    started = time.monotonic()
    if not domain:
        return JudgeVerdict(passed=False, error="empty_domain")

    tech_summary = _summarize_tech(tech_findings)
    ps_summary = _summarize_pagespeed(pagespeed_report)

    system = _JUDGE_SYSTEM_PROMPT
    if relax_level >= 1:
        system += (
            "\n\nMODO DE RELAJACIÓN ACTIVO (nivel "
            f"{relax_level}). Estás filtrando para un software que lleva "
            "tiempo sin encontrar webs suficientes. Sé MENOS estricto: "
            "responde NO solo si la web es claramente irrelevante para "
            "el prompt o tiene problemas técnicos graves. En caso de "
            "duda, responde SI."
        )
    user_msg = _build_user_prompt(user_prompt, domain, html_markdown,
                                  tech_summary, ps_summary)

    try:
        ai = get_ai_manager()
        response = ai.complete(prompt=user_msg, system_prompt=system)
    except Exception as exc:
        return JudgeVerdict(
            passed=False,
            error=f"ai_manager_error:{type(exc).__name__}",
            elapsed_ms=(time.monotonic() - started) * 1000,
        )

    elapsed_ms = (time.monotonic() - started) * 1000
    if not response.success:
        return JudgeVerdict(
            passed=False,
            error=response.error or "ai_failed",
            provider=getattr(response, "provider", ""),
            elapsed_ms=elapsed_ms,
            raw_response=response.text or "",
        )

    raw_text = response.text or ""
    decision = _parse_yes_no(raw_text)
    passed = bool(decision) if decision is not None else False
    score = 3 if passed else 0
    if decision is None:
        # Cuando el modelo no responde claramente, tratamos como NO pero
        # con score=1 para que el sistema de degradación sepa que no
        # estamos completamente seguros.
        score = 1

    return JudgeVerdict(
        passed=passed,
        raw_response=raw_text.strip()[:200],
        provider=getattr(response, "provider", ""),
        elapsed_ms=elapsed_ms,
        score=score,
    )


__all__ = ["judge_domain", "JudgeVerdict"]
