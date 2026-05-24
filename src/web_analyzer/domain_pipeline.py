"""
DomainPipeline - Arquitectura de Workers Autónomos por Dominio

Cada worker toma un dominio candidato de la cola y ejecuta el ciclo
COMPLETO sobre ese dominio antes de tomar el siguiente. Si el dominio
falla cualquier comprobación obligatoria, el worker lo descarta
(silenciosamente, sin guardarlo) y pide otro de la cola hasta llegar a
`max_results`.

Modo RÁPIDO (fast_mode=True):
  Fase 1 → Validación de tipo de web (snippet + Schema.org).
  Fase 2 (lite) → Comprobación rápida de "está viva" (httpx + regex):
                  HTTP < 400, HTML mínimo, no parking, no error genérico,
                  contenido textual real. Si NO está viva → descarte y
                  el worker busca otro dominio.
  Fase 3 → Extracción de contactos (Katana). Independientemente de si
           se encuentra todo lo que el usuario pidió o no, el resultado
           se devuelve al frontend.

Modo PRECISIÓN (fast_mode=False):
  Fase 1 → Igual.
  Fase 2 → Auditoría completa: HTML con httpx + BS4, tech scanner
           (Wappalyzer + ADN) y/o PageSpeed según decida la IA, y
           veredicto final con un auditor IA (SI/NO).
  Fase 3 → Extracción de contactos (Katana + Playwright). DESPUÉS de
           la extracción se comprueba que TODOS los campos pedidos
           (`extract_fields`) estén presentes; si falta alguno se
           descarta el dominio y el worker busca otro.

3 workers en paralelo. Integra ResourceThrottle para escalar dinámicamente:
  - El número de pestañas por worker lo dicta throttle.tabs en tiempo real
  - Si throttle.workers < workers_activos, los workers excedentes esperan
    (no toman nuevos dominios) hasta que el nivel suba
  - Si throttle.should_stop → el pipeline termina de forma segura

Sistema de degradación progresiva (precisión):
  Si la Fase 2 lleva mucho tiempo sin dejar pasar dominios suficientes,
  el `PrecisionDegradation` compartido va subiendo de nivel para
  relajar al juez IA y, eventualmente, desactivar PageSpeed.
"""
import threading
import queue
import time
from typing import List, Dict, Any, Optional, Callable

from src.domain_validator.validator import DomainValidator, ValidationResult
from src.web_analyzer.hybrid_extractor import HybridContactExtractor
# sales_triggers removed from pipeline — runs in domain_analyzer (deep audit mode)
from src.utils.resource_throttle import ResourceThrottle
from src.web_analyzer.precision.precision_phase import (
    PrecisionPhase,
    PrecisionDegradation,
)
from src.web_analyzer.quick_check import is_alive as quick_is_alive

# Número máximo de workers (el throttle puede reducirlo dinámicamente)
NUM_WORKERS = 3

# Labels de fase para la UI
PHASE_LABELS = {
    "idle":       "En espera",
    "phase1":     "Fase 1 · Validando",
    "phase2":     "Fase 2 · Precisión",
    "phase2_fast":"Fase 2 · Comprobación rápida",
    "phase3":     "Fase 3 · Extrayendo contacto",
    "done":       "Completado",
    "rejected":   "Descartado",
    "error":      "Error",
}


class WorkerState:
    """Estado público de un worker individual (thread-safe)."""

    def __init__(self, worker_id: int):
        self.worker_id = worker_id
        self._lock = threading.Lock()
        self._phase = "idle"
        self._domain = ""
        self._detail = ""

    def update(self, phase: str, domain: str = "", detail: str = ""):
        with self._lock:
            self._phase = phase
            self._domain = domain
            self._detail = detail

    def to_dict(self) -> Dict[str, str]:
        with self._lock:
            return {
                "worker_id": self.worker_id,
                "phase": self._phase,
                "phase_label": PHASE_LABELS.get(self._phase, self._phase),
                "domain": self._domain,
                "detail": self._detail,
            }


