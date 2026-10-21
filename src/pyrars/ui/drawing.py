"""What the pictures of the window are made of, worked out where no widget is.

A picture here is DATA: boxes and words at places, in pixels of its own, and
`ui/canvas.py` paints them and nothing else. So where the blocks of a cache lie,
which cycle each stage of an instruction fell in and which segments of a display
are lit are all worked out in a module that imports no `gi` and is tested and
mutated like every other module of the project, and the widget underneath is
twenty lines that can hold no mistake worth finding.

Why pictures at all: a table of numbers says what happened and a picture says what
is HAPPENING. A cache of eight sets that misses two hundred and fifty-six times
out of two hundred and fifty-six is one number in a table and an obvious story in a
grid - the two streams of the program land in the same set and throw each other
out, again and again (the architect, 2026-10-22, who asked for this after watching
a table tell him nothing).

The colours of the DATA are named here and fixed: a block that has been written to
is red whatever the theme of the desktop, as a warning light is red in any room.
The colour of the WORDS is the theme's own, which the canvas puts in, so that a
picture can be read dark or light.
"""

from dataclasses import dataclass

# The colours of the data, as red, green and blue.
COLOURS = {
    "frame": (0.55, 0.55, 0.58),
    "empty": (0.86, 0.86, 0.88),
    "clean": (0.52, 0.74, 0.93),
    "dirty": (0.95, 0.62, 0.44),
    "hit": (0.47, 0.78, 0.55),
    "miss": (0.93, 0.52, 0.47),
    "lit": (0.95, 0.27, 0.22),
    "dark": (0.28, 0.28, 0.31),
    "on": (0.47, 0.78, 0.55),
    "bar": (0.52, 0.74, 0.93),
    # The five stages of the pipeline, each its own colour, because the eye reads a
    # diagonal of five colours and counts nothing.
    "fetch": (0.62, 0.72, 0.92),
    "decode": (0.56, 0.82, 0.86),
    "execute": (0.60, 0.84, 0.62),
    "memory": (0.95, 0.84, 0.55),
    "write": (0.88, 0.70, 0.90),
}

STAGES = ("fetch", "decode", "execute", "memory", "write")
INITIALS = ("IF", "ID", "EX", "ME", "WB")


@dataclass(frozen=True, slots=True)
class Part:
    """One thing on a picture: a box, a word, or a word in a box.

    A part with a width and a height is a box; one with text and no box is a word
    at that place; one with both is a word in the middle of its box.
    """

    x: float
    y: float
    width: float = 0.0
    height: float = 0.0
    fill: str = ""  # the name of a colour; nothing means no box is painted
    edge: str = ""
    text: str = ""
    size: float = 11.0
    dim: bool = False  # a word that is there to be glanced at, not read


@dataclass(frozen=True, slots=True)
class Picture:
    """A whole picture: how much room it needs, and what is on it."""

    width: float
    height: float
    parts: tuple[Part, ...] = ()


# How big the pieces of a picture are, in pixels.
BLOCK = (134.0, 26.0)  # one block of a cache
SET = 58.0  # the room beside the grid for the name of a set
LINE = 20.0  # one line of writing
CYCLE = 28.0  # one cycle of the pipeline
STEP = 22.0  # one instruction of the diagram
WHERE = 190.0  # the room beside the diagram for the place and the instruction
KEY = 38.0  # one key of the lab's keyboard
SEGMENT = 11.0  # how thick a segment of a display is
DIGIT = (66.0, 108.0)  # and how big the whole digit is
GAP = 6.0


def cache_picture(seen, blocks=()) -> Picture:
    """The caches as a grid: a row to a set, a column to a way, and in each cell
    the addresses that block is holding.

    This is the one view that says WHY a cache is doing badly. The blocks of a set
    are in the order they will make room in (`place` 0 goes first, which is also
    how long it has been there), so a set whose cells keep changing while the rest
    are empty is a program whose addresses all land in the one set.
    """
    held = {(line.side, line.set, line.place): line for line in blocks}
    parts: list[Part] = []
    y = 0.0
    for cache in seen:
        built = {one.name: one.value for one in cache.settings}
        sets, ways = int(built.get("sets", 1)), int(built.get("ways", 1))
        parts.append(Part(0.0, y, text=_heading(cache, built), size=12.0))
        y += LINE + GAP
        for place in range(ways):
            parts.append(Part(SET + place * BLOCK[0], y, text=f"way {place}",
                              size=10.0, dim=True))
        y += LINE
        for index in range(sets):
            parts.append(Part(0.0, y + 4.0, text=f"set {index}", size=10.0,
                              dim=True))
            for place in range(ways):
                line = held.get((cache.side, index, place))
                parts.append(Part(SET + place * BLOCK[0], y, BLOCK[0] - GAP,
                                  BLOCK[1] - 2.0,
                                  fill="empty" if line is None else
                                  "dirty" if line.dirty else "clean",
                                  edge="frame",
                                  text="" if line is None
                                  else f"0x{line.low:08x}", size=10.0))
            y += BLOCK[1]
        y += LINE
    return Picture(SET + max(1, _widest(seen)) * BLOCK[0], max(y, LINE), tuple(parts))


