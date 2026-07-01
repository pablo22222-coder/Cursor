"""
Tests para:
  · Provider model override (un mismo provider sirve varios modelos).
  · UserOwnProvider (OpenAI-compatible, configurable por env vars).
  · Cadenas de fallback por tarea (TASK_PROMPT_ANALYSIS, ...).
  · AIManager con cadena custom: salto entre eslabones, ok, all-fail.
  · AIInterpreter ejecuta análisis + queries en paralelo y los ensambla.
  · ProductAnalyzer y el juez SI/NO usan la cadena correcta.

Sin red: usamos stubs de provider que se comportan como queramos.
"""
from __future__ import annotations

import sys
import os
import unittest
from unittest.mock import patch

sys.path.insert(0, "/workspace")

from src.services.providers.base_provider import (  # noqa: E402
    BaseProvider, AIResponse, ProviderError,
)
from src.services.providers.user_own_provider import UserOwnProvider  # noqa: E402
from src.services.providers.groq_provider import GroqProvider  # noqa: E402
from src.services.providers.cerebras_provider import CerebrasProvider  # noqa: E402
from src.services.providers.sambanova_provider import SambanovaProvider  # noqa: E402
from src.services.providers.gemini_provider import GeminiProvider  # noqa: E402
import src.services.ai_manager as ai_manager_module  # noqa: E402
from src.services.ai_manager import (  # noqa: E402
    AIManager, _ChainEntry, complete_for_task, get_ai_manager_for_task,
)
from src.services.task_chains import (  # noqa: E402
    TASK_PROMPT_ANALYSIS, TASK_QUERY_GENERATION, TASK_VALIDATION,
    PROMPT_ANALYSIS_CHAIN, QUERY_GENERATION_CHAIN, VALIDATION_CHAIN,
    get_chain, _env_model,
)


# ─────────────────────────────────────────────────────────────────────
#  Stubs reutilizables
# ─────────────────────────────────────────────────────────────────────

class _StubProvider(BaseProvider):
    """Provider falso configurable: éxito, error o excepción a voluntad."""
    name = "Stub"
    model = "stub-default"

    def __init__(self, *, name="Stub", default_model="stub-default",
                 available=True, behavior="ok",
                 status_code=429, text="OK"):
        self.name = name
        self.model = default_model
        self._available = available
        self._behavior = behavior
        self._status_code = status_code
        self._text = text
        self.calls = []   # registra cada llamada (model, prompt[:40])

    def is_available(self) -> bool:
        return self._available

    def complete(self, prompt, system_prompt="", *, model=None):
        effective = model or self.model
        self.calls.append({"model": effective, "prompt": prompt[:60]})
        if self._behavior == "provider_error":
            raise ProviderError(self.name, self._status_code, "stub")
        if self._behavior == "value_error":
            raise ValueError("stub-auth")
        if self._behavior == "network":
            raise ConnectionError("stub-net")
        if self._behavior == "unexpected":
            raise RuntimeError("stub-runtime")
        # behavior == "ok"
        return AIResponse(
            text=self._text, provider=self.name, model=effective,
            latency_ms=1.0, success=True,
        )


# ─────────────────────────────────────────────────────────────────────
#  Provider model override
# ─────────────────────────────────────────────────────────────────────

class TestProviderModelOverride(unittest.TestCase):
    def test_complete_uses_override_when_passed(self):
        s = _StubProvider(default_model="x", text="hola")
        r = s.complete("foo", "sys", model="y")
        self.assertEqual(r.model, "y")
        self.assertEqual(s.calls[-1]["model"], "y")

    def test_complete_uses_default_when_not_passed(self):
        s = _StubProvider(default_model="x", text="hola")
        r = s.complete("foo", "sys")
        self.assertEqual(r.model, "x")
        self.assertEqual(s.calls[-1]["model"], "x")


# ─────────────────────────────────────────────────────────────────────
#  UserOwnProvider
# ─────────────────────────────────────────────────────────────────────

