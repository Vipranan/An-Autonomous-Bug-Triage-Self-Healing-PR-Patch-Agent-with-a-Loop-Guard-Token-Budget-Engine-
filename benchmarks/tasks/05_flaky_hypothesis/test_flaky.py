import unittest
from wrapper import handle


class TestFlaky(unittest.TestCase):
    def test_handle(self):
        self.assertEqual(handle("hello"), "HELLO")


if __name__ == "__main__":
    unittest.main()
