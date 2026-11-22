import unittest
from service import get_bill


class TestService(unittest.TestCase):
    def test_get_bill(self):
        self.assertEqual(get_bill([10, 20]), 30)


if __name__ == "__main__":
    unittest.main()