class TestUserOwnProvider(unittest.TestCase):
    def setUp(self):
        self._saved = {
            k: os.environ.get(k)
            for k in ("USER_OWN_API_KEY", "USER_OWN_BASE_URL",
                       "USER_OWN_MODEL", "USER_OWN_PROVIDER_NAME")
        }

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_unavailable_without_key(self):
        os.environ.pop("USER_OWN_API_KEY", None)
        p = UserOwnProvider()
        self.assertFalse(p.is_available())

    def test_available_with_key(self):
        os.environ["USER_OWN_API_KEY"] = "x" * 20
        p = UserOwnProvider()
        self.assertTrue(p.is_available())

    def test_defaults_when_env_empty(self):
        os.environ["USER_OWN_API_KEY"] = "x" * 20
        os.environ.pop("USER_OWN_BASE_URL", None)
        os.environ.pop("USER_OWN_MODEL", None)
        os.environ.pop("USER_OWN_PROVIDER_NAME", None)
        p = UserOwnProvider()
        self.assertEqual(p._base_url, "https://api.openai.com/v1")
        self.assertEqual(p._model, "gpt-4o-mini")
        self.assertEqual(p._display_name, "UserOwn")

    def test_custom_endpoint(self):
        os.environ["USER_OWN_API_KEY"] = "x" * 20
        os.environ["USER_OWN_BASE_URL"] = "https://openrouter.ai/api/v1/"
        os.environ["USER_OWN_MODEL"] = "openrouter/auto"
        os.environ["USER_OWN_PROVIDER_NAME"] = "OpenRouter"
        p = UserOwnProvider()
        self.assertEqual(p._base_url, "https://openrouter.ai/api/v1")  # sin trailing /
        self.assertEqual(p._model, "openrouter/auto")
        self.assertEqual(p._display_name, "OpenRouter")

    def test_complete_posts_to_chat_completions(self):
        os.environ["USER_OWN_API_KEY"] = "x" * 20
        os.environ["USER_OWN_BASE_URL"] = "https://api.example.com/v1"
        os.environ["USER_OWN_MODEL"] = "gpt-4o-mini"

        captured = {}

        class _Resp:
            status_code = 200
            text = ""
            headers = {}
            def raise_for_status(self):
                return None
            def json(self):
                return {"choices": [{"message": {"content": "OK"}}]}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["body"] = json
            captured["headers"] = headers
            return _Resp()

        p = UserOwnProvider()
        with patch("src.services.providers.user_own_provider.requests.post",
                   side_effect=fake_post):
            r = p.complete("hola", "sys")

        self.assertTrue(r.success)
        self.assertEqual(captured["url"], "https://api.example.com/v1/chat/completions")
        self.assertEqual(captured["body"]["model"], "gpt-4o-mini")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer " + ("x" * 20))


# ─────────────────────────────────────────────────────────────────────
#  _env_model — regresión del bug "variable definida pero vacía"
#
#  Bug real reportado: el usuario copió .env.example (que deja los
#  *_MODEL en blanco a propósito, para usar los defaults) y las 3 IAs
#  murieron a la vez porque os.getenv(key, default) NO usa el default
#  cuando la variable existe pero está vacía — devuelve "".
#  Esto producía URLs rotas como
#  ".../models/:generateContent" (modelo vacío) en Gemini, y 404/400
#  en Groq/SambaNova con model="" en el body.
# ─────────────────────────────────────────────────────────────────────

class TestEnvModelFallback(unittest.TestCase):
    def setUp(self):
        self._saved = {}
        for k in ("TEST_MODEL_VAR",):
            self._saved[k] = os.environ.get(k)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_unset_variable_uses_default(self):
        os.environ.pop("TEST_MODEL_VAR", None)
        self.assertEqual(_env_model("TEST_MODEL_VAR", "default-model"),
                         "default-model")

    def test_empty_string_variable_uses_default(self):
        """El caso del bug real: variable PRESENTE pero vacía."""
        os.environ["TEST_MODEL_VAR"] = ""
        self.assertEqual(_env_model("TEST_MODEL_VAR", "default-model"),
                         "default-model")

    def test_whitespace_only_variable_uses_default(self):
        os.environ["TEST_MODEL_VAR"] = "   "
        self.assertEqual(_env_model("TEST_MODEL_VAR", "default-model"),
                         "default-model")

    def test_real_value_is_used_and_trimmed(self):
        os.environ["TEST_MODEL_VAR"] = "  custom-model-id  "
        self.assertEqual(_env_model("TEST_MODEL_VAR", "default-model"),
                         "custom-model-id")

    def test_no_dead_model_in_live_chains(self):
        """Guard-rail: los modelos que ya sabemos MUERTOS no deben
        colarse en las cadenas activas incluso si alguien los deja
        puestos en su .env por error de copy-paste antiguo."""
        from src.services.task_chains import (
            GROQ_LLAMA_70B, SAMBA_LLAMA_405B, GEMINI_FLASH,
        )
        dead_models = {
            "llama-3.1-70b-versatile",
            "Meta-Llama-3.1-405B-Instruct",
            "gemini-1.5-flash",
            "",  # el síntoma del bug: modelo vacío
        }
        for m in (GROQ_LLAMA_70B, SAMBA_LLAMA_405B, GEMINI_FLASH):
            self.assertNotIn(m, dead_models)
            self.assertTrue(m, "el modelo nunca debe quedar vacío")


