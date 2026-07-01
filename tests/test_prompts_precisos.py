"""
Tests para las mejoras de precisión en interpretación de prompt
y generación de queries.

Cubre:
  · Flujo secuencial: análisis → queries con contexto.
  · El bloque de contexto del análisis se serializa y se pasa al Query
    Strategist.
  · Post-procesado: dedup near-duplicados, filtra must_not, quita
    prefijos de instrucción residuales.
  · El sector_keywords del análisis se propaga al post-procesado.
  · Producto: el prompt mejorado mantiene las garantías mínimas
    (devuelve una sola línea, sin comillas, sin prefijos).
"""
from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, "/workspace")

from src.services.providers.base_provider import AIResponse  # noqa: E402
import src.services.ai_manager as ai_manager_module  # noqa: E402
from src.services.ai_interpreter import (  # noqa: E402
    _format_analysis_block, _extract_sector_keywords,
    _dedupe_keep_order, _normalize_query, _query_violates_must_not,
    _post_process_queries, _strip_wrapping_quotes, _clean_queries,
    AIInterpreter,
)
from src.services.task_chains import (  # noqa: E402
    TASK_PROMPT_ANALYSIS, TASK_QUERY_GENERATION,
)


# ─────────────────────────────────────────────────────────────────────
#  Helpers atómicos
# ─────────────────────────────────────────────────────────────────────

class TestFormatAnalysisBlock(unittest.TestCase):
    def test_handles_none_and_empty(self):
        self.assertIn("no disponible", _format_analysis_block(None))
        # dict vacío {} también cae como falsy → placeholder de no-disponible
        self.assertIn("no disponible", _format_analysis_block({}))

    def test_dict_with_only_irrelevant_fields_marks_empty(self):
        # Si el dict tiene valores pero ninguno es útil, devuelve "vacío"
        out = _format_analysis_block({"prompt_depurado": "",
                                       "business_type": None,
                                       "location": {}})
        self.assertIn("vacío", out)

    def test_includes_main_fields(self):
        block = _format_analysis_block({
            "prompt_depurado": "x",
            "business_type": "ecommerce",
            "location": {"country": "ES", "city": "Barcelona"},
            "must_have": ["Shopify"],
            "must_not": ["Wix"],
            "search_strategy": "footprint Shopify + slang ebike",
            "sector_keywords": ["ebike", "mtb"],
        })
        self.assertIn("business_type", block)
        self.assertIn("Barcelona", block)
        self.assertIn("Shopify", block)
        self.assertIn("Wix", block)
        self.assertIn("search_strategy", block)
        self.assertIn("sector_keywords", block)


class TestExtractSectorKeywords(unittest.TestCase):
    def test_none_returns_empty(self):
        self.assertEqual(_extract_sector_keywords(None), [])

    def test_normalizes_strings(self):
        out = _extract_sector_keywords({"sector_keywords": [" ebike ", "MTB", 42, ""]})
        self.assertEqual(out, ["ebike", "MTB"])


class TestDedupeKeepOrder(unittest.TestCase):
    def test_preserves_first_occurrence(self):
        self.assertEqual(_dedupe_keep_order(["A", "b", "a", "C", "B"]),
                         ["A", "b", "C"])

    def test_handles_empty(self):
        self.assertEqual(_dedupe_keep_order([]), [])
        self.assertEqual(_dedupe_keep_order(None), [])


class TestNormalizeQuery(unittest.TestCase):
    def test_same_canonical_for_paraphrases(self):
        a = _normalize_query('tienda online de zapatos')
        b = _normalize_query('tienda online zapatos')
        c = _normalize_query('intitle:zapatos tienda online')
        self.assertEqual(a, b)
        self.assertEqual(a, c)

    def test_different_intents_stay_distinct(self):
        a = _normalize_query('tienda zapatos Madrid')
        b = _normalize_query('tienda zapatos Barcelona')
        self.assertNotEqual(a, b)

    def test_operators_dropped(self):
        a = _normalize_query('intitle:"zapatos" site:.es')
        b = _normalize_query('zapatos')
        # 'es' < 3 chars así que se filtra; a queda solo 'zapatos'
        self.assertEqual(a, b)


