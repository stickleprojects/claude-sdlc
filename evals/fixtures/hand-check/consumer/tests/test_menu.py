import unittest

from app.menu import start_room


class StartRoom(unittest.TestCase):
    def test_the_game_starts_in_the_hall(self):
        self.assertEqual(start_room(), "hall")


if __name__ == "__main__":
    unittest.main()
