"""The widget that paints a picture of `ui/drawing.py`, and the one that paints
a bitmap display.

There is almost nothing here on purpose: WHAT is drawn - every box, every word and
every place - is worked out in `ui/drawing.py`, which knows no GTK and is tested
like everything else. This is the brush.

The colour of the words is the widget's own, so a picture reads dark or light with
the desktop; the colours of the data are named in the picture and fixed there,
because a block that has been written to is red in any theme.
"""

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("PangoCairo", "1.0")

from gi.repository import Gtk, Pango, PangoCairo  # noqa: E402

from pyrars.ui.drawing import COLOURS, Picture  # noqa: E402

MARGIN = 6.0


class Canvas(Gtk.DrawingArea):
    """A picture on the screen. `show` puts another picture up."""

    __gtype_name__ = "PyrarsCanvas"

    def __init__(self, pressed=None, **kept) -> None:
        super().__init__(**kept)
        self.picture = Picture(0.0, 0.0)
        # Called with the NAME of a part that is clicked, where the picture gave
        # that part one: a key of the digital lab, and whatever comes after it.
        self.pressed = pressed
        self.set_draw_func(self._drawn)
        clicking = Gtk.GestureClick()
        clicking.connect("released", self._clicked)
        self.add_controller(clicking)

    def at(self, x: float, y: float) -> str:
        """What is at a place of the widget: the name of the part drawn there.

        The parts are looked through BACKWARDS, because the last drawn is the one
        on top, and only those the picture gave a name to can be pressed at all.
        """
        for part in reversed(self.picture.parts):
            if (part.name and part.width and part.height
                    and part.x + MARGIN <= x <= part.x + MARGIN + part.width
                    and part.y + MARGIN <= y <= part.y + MARGIN + part.height):
                return part.name
        return ""

    def _clicked(self, gesture, count: int, x: float, y: float) -> None:
        pressed = self.at(x, y)
        if pressed and self.pressed is not None:
            self.pressed(pressed)

    def show(self, picture: Picture) -> None:
        self.picture = picture
        self.set_size_request(int(picture.width + 2 * MARGIN),
                              int(picture.height + 2 * MARGIN))
        self.queue_draw()

    def _drawn(self, area, context, width: int, height: int) -> None:
        shown = self.get_color()  # the colour of text in this theme
        words = (shown.red, shown.green, shown.blue, shown.alpha)
        for part in self.picture.parts:
            # A box is made only where something will be painted with it. A
            # rectangle left in the path with nothing done to it is handed to
            # whatever is painted NEXT, which showed up as a row of the pipeline
            # painted in the colour of the row under it, over its own words (the
            # architect, 2026-10-23).
            if part.width and part.height and (part.fill or part.edge):
                context.rectangle(part.x + MARGIN, part.y + MARGIN, part.width,
                                  part.height)
                if part.fill:
                    context.set_source_rgb(*COLOURS[part.fill])
                    if part.edge:
                        context.fill_preserve()
                    else:
                        context.fill()
                if part.edge:
                    context.set_source_rgb(*COLOURS[part.edge])
                    context.set_line_width(part.line)
                    context.stroke()
            if part.text:
                # Words on a colour of the DATA are ink: every fill of a picture is
                # a pale one, so the theme's own colour would be white on pale in
                # the dark and unreadable.
                self._written(context, part,
                              (*COLOURS["ink"], 1.0) if part.fill else words)

    def _written(self, context, part, colour) -> None:
        """One word of a picture: in the middle of its box where it has one, and at
        its own place where it has not."""
        layout = self.create_pango_layout(part.text)
        layout.set_font_description(Pango.FontDescription(f"Sans {part.size:g}"))
        wide, tall = layout.get_pixel_size()
        x, y = part.x + MARGIN, part.y + MARGIN
        if part.width and part.height:
            x += (part.width - wide) / 2
            y += (part.height - tall) / 2
        context.move_to(x, y)
        red, green, blue, alpha = colour
        context.set_source_rgba(red, green, blue,
                                alpha * (0.6 if part.dim else 1.0))
        PangoCairo.show_layout(context, layout)


class Pixels(Gtk.DrawingArea):
    """The bitmap display: one word of memory is one unit of the picture, and the
    low 24 bits of that word are its red, green and blue.

    The picture arrives as the BYTES of the words of memory (`BitmapDisplay.looks`)
    and is handed to cairo as it comes: no packing, no copying, nothing counted.
    That is the whole reason the device keeps its frame as an array - a picture of
    512 by 256 is half a megabyte, and making a hundred and thirty thousand Python
    integers of it and packing them again cost four milliseconds a snapshot.

    A unit larger than a pixel is drawn by scaling the image and asking for no
    smoothing: a unit is a square of one colour, not a blur of four.
    """

    __gtype_name__ = "PyrarsPixels"

    def __init__(self, **kept) -> None:
        super().__init__(**kept)
        self.looks: dict = {}
        self.set_draw_func(self._drawn)

    def show(self, looks: dict) -> None:
        self.looks = looks
        self.set_size_request(int(looks.get("columns", 0))
                              * int(looks.get("unit_width", 1)),
                              int(looks.get("rows", 0))
                              * int(looks.get("unit_height", 1)))
        self.queue_draw()

    def _drawn(self, area, context, width: int, height: int) -> None:
        pixels = self.looks.get("pixels", b"")
        columns = int(self.looks.get("columns", 0))
        rows = int(self.looks.get("rows", 0))
        if not pixels or columns < 1 or rows < 1:
            return
        # cairo writes into what it is given, so the bytes are copied into
        # something writable - one copy of memory, and the only one.
        image = cairo.ImageSurface.create_for_data(bytearray(pixels),
                                                   cairo.FORMAT_RGB24,
                                                   columns, rows, columns * 4)
        context.scale(int(self.looks.get("unit_width", 1)),
                      int(self.looks.get("unit_height", 1)))
        context.set_source_surface(image, 0, 0)
        context.get_source().set_filter(cairo.FILTER_NEAREST)
        context.paint()
