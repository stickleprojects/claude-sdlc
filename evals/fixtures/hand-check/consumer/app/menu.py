"""A tiny game shell: the --start-room option and the command menu."""

ROOMS = {"hall", "lift", "library"}


class BadRoom(ValueError):
    """--start-room named a room that doesn't exist."""


def start_room(arg=None):
    """The room the game starts in: the hall unless --start-room names another."""
    if arg is None:
        return "hall"
    if arg not in ROOMS:
        raise BadRoom(f"no room called {arg!r}; the rooms are {', '.join(sorted(ROOMS))}")
    return arg


class Game:
    def __init__(self):
        self.menu_open = False
        self.paused = False

    def press(self, button):
        """Handle one button press: menu opens the menu, B closes it, pause toggles pause."""
        if button == "menu":
            self.menu_open = True
        elif button == "B" and self.menu_open:
            self.menu_open = False
        elif button == "pause":
            self.paused = not self.paused