# ─────────────────────────────────────────────────────────────────────
#  Cadenas por tarea — orden exacto pedido por el usuario
# ─────────────────────────────────────────────────────────────────────

class TestTaskChainsExactOrder(unittest.TestCase):
    """
    Verifica el ORDEN de proveedores por tarea (lo que pidió el usuario),
    usando las constantes de modelo de task_chains en vez de literales,
    para que estos tests no se rompan cuando un proveedor deprecie un
    modelo y actualicemos la constante.
    """

    def test_prompt_analysis_order(self):
        from src.services.task_chains import (
            GROQ_LLAMA_70B, SAMBA_LLAMA_405B, GEMINI_FLASH,
        )
        seq = [(s.provider_class.__name__, s.model) for s in PROMPT_ANALYSIS_CHAIN]
        self.assertEqual(seq, [
            ("GroqProvider",      GROQ_LLAMA_70B),
            ("SambanovaProvider", SAMBA_LLAMA_405B),
            ("GeminiProvider",    GEMINI_FLASH),
            ("UserOwnProvider",   None),
        ])

    def test_query_generation_order(self):
        from src.services.task_chains import (
            GROQ_LLAMA_70B, SAMBA_LLAMA_405B, GEMINI_FLASH,
        )
        seq = [(s.provider_class.__name__, s.model) for s in QUERY_GENERATION_CHAIN]
        self.assertEqual(seq, [
            ("SambanovaProvider", SAMBA_LLAMA_405B),
            ("GroqProvider",      GROQ_LLAMA_70B),
            ("GeminiProvider",    GEMINI_FLASH),
            ("UserOwnProvider",   None),
        ])

    def test_validation_order(self):
        from src.services.task_chains import (
            GROQ_LLAMA_70B, GROQ_LLAMA_8B, CEREBRAS_LLAMA_8B, GEMINI_FLASH,
        )
        seq = [(s.provider_class.__name__, s.model) for s in VALIDATION_CHAIN]
        self.assertEqual(seq, [
            ("CerebrasProvider", CEREBRAS_LLAMA_8B),
            ("GroqProvider",     GROQ_LLAMA_70B),
            ("GroqProvider",     GROQ_LLAMA_8B),
            ("GeminiProvider",   GEMINI_FLASH),
            ("UserOwnProvider",  None),
        ])

    def test_models_are_alive_not_decommissioned(self):
        """Guard-rail: ninguno de los modelos MUERTOS conocidos debe
        estar en las cadenas por defecto."""
        from src.services.task_chains import (
            GROQ_LLAMA_70B, GROQ_LLAMA_8B, SAMBA_LLAMA_405B,
            CEREBRAS_LLAMA_8B, GEMINI_FLASH,
        )
        dead = {
            "llama-3.1-70b-versatile",       # Groq, ene-2025
            "Meta-Llama-3.1-405B-Instruct",  # SambaNova, jun-2025
            "gemini-1.5-flash",              # Google, apagado (404)
        }
        for m in (GROQ_LLAMA_70B, GROQ_LLAMA_8B, SAMBA_LLAMA_405B,
                  CEREBRAS_LLAMA_8B, GEMINI_FLASH):
            self.assertNotIn(m, dead, f"Modelo muerto en uso: {m}")

    def test_get_chain_falls_back_to_analysis_on_unknown(self):
        self.assertIs(get_chain("unknown_task"), PROMPT_ANALYSIS_CHAIN)


# ─────────────────────────────────────────────────────────────────────
#  AIManager con cadena custom (stubs)
# ─────────────────────────────────────────────────────────────────────

