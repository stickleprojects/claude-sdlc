import unittest

from app.prices import format_price


class FormatPriceTest(unittest.TestCase):
    def test_dollars_and_cents(self) -> None:
        self.assertEqual(format_price(1234), "$12.34")


if __name__ == "__main__":
    unittest.main()
