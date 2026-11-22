from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pricing import apply_discount


class TestPricing(unittest.TestCase):
    def test_discount_calculation(self):
        self.assertEqual(apply_discount(200.0, 15.0), 170.0)


if __name__ == "__main__":
    unittest.main()
