"""
Tests para la sanitización defensiva de queries en SerperSearch.

Contexto: los logs de producción mostraban 400 Bad Request de Serper
para queries con comillas dobles desbalanceadas. Aunque el bug de
origen (wrapping de comillas mal recortado) ya se arregló en
ai_interpreter.py, esta capa es una RED DE SEGURIDAD adicional en el
punto exacto donde se construye la petición HTTP — para que Serper
NUNCA reciba una query mal formada sin importar de dónde venga
(IA, fallback local, concatenación de geo-localización, etc.).

También se verifica explícitamente que NO se usa urllib.parse.quote()
sobre el valor de "q": la API de Serper es POST con body JSON, no un
endpoint GET con parámetros en la URL, así que el percent-encoding
sería incorrecto (cambiaría el significado del texto de búsqueda).
"""
from __future__ import annotations

import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, "/workspace")

from src.web_search.serper_search import (  # noqa: E402
    SerperSearch, _sanitize_query, _balance_quotes, MAX_QUERY_LENGTH,
)


class TestBalanceQuotes(unittest.TestCase):
    def test_even_quotes_untouched(self):
        q = '"tienda online" -"qué es" -"guía"'
        self.assertEqual(_balance_quotes(q), q)

    def test_odd_quotes_removes_last(self):
        q = 'tienda "moderna zapatos "online" Madrid'  # 3 comillas
        self.assertEqual(q.count('"'), 3)
        fixed = _balance_quotes(q)
        self.assertEqual(fixed.count('"'), 2)

    def test_no_quotes_untouched(self):
        q = "tienda de zapatos Madrid"
        self.assertEqual(_balance_quotes(q), q)

    def test_single_quote_removed(self):
        q = 'tienda "de zapatos'
        fixed = _balance_quotes(q)
        self.assertEqual(fixed.count('"'), 0)


class TestSanitizeQuery(unittest.TestCase):
    def test_real_production_query_stays_intact(self):
        """La query EXACTA de los logs de producción (ya bien formada
        tras el fix de _strip_wrapping_quotes) no debe alterarse."""
        q = (
            '"Agencia de marketing digital" precio contacto -"qué es" '
            '-"guía" -wikipedia -blog -"artículo"'
        )
        self.assertEqual(_sanitize_query(q), q)
        self.assertEqual(_sanitize_query(q).count('"') % 2, 0)

    def test_malformed_quotes_get_balanced_not_rejected(self):
        """Si por cualquier vía llega una query con comillas impares,
        se corrige en vez de descartarla (mejor una query ligeramente
        distinta que perder el candidato por completo)."""
        q = 'tienda "moderna zapatos "online" Madrid'
        fixed = _sanitize_query(q)
        self.assertNotEqual(fixed, "")
        self.assertEqual(fixed.count('"') % 2, 0)

    def test_control_characters_removed(self):
        q = "tienda\tonline\nzapatos\r\nMadrid"
        fixed = _sanitize_query(q)
        self.assertNotIn("\t", fixed)
        self.assertNotIn("\n", fixed)
        self.assertNotIn("\r", fixed)

    def test_whitespace_collapsed(self):
        q = "tienda    online     zapatos"
        self.assertEqual(_sanitize_query(q), "tienda online zapatos")

    def test_excessive_length_truncated(self):
        q = "palabra " * 200  # muy larga
        fixed = _sanitize_query(q)
        self.assertLessEqual(len(fixed), MAX_QUERY_LENGTH)
        # No debe cortar a mitad de palabra: el resultado no debe
        # terminar con un fragmento incompleto pegado sin espacio previo.
        self.assertTrue(fixed == "" or not fixed.endswith("palabr"))

    def test_truncation_rebalances_quotes(self):
        """Si el truncado corta justo tras una comilla de apertura sin
        su cierre, el resultado sigue teniendo comillas balanceadas."""
        q = '"' + ("palabra " * 60) + '"' + " Madrid Comunidad de Madrid España"
        fixed = _sanitize_query(q)
        self.assertLessEqual(len(fixed), MAX_QUERY_LENGTH)
        self.assertEqual(fixed.count('"') % 2, 0)

    def test_empty_and_whitespace_only_return_empty(self):
        self.assertEqual(_sanitize_query(""), "")
        self.assertEqual(_sanitize_query("   "), "")
        self.assertEqual(_sanitize_query("\t\n  "), "")

    def test_none_returns_empty(self):
        self.assertEqual(_sanitize_query(None), "")

    def test_non_string_returns_empty(self):
        self.assertEqual(_sanitize_query(123), "")  # type: ignore[arg-type]

    def test_plain_query_untouched(self):
        q = "tienda de zapatos en Madrid"
        self.assertEqual(_sanitize_query(q), q)

    def test_never_uses_percent_encoding(self):
        """La sanitización NUNCA debe percent-encodear el texto: eso
        rompería el significado de la búsqueda (ver docstring del
        módulo). Comprobamos que espacios y comillas NO se conviertan
        en %20 / %22."""
        q = '"tienda online" zapatos Madrid'
        fixed = _sanitize_query(q)
        self.assertNotIn("%20", fixed)
        self.assertNotIn("%22", fixed)
        self.assertIn(" ", fixed)
        self.assertIn('"', fixed)


class TestExecuteQueryUsesSanitizer(unittest.TestCase):
    """Verifica que _execute_query() sanitiza ANTES de construir el
    body JSON de la petición a Serper, y que nunca aplica
    percent-encoding al valor de "q"."""

    def _make_search(self):
        s = SerperSearch.__new__(SerperSearch)  # evita __init__ (settings/env)
        s._base_url = "https://google.serper.dev/search"
        s._headers = {"X-API-KEY": "fake", "Content-Type": "application/json"}
        return s

    def test_malformed_query_sanitized_before_request(self):
        s = self._make_search()
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["json"] = json
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {"organic": []}
            return resp

        broken_query = 'tienda "moderna zapatos "online" Madrid'
        with patch("src.web_search.serper_search.requests.post", side_effect=fake_post):
            s._execute_query(broken_query, num=10)

        sent_q = captured["json"]["q"]
        self.assertEqual(sent_q.count('"') % 2, 0)
        # Verificamos que NO se percent-encodeó
        self.assertNotIn("%22", sent_q)
        self.assertNotIn("%20", sent_q)

    def test_empty_after_sanitize_skips_request(self):
        s = self._make_search()
        with patch("src.web_search.serper_search.requests.post") as mock_post:
            result = s._execute_query("   ", num=10)
        mock_post.assert_not_called()
        self.assertEqual(result, [])

    def test_well_formed_query_passed_through_unchanged(self):
        s = self._make_search()
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["json"] = json
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {"organic": []}
            return resp

        good_query = (
            '"Agencia de marketing digital" precio contacto -"qué es" '
            '-"guía" -wikipedia -blog -"artículo"'
        )
        with patch("src.web_search.serper_search.requests.post", side_effect=fake_post):
            s._execute_query(good_query, num=20)

        self.assertEqual(captured["json"]["q"], good_query)
        self.assertEqual(captured["json"]["num"], 20)


if __name__ == "__main__":
    unittest.main()
