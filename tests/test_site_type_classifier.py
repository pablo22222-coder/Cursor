import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from detection.site_type_classifier import classify_site_types


class TestSiteTypeClassifier(unittest.TestCase):
    def test_detects_ecommerce_signal(self) -> None:
        text = "Add to cart. Checkout now. Shop our products."
        signals = classify_site_types(text, ["Shopify"])

        self.assertTrue(signals)
        self.assertEqual(signals[0].site_type, "ecommerce")


if __name__ == "__main__":
    unittest.main()