class TestAIManagerFallback(unittest.TestCase):
    def _mk_manager(self, *entries):
        return AIManager(chain=list(entries), task_name="test")

    def test_first_step_succeeds(self):
        a = _StubProvider(name="A", text="ok-A")
        b = _StubProvider(name="B", text="ok-B")
        m = self._mk_manager(_ChainEntry(a), _ChainEntry(b))
        r = m.complete("hola")
        self.assertTrue(r.success)
        self.assertEqual(r.provider, "A")
        # B no se llama
        self.assertEqual(len(b.calls), 0)

    def test_first_skipped_when_unavailable(self):
        a = _StubProvider(name="A", available=False)
        b = _StubProvider(name="B", text="ok-B")
        m = self._mk_manager(_ChainEntry(a), _ChainEntry(b))
        r = m.complete("hola")
        self.assertTrue(r.success)
        self.assertEqual(r.provider, "B")

    def test_provider_error_jumps_to_next(self):
        a = _StubProvider(name="A", behavior="provider_error")
        b = _StubProvider(name="B", text="ok-B")
        m = self._mk_manager(_ChainEntry(a), _ChainEntry(b))
        r = m.complete("hola")
        self.assertTrue(r.success)
        self.assertEqual(r.provider, "B")

    def test_auth_error_disables_step(self):
        a = _StubProvider(name="A", behavior="value_error")
        b = _StubProvider(name="B", text="ok-B")
        m = self._mk_manager(_ChainEntry(a), _ChainEntry(b))
        m.complete("hola")
        # Segunda llamada: A ya está deshabilitado → va directo a B
        a.calls.clear(); b.calls.clear()
        r = m.complete("hola2")
        self.assertEqual(len(a.calls), 0)
        self.assertEqual(len(b.calls), 1)
        self.assertTrue(r.success)

    def test_all_fail_returns_unsuccess(self):
        a = _StubProvider(name="A", behavior="provider_error")
        b = _StubProvider(name="B", behavior="network")
        m = self._mk_manager(_ChainEntry(a), _ChainEntry(b))
        r = m.complete("hola")
        self.assertFalse(r.success)
        self.assertEqual(r.provider, "none")

    def test_chain_with_model_overrides_passes_them(self):
        a = _StubProvider(name="A", default_model="default")
        m = self._mk_manager(_ChainEntry(a, model="override-1"))
        r = m.complete("hola")
        self.assertEqual(r.model, "override-1")
        self.assertEqual(a.calls[-1]["model"], "override-1")

    def test_json_mode_off_does_not_inject_default_system(self):
        captured = {}

        class _CapturingProvider(_StubProvider):
            def complete(self, prompt, system_prompt="", *, model=None):
                captured["system"] = system_prompt
                return super().complete(prompt, system_prompt, model=model)

        p = _CapturingProvider(name="Cap")
        m = AIManager(chain=[_ChainEntry(p)], task_name="t")
        m.complete("x", json_mode=False)
        # DEFAULT_SYSTEM_PROMPT empieza con "Eres un asistente especializado"
        self.assertNotIn("Eres un asistente especializado", captured["system"])

    def test_json_mode_on_injects_default_system(self):
        captured = {}

        class _CapturingProvider(_StubProvider):
            def complete(self, prompt, system_prompt="", *, model=None):
                captured["system"] = system_prompt
                return super().complete(prompt, system_prompt, model=model)

        p = _CapturingProvider(name="Cap")
        m = AIManager(chain=[_ChainEntry(p)], task_name="t")
        m.complete("x", json_mode=True)
        self.assertIn("Eres un asistente especializado", captured["system"])


# ─────────────────────────────────────────────────────────────────────
#  Singleton por tarea + complete_for_task
# ─────────────────────────────────────────────────────────────────────

class TestTaskSingletons(unittest.TestCase):
    def setUp(self):
        # Reset singletons entre tests
        ai_manager_module._task_managers.clear()

    def test_singleton_caches_per_task(self):
        m1 = get_ai_manager_for_task(TASK_VALIDATION)
        m2 = get_ai_manager_for_task(TASK_VALIDATION)
        self.assertIs(m1, m2)
        m3 = get_ai_manager_for_task(TASK_PROMPT_ANALYSIS)
        self.assertIsNot(m1, m3)

    def test_status_includes_chain_labels(self):
        from src.services.task_chains import GROQ_LLAMA_70B, GROQ_LLAMA_8B
        m = get_ai_manager_for_task(TASK_VALIDATION)
        st = m.status()
        self.assertEqual(st["task"], TASK_VALIDATION)
        # La cadena de validación tiene Groq con DOS modelos distintos.
        groq_labels = [c["label"] for c in st["chain"] if c["provider"] == "Groq"]
        self.assertEqual(len(groq_labels), 2)
        # Los modelos de Groq en el status_dict contienen ambos por separado
        models = [c["model"] for c in st["chain"] if c["provider"] == "Groq"]
        self.assertIn(GROQ_LLAMA_70B, models)
        self.assertIn(GROQ_LLAMA_8B, models)
        # Y son distintos entre sí (el punto de tener dos eslabones Groq)
        self.assertNotEqual(GROQ_LLAMA_70B, GROQ_LLAMA_8B)