class DomainPipelineOrchestrator:
    """
    Gestiona la cola de dominios candidatos y los 3 workers autónomos.

    Uso:
        orchestrator = DomainPipelineOrchestrator(
            analysis=analysis,
            tech_requirements=tech_requirements,
            extract_fields=['email'],
            fast_mode=False,
            on_result=callback_cuando_llega_resultado,
            on_progress=callback_progreso_global,
        )
        results = orchestrator.run(search_results)
    """

    def __init__(
        self,
        analysis,
        tech_requirements: Dict[str, Any],
        extract_fields: List[str],
        fast_mode: bool = False,
        max_results: int = 20,
        on_result: Optional[Callable] = None,
        on_progress: Optional[Callable] = None,
        throttle: Optional[ResourceThrottle] = None,
    ):
        self.analysis = analysis
        self.tech_requirements = tech_requirements
        self.extract_fields = extract_fields
        self.fast_mode = fast_mode
        self.max_results = max_results
        self.on_result = on_result        # callback(domain_info)  cuando un dominio termina
        self.on_progress = on_progress    # callback(worker_states, completed, total)
        self.throttle = throttle          # ResourceThrottle o None

        # NOTA: la Fase 2 (Análisis de Tecnologías) se ha eliminado por
        # completo del pipeline. Los filtros de tecnología no se evalúan
        # aquí hasta que se reescriba el módulo desde cero.

        # Worker states (uno por worker, índice 0-2)
        self.worker_states: List[WorkerState] = [
            WorkerState(i + 1) for i in range(NUM_WORKERS)
        ]

        # Cola de trabajo: cada item es un SearchResult
        self._queue: queue.Queue = queue.Queue()

        # Resultados finales (thread-safe via lock)
        self._results: List[Dict[str, Any]] = []
        self._results_lock = threading.Lock()

        # Contadores
        self._total = 0
        self._completed = 0
        self._completed_lock = threading.Lock()

        # Señal de parada anticipada cuando ya tenemos suficientes resultados
        self._enough = threading.Event()

        # Validador compartido (stateless, seguro entre threads)
        self._validator = DomainValidator(use_wappalyzer=False, use_pagespeed=False)

        # Sistema de degradación progresiva de la Fase 2 (solo precisión).
        # Compartido por todos los workers; cuenta el tiempo que llevamos
        # sin dejar pasar a un dominio para subir el nivel y aflojar.
        self._precision_degradation: Optional[PrecisionDegradation] = (
            None if self.fast_mode else PrecisionDegradation()
        )

    # ------------------------------------------------------------------
    # Punto de entrada público
    # ------------------------------------------------------------------

    def run(self, search_results: List[Any]) -> List[Dict[str, Any]]:
        """
        Lanza los 3 workers y procesa todos los search_results.
        Bloquea hasta que todos los workers terminan.
        Returns lista de dominios validados y con contacto extraído.
        """
        self._total = len(search_results)

        # Llenar la cola
        for sr in search_results:
            self._queue.put(sr)

        # Señal de fin para cada worker (un None por worker)
        for _ in range(NUM_WORKERS):
            self._queue.put(None)

        # Lanzar workers en threads separados
        threads = []
        for i in range(NUM_WORKERS):
            t = threading.Thread(
                target=self._worker_loop,
                args=(i,),
                daemon=True,
                name=f"DomainWorker-{i+1}"
            )
            t.start()
            threads.append(t)

        # Esperar a todos
        for t in threads:
            t.join()

        # Ordenar por confianza descendente y CAPAR EXACTAMENTE a
        # max_results. Si por una race condition entre workers se
        # quedaron 1-2 dominios extra al acumular (3 workers terminando
        # a la vez justo cuando el contador llegaba al límite), aquí los
        # descartamos quedándonos con los mejores por confidence.
        with self._results_lock:
            self._results.sort(key=lambda x: x.get("confidence", 0), reverse=True)
            return list(self._results[: self.max_results])

    # ------------------------------------------------------------------
    # Bucle principal de cada worker
    # ------------------------------------------------------------------

    def _worker_loop(self, worker_idx: int):
        """
        Ciclo autónomo del worker: toma dominios de la cola uno a uno
        y ejecuta el pipeline completo para cada uno.

        Integración con ResourceThrottle:
        - Si throttle.should_stop → señaliza _enough y termina inmediatamente
        - Si worker_idx >= throttle.workers → pausa (sin tomar nuevos dominios)
          hasta que el nivel del throttle suba y libere este índice de worker
        - El número de pestañas lo consulta tab_count_fn() en cada llamada
          a HybridContactExtractor (valor dinámico en tiempo real)
        """
        state = self.worker_states[worker_idx]
        state.update("idle", "", "Esperando dominio...")

        # tab_count_fn: consultada en cada dominio, retorna el límite actual
        def tab_count_fn():
            if self.throttle:
                return self.throttle.tabs
            return 3

        # Cada worker tiene su propio extractor Playwright (instancia independiente)
        extractor = HybridContactExtractor(
            max_workers=1,
            fast_mode=self.fast_mode,
            tab_count_fn=tab_count_fn,
        )

        while True:
            # ── Comprobar parada total del throttle ──────────────────────
            if self.throttle and self.throttle.should_stop:
                state.update("idle", "", "Detenido por throttle (Nivel 5)")
                self._enough.set()
                break

            # ── Pausa si el throttle ha reducido workers por debajo de nuestro índice
            # (worker_idx es 0-based; throttle.workers es cuántos activos se permiten)
            if self.throttle and (worker_idx >= self.throttle.workers):
                state.update("idle", "", f"En pausa (throttle: {self.throttle.workers} workers activos)")
                time.sleep(1.0)
                continue

            try:
                search_result = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            # None = señal de fin
            if search_result is None:
                break

            # ¿Ya tenemos suficientes resultados?
            if self._enough.is_set():
                self._queue.task_done()
                with self._completed_lock:
                    self._completed += 1
                self._notify_progress()
                continue

            domain = getattr(search_result, 'domain', str(search_result))
            self._process_domain(search_result, domain, state, extractor, worker_idx)

            self._queue.task_done()

        state.update("idle", "", "")

    # ------------------------------------------------------------------
    # Pipeline por dominio (4 fases)
    # ------------------------------------------------------------------

    def _process_domain(
        self,
        search_result,
        domain: str,
        state: WorkerState,
        extractor: HybridContactExtractor,
        worker_idx: int,
    ):
        # ── FASE 1: Validación de tipo de web ────────────────────────
        # Modo resiliente: el validador etiqueta y puntúa pero NUNCA descarta.
        # Un score bajo o un error se registran en domain_info y el dominio
        # llega al frontend con aviso "Análisis incompleto".
        state.update("phase1", domain, "Analizando HTML + Schema.org...")
        self._notify_progress()

        score = 0.0
        analysis_ok = False
        validation_notes = []

        try:
            validation = self._validator.validate(search_result, self.analysis)
            score = validation.confidence_score
            analysis_ok = validation.analysis_complete
            if not analysis_ok and validation.error_message:
                validation_notes.append(f"Análisis incompleto: {validation.error_message[:60]}")
                print(f"[Pipeline] ⚠ {domain} — análisis incompleto (score={score:.0f}): {validation.error_message[:80]}")
            else:
                print(f"[Pipeline] {'✓' if score >= 60 else '~'} {domain} — score={score:.0f}")
        except Exception as e:
            validation_notes.append(f"Error en validación: {str(e)[:60]}")
            print(f"[Pipeline] ⚠ {domain} — excepción en validación: {e}")
            # Crear objeto mínimo para continuar
            validation = ValidationResult(domain=domain, url=getattr(search_result, 'url', ''))
            validation.page_title = getattr(search_result, 'title', '')

        # Score filter: discard domains below 60 (fast pipeline, quality over quantity)
        MIN_RELEVANCE_SCORE = 60
        if score < MIN_RELEVANCE_SCORE:
            print(f"[Pipeline] ✗ {domain} — score {score:.0f} < {MIN_RELEVANCE_SCORE}, descartado")
            state.update("rejected", domain, f"Score bajo ({score:.0f} < {MIN_RELEVANCE_SCORE})")
            self._mark_completed()
            return

        # Construir domain_info
        schema_info = {}
        if getattr(validation, 'schema_data', None):
            try:
                schema_info = {
                    "types":        validation.schema_data.get("types", [])[:3],
                    "is_ecommerce": validation.schema_data.get("is_ecommerce", False),
                    "is_service":   validation.schema_data.get("is_service_business", False),
                    "has_products": validation.schema_data.get("has_products", False),
                    "product_count":validation.schema_data.get("product_count", 0),
                    "has_reviews":  validation.schema_data.get("has_reviews", False),
                    "rating":       validation.schema_data.get("aggregate_rating"),
                }
            except Exception:
                pass

        title = getattr(validation, 'page_title', '') or getattr(search_result, 'title', '') or ""
        domain_url = getattr(validation, 'url', '') or getattr(search_result, 'url', '')
        domain_name = getattr(validation, 'domain', '') or domain

        domain_info: Dict[str, Any] = {
            "domain":            domain_name,
            "url":               domain_url,
            "confidence":        round(score, 1),
            "title":             title[:60] + "..." if len(title) > 60 else title,
            "reasons":           getattr(validation, 'validation_reasons', [])[:3],
            "tech":              [],
            "tech_profile":      None,
            "is_ecommerce":      False,
            "schema":            schema_info,
            "tech_match":        False,
            "contact":           None,
            "analysis_complete": analysis_ok,
            "analysis_notes":    validation_notes,
        }

        # ── FASE 2 LITE: Solo en modo rápido ──────────────────────────
        # Comprobación ultra-ligera de "está viva" con httpx + regex.
        # Sin Playwright, sin IA, sin Wappalyzer. Si la web responde
        # con error, está parqueada o vacía → el worker descarta este
        # dominio y va a por otro (no se guarda nada). Si pasa la
        # comprobación, sigue a la Fase 3 y SIEMPRE se entrega el
        # resultado al frontend, encuentre lo que encuentre o no.
        if self.fast_mode:
            state.update("phase2_fast", domain, "Comprobando que la web esté viva...")
            self._notify_progress()
            try:
                check = quick_is_alive(domain_url)
                domain_info["quick_check"] = check.to_dict()
            except Exception as e:
                # Cualquier error en la comprobación: no bloqueamos el
                # pipeline. Tratamos como "viva" para no perder el dominio
                # por un fallo nuestro y dejamos que la Fase 3 lo intente.
                check = None
                domain_info["analysis_notes"].append(
                    f"QuickCheck error inesperado: {str(e)[:60]}"
                )
                print(f"[Pipeline] ⚠ {domain} — excepción en QuickCheck: {e}")

            if check is not None and not check.alive:
                print(
                    f"[Pipeline] ✗ {domain} — QuickCheck falló "
                    f"({check.reason}, status={check.status_code})"
                )
                state.update("rejected", domain, f"Web rota: {check.reason[:60]}")
                self._mark_completed()
                return

        # ── FASE 2: Solo en modo precisión ────────────────────────────
        # Descarga el HTML con httpx (sin Playwright), construye un
        # contexto en capas con BeautifulSoup, ejecuta opcionalmente el
        # Tech Scanner (Wappalyzer + ADN) y/o PageSpeed Insights según
        # decidió la IA en el routing, y le pide a un auditor IA un
        # veredicto SI/NO. Si el veredicto es NO el dominio se descarta.
        if not self.fast_mode:
            state.update("phase2", domain, "Auditoría IA · HTML + tech + PageSpeed...")
            self._notify_progress()

            try:
                def _on_stage(stage_name: str, message: str):
                    state.update("phase2", domain, message)
                    self._notify_progress()

                phase2 = PrecisionPhase(
                    intent=self.analysis,
                    degradation=self._precision_degradation,
                    on_stage=_on_stage,
                )
                phase2_result = phase2.run(domain_name, domain_url)
                domain_info["precision_phase"] = phase2_result.to_dict()
                # Anotaciones para el frontend
                if phase2_result.tech_findings:
                    domain_info["tech_profile"] = {
                        "all_techs":  (phase2_result.tech_findings.get("wappalyzer_all_techs") or [])[:15],
                        "categories": phase2_result.tech_findings.get("wappalyzer_categories") or {},
                        "confirmed":  phase2_result.tech_findings.get("technologies_confirmed") or {},
                        "footprint":  phase2_result.tech_findings.get("raw_footprint") or [],
                        "social":     phase2_result.tech_findings.get("social_profiles") or [],
                    }
                    domain_info["tech_match"] = bool(
                        phase2_result.tech_findings.get("all_targets_met")
                    )

                if not phase2_result.passed:
                    reason = (
                        phase2_result.error
                        or (phase2_result.verdict or {}).get("raw_response")
                        or "veredicto NO"
                    )
                    print(
                        f"[Pipeline] ✗ {domain} — Fase 2 falló "
                        f"(stage={phase2_result.stage_at_failure}): {str(reason)[:80]}"
                    )
                    state.update("rejected", domain, f"Fase 2: {str(reason)[:60]}")
                    self._mark_completed()
                    return
                else:
                    print(
                        f"[Pipeline] ✓ {domain} — Fase 2 OK "
                        f"(degrad={phase2_result.degradation_level}, "
                        f"ps_used={phase2_result.pagespeed_used})"
                    )
            except Exception as e:
                # En caso de error inesperado en la fase 2, no rompemos
                # el pipeline — anotamos y dejamos pasar (resiliencia).
                domain_info["analysis_notes"].append(
                    f"Fase 2 error inesperado: {str(e)[:60]}"
                )
                print(f"[Pipeline] ⚠ {domain} — excepción en Fase 2: {e}")

        # ── FASE 3: Extracción de contacto (resiliente) ───────────────
        if self.extract_fields:
            mode_label = "Katana (rápido)" if self.fast_mode else "Katana + Playwright"
            state.update("phase3", domain, mode_label)
            self._notify_progress()

            try:
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    extracted = loop.run_until_complete(
                        extractor.extract_all_parallel([domain_info], self.extract_fields)
                    )
                    if extracted:
                        domain_info = extracted[0]
                        if domain_info.get("contact"):
                            domain_info["contact"]["fields_requested"] = self.extract_fields
                finally:
                    loop.close()
                    asyncio.set_event_loop(None)
                    del loop
            except Exception as e:
                domain_info["contact"] = {
                    "email": None, "phone": None,
                    "all_emails": [], "all_phones": [],
                    "social_media": [], "extraction_success": False,
                    "extraction_method": "error",
                    "source": f"pipeline_error: {str(e)[:40]}",
                    "fields_requested": self.extract_fields,
                }
        else:
            domain_info["contact"] = None

        # ── Gate de completitud (SOLO modo precisión) ─────────────────
        # Tras la extracción, en modo precisión exigimos que TODOS los
        # campos pedidos por el usuario estén presentes; si falta alguno
        # descartamos el dominio y el worker va a buscar otro. En modo
        # rápido este gate NO se aplica: se devuelve siempre lo que
        # haya, completo o no.
        if (not self.fast_mode) and self.extract_fields:
            missing = self._missing_required_fields(
                domain_info.get("contact"), self.extract_fields
            )
            if missing:
                print(
                    f"[Pipeline] ✗ {domain} — modo preciso: faltan campos "
                    f"requeridos {missing}, descartado"
                )
                state.update(
                    "rejected", domain,
                    f"Faltan datos: {', '.join(missing)}"
                )
                self._mark_completed()
                return

        # ── Guardar resultado — siempre llega al frontend ─────────────
        state.update("done", domain, "")
        with self._results_lock:
            self._results.append(domain_info)
            count = len(self._results)

        # Liberar referencias a objetos de análisis ya no necesarios
        del validation, schema_info

        if self.on_result:
            try:
                self.on_result(domain_info)
            except Exception:
                pass

        if count >= self.max_results:
            self._enough.set()

        self._mark_completed()

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    def precision_degradation_status(self) -> Optional[Dict[str, Any]]:
        """Snapshot del estado del sistema de degradación. None si no aplica."""
        if self._precision_degradation is None:
            return None
        return self._precision_degradation.status_dict()

    @staticmethod
    def _missing_required_fields(
        contact: Optional[Dict[str, Any]],
        fields: List[str],
    ) -> List[str]:
        """
        Devuelve la lista de campos pedidos por el usuario que NO se
        han conseguido extraer. Si la lista está vacía, todos están
        presentes.

        El mapeo es:
          · 'email'  → contact['email'] no vacío
          · 'phone'  → contact['phone'] no vacío
          · 'social' → contact['social_media'] no vacío

        En modo precisión usamos esto para descartar dominios
        incompletos. En modo rápido no se aplica.
        """
        if not fields:
            return []
        if not contact:
            return list(fields)

        def _empty(value) -> bool:
            if value is None:
                return True
            if isinstance(value, str):
                return not value.strip()
            if isinstance(value, (list, tuple, dict)):
                return len(value) == 0
            return False

        missing: List[str] = []
        for field_name in fields:
            f = (field_name or "").strip().lower()
            if f == "email":
                if _empty(contact.get("email")):
                    missing.append("email")
            elif f == "phone":
                if _empty(contact.get("phone")):
                    missing.append("phone")
            elif f == "social":
                if _empty(contact.get("social_media")):
                    missing.append("social")
            else:
                if _empty(contact.get(f)):
                    missing.append(f)
        return missing

    def _mark_completed(self):
        with self._completed_lock:
            self._completed += 1
        self._notify_progress()

    def _notify_progress(self):
        if not self.on_progress:
            return
        with self._completed_lock:
            completed = self._completed
        states = [ws.to_dict() for ws in self.worker_states]
        try:
            self.on_progress(states, completed, self._total)
        except Exception:
            pass