class TestStripWrappingQuotes(unittest.TestCase):
    """
    Regresión de un bug real en producción: la implementación anterior
    (``s.strip("`'\\"")``) quitaba comillas de los EXTREMOS sin
    comprobar que estuvieran balanceadas. Esto corrompía queries de
    Google que empiezan y/o terminan con una frase exacta legítima,
    dejando un número IMPAR de comillas → Serper las rechazaba con
    400 Bad Request (así se perdía la mayoría de las queries del
    fallback local reportadas por el usuario en logs de producción).
    """

    def test_real_world_broken_query_stays_intact(self):
        """La query EXACTA de los logs de producción que causaba el 400."""
        q = ('"Agencia de marketing digital" precio contacto '
             '-"qué es" -"guía" -wikipedia -blog -"artículo"')
        fixed = _strip_wrapping_quotes(q)
        # No se debe tocar: no es un wrapping superfluo de toda la
        # query, son frases exactas legítimas de sintaxis Google.
        self.assertEqual(fixed, q)
        self.assertEqual(fixed.count('"') % 2, 0, "comillas desbalanceadas")

    def test_query_wrapped_entirely_gets_unwrapped(self):
        """Caso legítimo: el LLM envuelve TODA la query en comillas
        superfluas — esto SÍ se debe limpiar."""
        self.assertEqual(
            _strip_wrapping_quotes('"tienda de zapatos online Madrid"'),
            "tienda de zapatos online Madrid",
        )

    def test_backtick_wrapped_gets_unwrapped(self):
        self.assertEqual(
            _strip_wrapping_quotes("`tienda de zapatos`"),
            "tienda de zapatos",
        )

    def test_single_quote_wrapped_gets_unwrapped(self):
        self.assertEqual(
            _strip_wrapping_quotes("'tienda de zapatos'"),
            "tienda de zapatos",
        )

    def test_multiple_exact_phrases_never_touched(self):
        q = '"frase uno" y también "frase dos" al final'
        self.assertEqual(_strip_wrapping_quotes(q), q)

    def test_query_starting_with_quote_but_no_closing_quote_untouched(self):
        q = '"solo abre sin cerrar en Google'
        # Empieza con comilla pero NO termina con comilla → no debe tocarse.
        self.assertEqual(_strip_wrapping_quotes(q), q)

    def test_plain_query_untouched(self):
        q = "tienda de zapatos en Madrid"
        self.assertEqual(_strip_wrapping_quotes(q), q)

    def test_post_process_never_produces_odd_quote_count(self):
        """Verificación end-to-end: ninguna query que salga de
        _post_process_queries puede tener comillas desbalanceadas."""
        real_queries = [
            '"Agencia de marketing digital" precio contacto -"qué es" -"guía" -wikipedia -blog -"artículo"',
            'Agencia de marketing digital empresa servicios "sobre nosotros"',
            'Agencia de marketing digital "solicitar presupuesto" OR "pedir información"',
            'Agencia de marketing digital site:.com OR site:.es -"qué es"',
            'intitle:"Agencia de marketing digital" contacto',
            'Agencia de marketing digital "nuestros servicios" OR "our services"',
            'Agencia de marketing digital pricing OR "get a quote" OR "free trial"',
            'inurl:agencia Agencia de marketing digital',
            'Agencia de marketing digital "trabaja con nosotros" OR "contact us"',
        ]
        out = _post_process_queries(real_queries)
        self.assertGreater(len(out), 0)
        for q in out:
            self.assertEqual(
                q.count('"') % 2, 0,
                f"Query con comillas desbalanceadas tras post-process: {q!r}",
            )

    def test_clean_queries_never_produces_odd_quote_count(self):
        """Mismo chequeo para _clean_queries (usado en la ruta de la IA)."""
        raw = [
            '"tienda online" "añadir al carrito" Barcelona',
            'intitle:"bicicletas eléctricas" contacto',
        ]
        out = _clean_queries(raw)
        for q in out:
            self.assertEqual(q.count('"') % 2, 0)


class TestMustNotEnforcement(unittest.TestCase):
    def test_positive_mention_violates(self):
        self.assertTrue(_query_violates_must_not(
            "powered by shopify", ["Shopify"]
        ))

    def test_explicit_exclusion_is_ok(self):
        self.assertFalse(_query_violates_must_not(
            "tienda online -shopify", ["Shopify"]
        ))

    def test_substring_does_not_trigger(self):
        # "shopifyguide" no es shopify; no debería disparar
        self.assertFalse(_query_violates_must_not(
            "tienda shopifyguide", ["Shopify"]
        ))

    def test_empty_must_not_passes_all(self):
        self.assertFalse(_query_violates_must_not("anything", []))
        self.assertFalse(_query_violates_must_not("anything", None))