# ─────────────────────────────────────────────────────────────────────
#  AIInterpreter ejecuta análisis y queries en paralelo
# ─────────────────────────────────────────────────────────────────────

class TestAIInterpreterParallel(unittest.TestCase):
    def setUp(self):
        ai_manager_module._task_managers.clear()
        self._patches = []

    def tearDown(self):
        for p in self._patches:
            p.stop()
        ai_manager_module._task_managers.clear()

    def _patch_complete_for_task(self, fake):
        p1 = patch("src.services.ai_interpreter.complete_for_task", side_effect=fake)
        p2 = patch("src.services.precision_routers.complete_for_task", side_effect=fake)
        self._patches.extend([p1, p2])
        p1.start(); p2.start()

    def test_analysis_and_queries_use_different_chains(self):
        from src.services.ai_interpreter import AIInterpreter

        calls = []

        def fake(task, prompt, system_prompt="", *, json_mode=True):
            calls.append({"task": task, "system": system_prompt[:40]})
            if task == TASK_PROMPT_ANALYSIS:
                # Analyst → JSON con metadatos
                if "Prompt Analyst" in system_prompt or "PROMPT DEL USUARIO" in prompt:
                    body = (
                        '{"business_type":"ecommerce","product_category":"e-bikes",'
                        '"service_type":null,"niche":"urbano","location":{"country":"ES",'
                        '"region":null,"city":"Barcelona"},"target_audience":"B2C",'
                        '"language":"es","must_have":["Shopify"],"must_not":[],'
                        '"validation_indicators":["añadir al carrito"],'
                        '"exclusion_indicators":["qué es"],"confidence":0.9,'
                        '"analysis_notes":"OK","prompt_depurado":"e-bikes BCN"}'
                    )
                    return AIResponse(text=body, provider="Groq", model="llama-3.1-70b-versatile")
                else:
                    # router (tech/pagespeed) — respondemos default off
                    body = '{"use_scanner":false,"use_pagespeed":false,"confidence":"low","reason":"x"}'
                    return AIResponse(text=body, provider="Groq", model="x")
            if task == TASK_QUERY_GENERATION:
                body = (
                    '{"search_queries":["bicicletas eléctricas barcelona inurl:tienda",'
                    '"shopify e-bikes españa","intitle:tienda online de bicicletas",'
                    '"ebike comprar barcelona","mejor tienda ebike madrid",'
                    '"venta bicicletas eléctricas urbano",'
                    '"shopify bicicletas \\"añadir al carrito\\"",'
                    '"e-bikes premium tienda online",'
                    '"tienda ebike contacto presupuesto",'
                    '"\\"powered by shopify\\" bicicletas",'
                    '"comprar bicicleta eléctrica urbana barcelona",'
                    '"distribuidor bicicletas urbanas españa",'
                    '"tienda física bicicletas eléctricas barcelona",'
                    '"e-bike shop spain checkout",'
                    '"-blog -guia tienda online bicicletas electricas"]}'
                )
                return AIResponse(text=body, provider="SambaNova", model="405B")
            return AIResponse(text="", provider="none", success=False)

        self._patch_complete_for_task(fake)

        intent = AIInterpreter().interpret(
            "tienda online de bicicletas eléctricas en Barcelona con Shopify",
            precision_routing=False,
        )

        self.assertEqual(intent.business_type, "ecommerce")
        self.assertEqual(intent.location["country"], "ES")
        self.assertIn("Shopify", intent.must_have)
        self.assertGreaterEqual(len(intent.search_queries), 10)
        self.assertIn("Groq", intent.provider_used)
        self.assertIn("SambaNova", intent.provider_used)
        # Verificamos que se llamó a las dos cadenas distintas (al
        # menos una vez cada una; el routing está OFF en este test).
        tasks_called = [c["task"] for c in calls]
        self.assertIn(TASK_PROMPT_ANALYSIS, tasks_called)
        self.assertIn(TASK_QUERY_GENERATION, tasks_called)

    def test_fallback_to_local_when_analysis_fails(self):
        from src.services.ai_interpreter import AIInterpreter

        def fake(task, prompt, system_prompt="", *, json_mode=True):
            return AIResponse(text="", provider="none", success=False)

        self._patch_complete_for_task(fake)

        intent = AIInterpreter().interpret("blog de viajes", precision_routing=False)
        # Análisis local: regex que detecta blog en _BT_KEYWORDS
        self.assertEqual(intent.business_type, "blog")
        self.assertTrue(len(intent.search_queries) >= 5)


if __name__ == "__main__":
    unittest.main()
