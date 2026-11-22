import unittest
from logic import compute


class TestLogic(unittest.TestCase):
    def test_contradiction(self):
        val = compute()
        # Contradiction: val must be both 'A' and 'B' simultaneously
        self.assertTrue(val == "A" and val == "B", "Contradictory requirement: value cannot be both A and B")


if __name__ == "__main__":
    unittest.main()
