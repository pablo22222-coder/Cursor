import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.prompt_parser import PromptParser


class TestPromptParser(unittest.TestCase):
    def test_extracts_site_type_product_and_speed(self) -> None:
        parser = PromptParser()
        spec = parser.parse("ecommerce de electronica con carga lenta")

        self.assertIn("ecommerce", spec.site_types)
        self.assertIn("electronica", spec.product_terms)
        self.assertEqual(spec.metrics.load_speed, "slow")


if __name__ == "__main__":
    unittest.main()
