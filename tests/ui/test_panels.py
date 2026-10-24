"""The panels: the widgets that paint what `ui/drawing.py` worked out.

What is DRAWN is tested without GTK (`tests/unit/test_ui_drawing.py`); what is
tested here is that the brush works - that every picture the project makes can be
painted, that a device gets the widget it ought to have, and that the one device
whose picture is not boxes and words but an image of memory is packed into that
image correctly.
"""

import cairo
import pytest

pytestmark = pytest.mark.ui


def painted(widget, width: int = 400, height: int = 300):
    """Paint a widget into an image nobody will look at, by calling the very
    function GTK calls. Anything the painting cannot do raises here."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    widget._drawn(widget, cairo.Context(surface), width, height)
    return surface


def seen(name: str, offset=0x10, size=5, state=None, looks=None):
    from pyrars.session.debug import DeviceSeen

    return DeviceSeen(name, offset, size, state or {}, looks or {})


# ------------------------------------------------------------------ the canvas


def test_a_picture_is_painted_as_it_was_worked_out(gtk):
    from pyrars.session.debug import CacheLine, CacheSeen, Setting
    from pyrars.ui.canvas import Canvas
    from pyrars.ui.drawing import cache_picture

    cache = CacheSeen("cache", False, (Setting("block_bytes", 16),
                                       Setting("sets", 2), Setting("ways", 2)),
                      4, 1, 3, 0.25, 0, 0)
    drawn = cache_picture([cache], [CacheLine("cache", 0, 0, 1, 0, 15, True)])
    made = Canvas()
    made.show(drawn)
    assert made.picture is drawn
    wide, tall = made.get_size_request()
    assert wide >= int(drawn.width) and tall >= int(drawn.height)
    painted(made)  # and it paints without a word of complaint


def test_a_box_of_a_picture_lands_where_the_picture_put_it(gtk):
    """The one thing the brush decides is the margin around a picture, so that a
    box at nothing, nothing is not against the edge of the widget."""
    from pyrars.ui.canvas import MARGIN, Canvas
    from pyrars.ui.drawing import COLOURS, Part, Picture

    made = Canvas()
    made.show(Picture(40.0, 40.0, (Part(0.0, 0.0, 20.0, 20.0, fill="lit"),)))
    surface = painted(made, 60, 60)
    held, stride = surface.get_data(), surface.get_stride()

    def pixel(x: int, y: int) -> tuple[int, ...]:
        at = y * stride + 4 * x
        return tuple(held[at:at + 3])

    red = tuple(round(one * 255) for one in reversed(COLOURS["lit"]))
    inside = pixel(int(MARGIN) + 4, int(MARGIN) + 4)
    assert max(abs(one - other) for one, other in zip(inside, red)) <= 1
    assert pixel(1, 1) == (0, 0, 0)  # and nothing is painted in the margin


def test_a_box_with_no_colour_of_its_own_paints_nothing(gtk):
    """And leaves nothing behind for the next box either.

    A rectangle put in the path of cairo and never painted is handed to whatever
    is painted NEXT: the row of names of the pipeline, which has a box and no
    colour, came out in the colour of the row under it and over its own words (the
    architect, 2026-10-23).
    """
    from pyrars.ui.canvas import MARGIN, Canvas
    from pyrars.ui.drawing import Part, Picture

    made = Canvas()
    made.show(Picture(80.0, 80.0, (
        Part(0.0, 0.0, 20.0, 20.0, text="here"),  # a box with no colour at all
        Part(0.0, 40.0, 20.0, 20.0, fill="lit"))))  # and one with a colour
    surface = painted(made, 100, 100)
    held, stride = surface.get_data(), surface.get_stride()

    def pixel(x: int, y: int) -> tuple[int, ...]:
        at = y * stride + 4 * x
        return tuple(held[at:at + 3])

    assert pixel(int(MARGIN) + 2, int(MARGIN) + 18) == (0, 0, 0)  # nothing painted
    assert pixel(int(MARGIN) + 2, int(MARGIN) + 42) != (0, 0, 0)  # and that one is


def test_words_on_a_colour_of_the_data_are_dark_whatever_the_theme(gtk):
    """Every fill of a picture is a pale one, so the words on it are ink: the
    theme's own colour would be white on pale in the dark."""
    from pyrars.ui.canvas import Canvas
    from pyrars.ui.drawing import COLOURS, Part, Picture

    made = Canvas()
    made.show(Picture(60.0, 30.0, (Part(0.0, 0.0, 50.0, 24.0, fill="empty",
                                        text="IF", size=10.0),)))
    surface = painted(made, 80, 60)
    held, stride = surface.get_data(), surface.get_stride()
    ink = tuple(round(one * 255) for one in reversed(COLOURS["ink"]))
    pale = tuple(round(one * 255) for one in reversed(COLOURS["empty"]))
    seen = {tuple(held[y * stride + 4 * x:y * stride + 4 * x + 3])
            for y in range(6, 28) for x in range(6, 54)}

    def near(colour, wanted, allowed: int = 24) -> bool:
        return max(abs(one - other) for one, other in zip(colour, wanted)) <= allowed

    assert any(near(colour, pale, 2) for colour in seen)  # the cell
    assert any(near(colour, ink) for colour in seen)  # the letters on it, in ink