def _heading(cache, built: dict) -> str:
    """One line above a grid: what the cache is, and how it has fared."""
    said = (f"{cache.side}: {built.get('sets')} sets of {built.get('ways')}, "
            f"{built.get('block_bytes')} bytes a block")
    if cache.accesses:
        said += (f" - {cache.accesses} accesses, {cache.hits} hits, "
                 f"{cache.misses} misses ({cache.rate * 100:.0f}% hit)")
    else:
        said += " - nothing has reached it yet"
    return said


def _widest(seen) -> int:
    return max((int({one.name: one.value for one in cache.settings}.get("ways", 1))
                for cache in seen), default=1)


def pipeline_picture(rows) -> Picture:
    """The diagram: a row to an instruction, a column to a cycle, and the five
    stages of each instruction laid along it.

    What is to be seen in it is the diagonal: every instruction one cycle behind
    the one before it, and wherever the diagonal breaks something was waited for -
    a result that had not been written back, a branch that was guessed wrongly.
    """
    if not rows:
        return Picture(0.0, 0.0)
    parts: list[Part] = []
    cycles = max(row.starts[-1] + 1 for row in rows)
    for cycle in range(cycles):
        if cycle % 5 == 0:
            parts.append(Part(WHERE + cycle * CYCLE, 0.0, text=str(cycle),
                              size=10.0, dim=True))
    for index, row in enumerate(rows):
        y = LINE + index * STEP
        parts.append(Part(0.0, y + 2.0,
                          text=f"0x{row.address:08x}  {row.mnemonic}", size=10.0))
        for stage, (name, start) in enumerate(zip(STAGES, row.starts)):
            wide = row.ex_cycles if name == "execute" else 1
            parts.append(Part(WHERE + start * CYCLE, y, CYCLE * wide - 2.0,
                              STEP - 2.0, fill=name, edge="frame",
                              text=INITIALS[stage], size=9.0))
    return Picture(WHERE + cycles * CYCLE, LINE + len(rows) * STEP, tuple(parts))


