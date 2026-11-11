"""The level editor's dock, with its floor mode (fixture for the delivery-gap eval, #106)."""

from floor_model import draw_floor, move_room, place_rooms


class Dock:
    """The dock's tabs. Floor mode is the floor tab."""

    def __init__(self, floors: dict[str, list[str]]) -> None:
        self.floors = floors
        self.mode = "rooms"
        self.rooms = []
        self.floor_tab: list[str] = []

    def choose_floor(self, floor: str) -> list[str]:
        """Floor mode: choosing a floor lays out every room on it and shows it in the floor tab."""
        self.mode = "floor"
        self.rooms = place_rooms(self.floors[floor])
        self.floor_tab = draw_floor(self.rooms)
        return self.floor_tab

    def drag_room(self, name: str, x: int, y: int) -> None:
        """Moving a room by hand in the floor tab; it snaps to the grid."""
        self.rooms = [move_room(r, x, y) if r.name == name else r for r in self.rooms]
        self.floor_tab = draw_floor(self.rooms)