def test_every_picture_the_project_makes_can_be_painted(gtk):
    """One test for all of them: a colour nobody has, or a word GTK cannot lay
    out, would otherwise show up in a draw handler, where nothing is reported."""
    from pyrars.session.debug import Setting, StageSeen, StatisticsSeen
    from pyrars.ui import drawing
    from pyrars.ui.canvas import Canvas

    from tests.unit.test_ui_drawing import cache, lab

    made = Canvas()
    for picture in (
            drawing.cache_picture([cache(accesses=1, misses=1)]),
            drawing.pipeline_picture([StageSeen(0, "addi", (0, 1, 2, 3, 4), 1, 0)]),
            drawing.lab_picture(lab(left=0x5A, key=3, counting=True, counter=7)),
            drawing.bars_picture(StatisticsSeen(1, 1, 0, 0, 0, 0,
                                                (Setting("alu", 1),), ())),
            drawing.blocks_picture({"blocks": 3, "at": 1, "left": 1,
                                    "working": True, "writing": False,
                                    "refused": True}),
            drawing.copying_picture({"copied": 1, "left": 1, "copying": True,
                                     "from": 0, "to": 4, "refused": False})):
        made.show(picture)
        painted(made)


def test_a_picture_on_the_screen(showing, gtk):
    """Once through the real thing: GTK itself asks for the drawing, with a theme
    and a colour of its own."""
    from pyrars.ui.canvas import Canvas
    from pyrars.ui.drawing import Part, Picture

    made = showing(Canvas())
    made.show(Picture(200.0, 60.0, (Part(0.0, 0.0, 80.0, 20.0, fill="clean",
                                         edge="frame", text="here"),
                                    Part(0.0, 30.0, text="and a word", dim=True))))
    assert made.get_width() > 0


# ------------------------------------------------------- the bitmap display


def test_the_units_of_a_bitmap_become_the_pixels_of_an_image(gtk):
    """One word of memory is one unit, and the low 24 bits of it are its colour.
    The bytes of the words ARE the image, so nothing is packed at all."""
    from pyrars.ui.canvas import Pixels

    made = Pixels()
    made.show({"pixels": bytes((0x00, 0x00, 0xFF, 0x00,   # red, as a word is held
                                0x00, 0xFF, 0x00, 0x00,   # green
                                0xFF, 0x00, 0x00, 0x00,   # blue
                                0xFF, 0xFF, 0xFF, 0x00)),  # white
               "columns": 2, "rows": 2, "unit_width": 3, "unit_height": 3})
    assert made.get_size_request() == (6, 6)  # two units of three pixels
    surface = painted(made, 6, 6)
    held = surface.get_data()
    stride = surface.get_stride()
    # the first unit is red, and it fills the three by three it was given
    for x in range(3):
        for y in range(3):
            assert tuple(held[y * stride + 4 * x:y * stride + 4 * x + 3]) \
                == (0x00, 0x00, 0xFF)  # blue, green, red, as cairo holds them
    assert tuple(held[0:3]) != tuple(held[12:15])  # and the next unit is not red