class TestPostProcessQueries(unittest.TestCase):
    def test_full_pipeline(self):
        out = _post_process_queries(
            [
                "tienda online de zapatos",
                "tienda online zapatos",         # near-dup → eliminada
                "powered by shopify zapatos",    # must_not → eliminada
                "intitle:zapatos tienda online", # near-dup
                "Query 1: zapatos",              # prefijo instrucción
                "inurl:/shop zapatos online",    # OK, diferente
                "zapatos baratos Madrid",        # OK, diferente
                "x",                             # demasiado corta
            ],
            must_not=["Shopify"],
        )
        self.assertEqual(len(out), 3)
        for q in out:
            self.assertNotIn("shopify", q.lower())

    def test_caps_to_target_count(self):
        # Generamos 30 queries genuinamente DIFERENTES (token único en
        # cada una) para que el dedup no las colapse y el cap funcione.
        sectores = ["zapatos", "camisas", "pantalones", "vestidos",
                    "abrigos", "joyas", "relojes", "bolsos", "perfumes",
                    "gorras", "calcetines", "ropa", "moda", "deporte",
                    "lujo", "premium", "vintage", "boho", "minimalista",
                    "urbano", "infantil", "bebé", "niño", "adulto",
                    "trabajo", "casa", "exterior", "interior", "fiesta",
                    "noche"]
        many = [f"tienda online {s} barcelona" for s in sectores]
        self.assertEqual(len(many), 30)
        out = _post_process_queries(many, target_count=15)
        self.assertEqual(len(out), 15)

    def test_returns_what_there_is_when_less(self):
        # Si tras filtrar solo quedan 4, devolvemos 4 — no padding.
        out = _post_process_queries(
            ["q1 zapatos", "q2 zapatillas", "q3 calzado", "q4 tenis"],
            target_count=15,
        )
        self.assertEqual(len(out), 4)

    def test_must_not_with_explicit_minus_passes(self):
        # Si la query usa "-shopify" como operador, NO debe filtrarse:
        # es una exclusión legítima de Google.
        out = _post_process_queries(
            ["tienda zapatos online -shopify"],
            must_not=["Shopify"],
        )
        self.assertEqual(len(out), 1)


# ─────────────────────────────────────────────────────────────────────
#  Flujo secuencial: analysis → queries con contexto
# ─────────────────────────────────────────────────────────────────────