def lab_picture(looks) -> Picture:
    """The digital lab: two seven-segment displays, the sixteen keys, the counter.

    The keys are drawn in the four rows of four the device wires them as, because
    which ROW a key is in is what a program asks about (it says which row to look
    at, and is told nothing about the others).
    """
    if not looks:
        return Picture(0.0, 0.0)
    parts: list[Part] = []
    segments = tuple(looks.get("segments", ()))
    for place, which in enumerate(("left", "right")):
        parts += _digit(place * (DIGIT[0] + GAP * 3), 0.0,
                        int(looks.get(which, 0)), segments)
    x = 2 * (DIGIT[0] + GAP * 3) + GAP * 2
    keys = int(looks.get("keys", 16))
    down = int(looks.get("key", -1))
    for key in range(keys):
        parts.append(Part(x + (key % 4) * KEY, (key // 4) * KEY, KEY - GAP,
                          KEY - GAP, fill="lit" if key == down else "empty",
                          edge="frame", text=f"{key:x}".upper(), size=11.0))
    y = max(DIGIT[1], (keys + 3) // 4 * KEY) + GAP
    period = max(int(looks.get("period", 1)), 1)
    left = int(looks.get("counter", 0))
    wide = (DIGIT[0] + GAP * 3) * 2 + KEY * 4
    parts.append(Part(0.0, y, wide, LINE - 4.0, fill="empty", edge="frame"))
    if looks.get("counting"):
        parts.append(Part(0.0, y, wide * (period - left) / period, LINE - 4.0,
                          fill="bar"))
    parts.append(Part(0.0, y + LINE, text="counter: "
                      + (f"{left} notices to go" if looks.get("counting")
                         else "off")
                      + ("; a key tells the program" if looks.get("keys tell")
                         else ""), size=10.0, dim=True))
    return Picture(x + KEY * 4, y + LINE * 2, tuple(parts))


def _digit(x: float, y: float, bits: int, segments=()) -> list[Part]:
    """One seven-segment display, from the bits the program wrote into it.

    The places are the shape of the thing: a and d across the top and the bottom,
    b and c down the right, e and f down the left, g across the middle, and the
    dot beside it. The ORDER of the bits is the device's own (`SEGMENTS`), so a
    device that numbered them otherwise would draw itself right here.
    """
    wide, tall = DIGIT
    thick = SEGMENT
    places = {
        "a": (x + thick, y, wide - 2 * thick, thick),
        "b": (x + wide - thick, y + thick, thick, (tall - 3 * thick) / 2),
        "c": (x + wide - thick, y + (tall + thick) / 2, thick,
              (tall - 3 * thick) / 2),
        "d": (x + thick, y + tall - thick, wide - 2 * thick, thick),
        "e": (x, y + (tall + thick) / 2, thick, (tall - 3 * thick) / 2),
        "f": (x, y + thick, thick, (tall - 3 * thick) / 2),
        "g": (x + thick, y + (tall - thick) / 2, wide - 2 * thick, thick),
        "dot": (x + wide + GAP, y + tall - thick, thick, thick),
    }
    parts = []
    for index, name in enumerate(segments or tuple(places)):
        if name not in places:
            continue
        box = places[name]
        parts.append(Part(box[0], box[1], box[2], box[3],
                          fill="lit" if bits >> index & 1 else "dark"))
    return parts


def bars_picture(counted, wide: float = 320.0) -> Picture:
    """What the run was made of, as bars: the instructions by kind.

    A bar is read without reading: which kind of instruction a program is made of
    is the first question anybody asks of a count, and the answer is a shape.
    """
    if counted is None or not counted.kinds:
        return Picture(0.0, 0.0)
    most = max(one.value for one in counted.kinds) or 1
    parts: list[Part] = []
    for index, one in enumerate(counted.kinds):
        y = index * (LINE + 4.0)
        parts.append(Part(0.0, y + 2.0, text=one.name, size=10.0))
        parts.append(Part(SET + GAP, y, wide * one.value / most, LINE - 4.0,
                          fill="bar"))
        parts.append(Part(SET + GAP + wide * one.value / most + GAP, y + 2.0,
                          text=str(one.value), size=10.0, dim=True))
    return Picture(SET + GAP + wide + 70.0, len(counted.kinds) * (LINE + 4.0),
                   tuple(parts))


def blocks_picture(looks) -> Picture:
    """A disk as its blocks, with the one it is working on lit."""
    if not looks:
        return Picture(0.0, 0.0)
    blocks = int(looks.get("blocks", 0))
    at = int(looks.get("at", 0))
    working = bool(looks.get("working"))
    across = min(blocks, 16) or 1
    parts: list[Part] = []
    for block in range(blocks):
        parts.append(Part((block % across) * KEY, (block // across) * KEY,
                          KEY - GAP, KEY - GAP,
                          fill="lit" if working and block == at else "empty",
                          edge="frame", text=str(block), size=10.0))
    y = ((blocks + across - 1) // across) * KEY
    said = (f"working {'to' if looks.get('writing') else 'from'} the disk at block "
            f"{at}, {looks.get('left')} to go" if working else "not working")
    parts.append(Part(0.0, y, text=said
                      + (" - the last work was refused" if looks.get("refused")
                         else ""), size=10.0, dim=True))
    return Picture(across * KEY, y + LINE, tuple(parts))


def copying_picture(looks, wide: float = 360.0) -> Picture:
    """What the controller of direct access has copied, as a bar: a program that
    waits on it waits for that bar to fill."""
    if not looks:
        return Picture(0.0, 0.0)
    copied, left = int(looks.get("copied", 0)), int(looks.get("left", 0))
    whole = copied + left or 1
    parts = [Part(0.0, 0.0, wide, LINE, fill="empty", edge="frame"),
             Part(0.0, 0.0, wide * copied / whole, LINE, fill="bar")]
    said = (f"copying 0x{int(looks.get('from', 0)):08x} to "
            f"0x{int(looks.get('to', 0)):08x}: {copied} words copied, {left} to go"
            if looks.get("copying") else f"{copied} words copied, not copying")
    parts.append(Part(0.0, LINE + 4.0, text=said
                      + (" - the last copying was refused"
                         if looks.get("refused") else ""), size=10.0, dim=True))
    return Picture(wide, LINE * 2 + 4.0, tuple(parts))
