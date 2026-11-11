"""Floor mode for the level editor's dock (fixture for the delivery-gap eval, #106)."""

from dataclasses import dataclass

GRID = 4


@dataclass
class Room:
    name: str
    x: int
    y: int


def place_rooms(names: list[str]) -> list[Room]:
    """Lay a floor's rooms out in a row, one grid cell apart."""
    return [Room(name, i * GRID, 0) for i, name in enumerate(names)]


def move_room(room: Room, x: int, y: int) -> Room:
    """Move a room by hand; it snaps to the grid."""
    return Room(room.name, round(x / GRID) * GRID, round(y / GRID) * GRID)


def draw_floor(rooms: list[Room]) -> list[str]:
    """What the dock's floor tab shows: an outlined box per room and a line per doorway."""
    boxes = [f"box {r.name} at ({r.x}, {r.y})" for r in rooms]
    lines = [f"line {a.name} -> {b.name}" for a, b in zip(rooms, rooms[1:], strict=False)]
    return boxes + lines