class TestSequentialFlow(unittest.TestCase):
    def setUp(self):
        ai_manager_module._task_managers.clear()
        self._patches = []

    def tearDown(self):
        for p in self._patches:
            p.stop()
        ai_manager_module._task_managers.clear()

    def _patch(self, fake):
        p1 = patch("src.services.ai_interpreter.complete_for_task", side_effect=fake)
        p2 = patch("src.services.precision_routers.complete_for_task", side_effect=fake)
        self._patches.extend([p1, p2])
        p1.start(); p2.start()

    def test_queries_call_receives_analysis_context(self):
        """El segundo prompt (queries) DEBE incluir el contexto del
        análisis, no el placeholder antiguo."""
        captured = []

        def fake(task, prompt, system_prompt="", *, json_mode=True):
            captured.append({"task": task, "prompt": prompt})
            if task == TASK_PROMPT_ANALYSIS:
                # Router (Tech / PageSpeed) → respondemos default OFF.
                if "routing intelligence" in system_prompt or "Tech Stack" in system_prompt or "PageSpeed" in system_prompt:
                    return AIResponse(
                        text='{"use_scanner":false,"use_pagespeed":false,"confidence":"low","reason":"x"}',
                        provider="Groq", model="m",
                    )
                # Analyst → JSON con must_have/must_not + sector_keywords
                return AIResponse(
                    text=(
                        '{"prompt_depurado":"tienda ebike Barcelona Shopify, no Wix",'
                        '"business_type":"ecommerce",'
                        '"product_category":"ebikes",'
                        '"service_type":null,'
                        '"niche":"movilidad urbana",'
                        '"location":{"country":"ES","region":"Cataluña","city":"Barcelona"},'
                        '"target_audience":"B2C",'
                        '"language":"es",'
                        '"must_have":["Shopify"],'
                        '"must_not":["Wix"],'
                        '"validation_indicators":["añadir al carrito"],'
                        '"exclusion_indicators":["qué es"],'
                        '"confidence":0.9,'
                        '"analysis_notes":"ok",'
                        '"search_strategy":"footprint Shopify + slang ebike",'
                        '"sector_keywords":["ebike","mtb electrica"]}'
                    ),
                    provider="Groq", model="m",
                )
            if task == TASK_QUERY_GENERATION:
                return AIResponse(
                    text='{"search_queries":["ebike tienda Barcelona",'
                          '"powered by Shopify ebike",'
                          '"\\"asistencia eléctrica\\" tienda Cataluña",'
                          '"inurl:/products/ ebike Barcelona",'
                          '"ebike checkout España -wikipedia"]}',
                    provider="SambaNova", model="m",
                )
            return AIResponse(text="", provider="none", success=False)

        self._patch(fake)

        intent = AIInterpreter().interpret(
            "tienda online de ebikes en Barcelona con Shopify, sin Wix",
            precision_routing=False,
        )

        # Las queries del intent vienen del array que devolvió la IA,
        # tras post-procesado (sin la que mencione Wix; ninguna aquí
        # menciona Wix por lo que esperamos las 5).
        self.assertGreaterEqual(len(intent.search_queries), 4)
        for q in intent.search_queries:
            # Ninguna debe mencionar Wix en positivo
            self.assertNotIn("wix", q.lower())

        # Verificamos que el SEGUNDO call (queries) recibió el contexto
        # del análisis: el prompt enviado debe contener "Shopify" (el
        # must_have del análisis) en el bloque de contexto.
        queries_calls = [c for c in captured if c["task"] == TASK_QUERY_GENERATION]
        self.assertEqual(len(queries_calls), 1)
        qprompt = queries_calls[0]["prompt"]
        self.assertIn("must_have", qprompt)
        self.assertIn("Shopify", qprompt)
        self.assertIn("ebike", qprompt.lower())  # sector_keywords
        self.assertIn("Barcelona", qprompt)
        # Y NO debe llevar el placeholder antiguo ("paralelo — no disponible")
        self.assertNotIn("en paralelo", qprompt.lower())

    def test_post_process_drops_must_not_violators_from_ia_output(self):
        """Si la IA de queries por error mete una query que viola
        must_not, el post-procesado la elimina."""
        def fake(task, prompt, system_prompt="", *, json_mode=True):
            if task == TASK_PROMPT_ANALYSIS:
                if "routing intelligence" in system_prompt or "Tech Stack" in system_prompt or "PageSpeed" in system_prompt:
                    return AIResponse(
                        text='{"use_scanner":false,"use_pagespeed":false}',
                        provider="X", model="m",
                    )
                return AIResponse(
                    text=(
                        '{"prompt_depurado":"x","business_type":"ecommerce",'
                        '"product_category":null,"service_type":null,'
                        '"niche":null,"location":{},"target_audience":null,'
                        '"language":"es",'
                        '"must_have":[],"must_not":["Shopify"],'
                        '"validation_indicators":[],"exclusion_indicators":[],'
                        '"confidence":0.5,"analysis_notes":"","search_strategy":"",'
                        '"sector_keywords":[]}'
                    ),
                    provider="X", model="m",
                )
            if task == TASK_QUERY_GENERATION:
                # La IA mete UNA query que viola must_not (Shopify en
                # positivo). El post-procesado la debe filtrar.
                return AIResponse(
                    text='{"search_queries":[' \
                         '"tienda online de zapatos",' \
                         '"powered by shopify zapatos",' \
                         '"woocommerce zapatos España",' \
                         '"checkout zapatos online"' \
                         ']}',
                    provider="X", model="m",
                )
            return AIResponse(text="", provider="none", success=False)

        self._patch(fake)
        intent = AIInterpreter().interpret("tienda de zapatos sin shopify",
                                            precision_routing=False)
        self.assertGreater(len(intent.search_queries), 0)
        for q in intent.search_queries:
            self.assertNotIn("shopify", q.lower(),
                             f"Query no debería mencionar Shopify: {q}")
        # Esperamos 3 (woocommerce, tienda zapatos, checkout)
        self.assertEqual(len(intent.search_queries), 3)

    def test_indicators_are_deduplicated(self):
        def fake(task, prompt, system_prompt="", *, json_mode=True):
            if task == TASK_PROMPT_ANALYSIS:
                if "routing intelligence" in system_prompt or "Tech Stack" in system_prompt or "PageSpeed" in system_prompt:
                    return AIResponse(text='{"use_scanner":false,"use_pagespeed":false}',
                                       provider="X", model="m")
                return AIResponse(
                    text=(
                        '{"prompt_depurado":"x","business_type":"otro",'
                        '"product_category":null,"service_type":null,'
                        '"niche":null,"location":{},"target_audience":null,'
                        '"language":"es","must_have":[],"must_not":[],'
                        '"validation_indicators":['
                        '"añadir al carrito","Añadir al carrito","checkout","CHECKOUT"],'
                        '"exclusion_indicators":["qué es","Qué Es","wikipedia"],'
                        '"confidence":0.5,"analysis_notes":"","search_strategy":"",'
                        '"sector_keywords":[]}'
                    ),
                    provider="X", model="m",
                )
            return AIResponse(text='{"search_queries":["x y z","a b c"]}',
                               provider="X", model="m")

        self._patch(fake)
        intent = AIInterpreter().interpret("foo", precision_routing=False)
        # 4 originales (añadir x2, checkout x2) → 2 únicos
        self.assertEqual(len(intent.validation_indicators), 2)
        # 3 originales (qué es x2, wikipedia) → 2 únicos
        self.assertEqual(len(intent.exclusion_indicators), 2)


if __name__ == "__main__":
    unittest.main()
