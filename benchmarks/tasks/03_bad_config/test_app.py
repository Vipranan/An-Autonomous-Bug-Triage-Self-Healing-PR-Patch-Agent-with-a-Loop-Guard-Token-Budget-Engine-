import unittest
from app import load_settings


class TestApp(unittest.TestCase):
    def test_settings(self):
        cfg = load_settings()
        self.assertGreater(cfg["timeout"], 0)


if __name__ == "__main__":
    unittest.main()