def test_a_bitmap_with_nothing_in_it_paints_nothing(gtk):
    from pyrars.ui.canvas import Pixels

    made = Pixels()
    made.show({})
    assert made.get_size_request() == (0, 0)
    painted(made, 4, 4)


# ------------------------------------------------------- the panels themselves


def test_what_is_at_a_place_of_a_picture(gtk):
    """A click is answered by looking through the parts BACKWARDS, because the last
    drawn is the one on top; and only what the picture gave a name to answers at
    all."""
    from pyrars.ui.canvas import MARGIN, Canvas
    from pyrars.ui.drawing import Part, Picture

    heard = []
    made = Canvas(pressed=heard.append)
    made.show(Picture(100.0, 100.0, (
        Part(0.0, 0.0, 40.0, 20.0, fill="empty", name="key:1"),
        Part(0.0, 0.0, 40.0, 20.0, fill="lit", name="key:2"),  # drawn over it
        Part(50.0, 0.0, 40.0, 20.0, fill="empty"),  # and this one has no name
        Part(50.0, 40.0, 40.0, 20.0, fill="empty", name="key:3"),
        Part(50.0, 40.0, 40.0, 20.0, fill="frame"))))  # nameless, over a key
    assert made.at(MARGIN + 2, MARGIN + 2) == "key:2"
    assert made.at(MARGIN + 52, MARGIN + 2) == ""  # nameless: nothing to press
    assert made.at(MARGIN + 2, MARGIN + 80) == ""  # and nothing is there at all
    # a part with no name of its own does not stand in the way of one that has
    assert made.at(MARGIN + 52, MARGIN + 42) == "key:3"
    # and a click where nothing can be pressed tells nobody anything
    made._clicked(None, 1, MARGIN + 52.0, MARGIN + 2.0)
    assert heard == []
    made._clicked(None, 1, MARGIN + 2.0, MARGIN + 2.0)
    assert heard == ["key:2"]


def test_a_key_of_the_lab_clicked_reaches_whoever_is_listening(gtk, showing,
                                                               turning):
    """The whole way: a click on the picture of the lab becomes the device and the
    number of the key, for the window to hand to the thread of the run."""
    from gi.repository import Gdk, Gtk

    from pyrars.ui.devices import Panel

    pressed = []
    panel = Panel("lab", pressed=lambda device, key: pressed.append((device, key)))
    panel.show(seen("lab", looks={"left": 0, "right": 0, "keys": 16, "key": -1,
                                  "segments": tuple("abcdefg") + ("dot",),
                                  "counting": False, "counter": 0, "period": 31,
                                  "keys tell": False}))
    showing(panel)
    # where the sixth key is drawn, in the coordinates of the widget
    from pyrars.ui.canvas import MARGIN
    key = [part for part in panel.picture.picture.parts
           if part.name == "key:6"][0]
    panel.picture._clicked(None, 1, key.x + MARGIN + 2, key.y + MARGIN + 2)
    assert pressed == [("lab", 6)]
    # and a click where nothing is named presses nothing
    panel.picture._clicked(None, 1, 0.0, 0.0)
    assert pressed == [("lab", 6)]


def test_only_what_the_picture_calls_a_key_is_one(gtk):
    """The panel reads the picture's own naming and nothing else, so a part named
    for something that is not a key presses no key."""
    from pyrars.ui.devices import _clicked_on

    assert _clicked_on("key:7") == 7
    assert _clicked_on("key:15") == 15
    assert _clicked_on("pad:7") is None  # named for something else
    assert _clicked_on("key:") is None
    assert _clicked_on("") is None


