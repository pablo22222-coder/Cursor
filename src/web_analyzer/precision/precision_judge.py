"""
PrecisionJudge — último filtro de la Fase 2.

Recibe el contexto HTML estructurado, los hallazgos del Tech Scanner y
el informe de PageSpeed, y le pide a la IA un veredicto SI/NO sobre si
ese dominio cumple con lo que pidió el usuario y es suficientemente
fiable y profesional como para pasar a la Fase 3.

Cadena de fallback usada (definida en src/services/task_chains.py):
    Cerebras 8B → Groq 70B → Groq 8B → Gemini Flash → User Own
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.services.ai_manager import complete_for_task
from src.services.task_chains import TASK_VALIDATION


# ─────────────────────────────────────────────────────────────────────
#  Prompt del Auditor (reescrito en versión profesional)
# ─────────────────────────────────────────────────────────────────────

_JUDGE_SYSTEM_PROMPT = """\
ROL
Eres "Domain Relevance Auditor", un auditor automático de webs cuya
única función es decidir, en una sola palabra, si un dominio concreto
debe pasar a la fase de extracción de contactos del pipeline o ser
descartado. Tu juicio es la última puerta antes de gastar recursos en
ese dominio, así que es vital que aciertes el SI, pero también que no
te pongas tan duro que descartes webs que claramente encajan.

OBJETIVO
Decidir SI / NO mirando si el dominio:
  (a) encaja con la necesidad del usuario,
  (b) parece técnicamente fiable y activo, y
  (c) presenta el aspecto mínimo de un negocio real.

ENTRADAS QUE RECIBIRÁS
1. [PROMPT DEL USUARIO]
   La descripción del tipo de web que se busca. En modo Producto, este
   prompt lo ha generado la IA a partir del producto del usuario y
   describe el COMPRADOR IDEAL. Es tu vara de medir principal.

2. [DOMINIO ANALIZADO]
   El dominio que estás auditando.

3. [HTML DE LA WEB — formato Markdown]
   Resumen estructurado del contenido visible: dominio, idioma, título,
   meta descripción, og:type / og:description, secciones de navegación,
   H1 y H2, schema.org / JSON-LD, CTAs, footer y body limpio.
   Si una sub-sección viene "(no ejecutado para este dominio)" o
   vacía, NO la penalices: simplemente no hay datos de esa señal.

4. [ANÁLISIS WAPPALYZER / ADN]
   Tecnologías detectadas en el sitio (CMS, ecommerce, CRM, pixeles,
   chat, scripts de terceros, etc.) y, cuando el prompt pedía
   tecnologías concretas, la confirmación SI/NO para cada una.
   Puede venir vacío si la fase técnica no se activó.

5. [ANÁLISIS PAGESPEED]
   Salud técnica del sitio: scores Lighthouse (perf/SEO/accesibilidad/
   best practices), Core Web Vitals reales (CrUX) e indicadores
   relevantes. Puede venir vacío si la fase no se activó o si la API
   falló (esto NO es motivo de descarte).

CRITERIOS — TODOS deben cumplirse para responder "SI"

  · RELEVANCIA (peso alto). El contenido del HTML y las tecnologías
    detectadas son CLARAMENTE compatibles con lo que el usuario pidió.
    Razona con el contexto, no con coincidencia literal: si el prompt
    dice "clínica dental en Madrid" y el HTML es de "Centro Odontológico
    Sánchez · Madrid" → SI, aunque no diga "clínica" exactamente.
    Tolera variaciones de idioma, sinónimos y nichos cercanos.
    Si el prompt exigía una tecnología concreta y los hallazgos
    técnicos la confirman como NO presente → eso pesa fuerte contra.

  · FIABILIDAD (peso medio). El sitio no muestra señales de abandono
    grave ni vulnerabilidades de seguridad serias detectadas por
    PageSpeed (HTTPS roto, libs JS con CVE conocidos en
    best_practices/security). Una performance baja o un SEO mediocre
    NO son motivo de descarte salvo que el prompt lo pidiera
    explícitamente.

  · PROFESIONALISMO (peso medio). La web tiene una estructura mínima
    de negocio activo: navegación con secciones reales, algún H1/H2
    informativo, contenido en el body, footer con datos legales o
    secciones tipo "Contacto / Sobre nosotros / Servicios". DESCARTA
    si parece un dominio aparcado, una landing vacía de plantilla,
    un sitio "Coming soon", un error masivo o una página de redirección
    a un marketplace.

REGLA ANTI-BLOQUEO (CRUCIAL)
Este filtro corre dentro de un software automatizado. Si te pones
demasiado estricto el sistema se quedará sin dominios y fallará. En
casos AMBIGUOS — encaja "más o menos" y el sitio se ve normal — la
respuesta correcta es "SI". Reserva el "NO" para los casos en los que
una persona razonable también lo descartaría.

REGLA DE ORO DE SALIDA — SIN EXCEPCIONES
Tu respuesta debe ser EXACTAMENTE una palabra: "SI" o "NO".
Está prohibido añadir explicaciones, comillas, puntuación,
comentarios, traducciones o cualquier otro carácter.
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
            f"{relax_level}). El pipeline lleva tiempo sin encontrar "
            "dominios suficientes — sé MÁS PERMISIVO: responde NO solo "
            "si la web es CLARAMENTE irrelevante para el prompt o tiene "
            "problemas técnicos GRAVES. En caso de duda, responde SI."
        )
    user_msg = _build_user_prompt(user_prompt, domain, html_markdown,
                                  tech_summary, ps_summary)

    try:
        # La validación NO es JSON — desactivamos json_mode para no meter
        # el system prompt de "responde solo JSON" que confundiría al
        # modelo. Cadena de fallback: TASK_VALIDATION
        # (Cerebras 8B → Groq 70B → Groq 8B → Gemini → User Own).
        response = complete_for_task(
            TASK_VALIDATION,
            prompt=user_msg,
            system_prompt=system,
            json_mode=False,
        )
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