def test_a_panel_of_a_device_with_no_keys_presses_nothing(gtk):
    """A timer has no picture at all, so there is nothing of it to click."""
    from pyrars.ui.devices import Panel

    panel = Panel("timer", pressed=lambda device, key: 1 / 0)
    panel.show(seen("timer", state={"clock": "wall"}))
    assert panel.picture is None


def test_every_device_gets_a_panel_and_the_right_one(gtk):
    """A device with a picture gets it above its table; one whose whole state is
    three numbers gets the numbers, because a drawing of a number says nothing the
    number does not."""
    from pyrars.devices import DEVICES
    from pyrars.ui import devices
    from pyrars.ui.canvas import Canvas, Pixels

    expected = {"bitmap": Pixels, "keyboard": devices.Display, "lab": Canvas,
                "disk": Canvas, "dma": Canvas}
    for name in DEVICES:
        panel = devices.Panel(name)
        assert panel.device == name
        if name in expected:
            assert isinstance(panel.picture, expected[name]), name
        else:
            assert panel.picture is None, name


def test_a_panel_puts_the_picture_beside_the_table(gtk):
    """Beside and not above (the architect, 2026-10-22): the room the views have is
    wide and shallow, while a picture and a table of names and values are both
    narrow and long, so side by side each of them gets its whole height."""
    from gi.repository import Gtk

    from pyrars.ui.devices import Panel

    pane = Panel("lab").get_first_child()
    assert isinstance(pane, Gtk.Paned)
    assert pane.get_orientation() == Gtk.Orientation.HORIZONTAL
    assert pane.get_end_child() is not None  # the table, beside it


def test_a_panel_says_where_its_device_answers(gtk):
    from pyrars.ui.devices import Panel

    panel = Panel("timer")
    panel.show(seen("timer", 0x18, 16, {"clock": "wall", "time": 7}),
               base=0xFFFF0000)
    assert panel.table.rows[0] == ("where", "0xffff0018")
    assert panel.table.rows[1] == ("size", "16 bytes")
    assert dict(panel.table.rows)["time"] == "7"  # a device counts in tens


def test_a_panel_of_a_device_that_is_not_attached_keeps_what_it_had(gtk):
    """The last thing a device held is more use than an empty panel: a run that
    ended is still a run somebody is reading."""
    from pyrars.ui.devices import Panel

    panel = Panel("lab")
    panel.show(seen("lab", state={"left": "0x01"},
                    looks={"left": 1, "right": 0, "segments": ("a",), "keys": 4,
                           "key": 0, "counting": False, "counter": 0,
                           "period": 31, "keys tell": False}))
    held = panel.table.rows
    panel.show(None)
    assert panel.table.rows == held


def test_the_display_of_the_keyboard_shows_what_the_program_wrote(gtk):
    from pyrars.ui.devices import Panel

    panel = Panel("keyboard")
    panel.show(seen("keyboard", 0x0, 16, {"shown": "hi"},
                    {"text": "hi there", "columns": 80, "rows": 25,
                     "queued": 2, "lost": 1, "busy": False}))
    buffer = panel.picture.view.get_buffer()
    said = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
    assert said.startswith("hi there")
    assert "2 keys typed and not read yet" in said
    assert "1 keys lost" in said


def test_the_lab_is_drawn_from_the_numbers_it_reports(gtk):
    from pyrars.ui.devices import Panel

    panel = Panel("lab")
    panel.show(seen("lab", looks={"left": 0xFF, "right": 0, "keys": 16, "key": 2,
                                  "segments": tuple("abcdefg") + ("dot",),
                                  "counting": False, "counter": 0, "period": 31,
                                  "keys tell": False}))
    lit = [part for part in panel.picture.picture.parts if part.fill == "lit"]
    assert len(lit) == 9  # eight segments of the left display, and the key down
    painted(panel.picture)
