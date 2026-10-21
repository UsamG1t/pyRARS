"""The widget that paints a picture of `ui/drawing.py`, and the one that paints
a bitmap display.

There is almost nothing here on purpose: WHAT is drawn - every box, every word and
every place - is worked out in `ui/drawing.py`, which knows no GTK and is tested
like everything else. This is the brush.

The colour of the words is the widget's own, so a picture reads dark or light with
the desktop; the colours of the data are named in the picture and fixed there,
because a block that has been written to is red in any theme.
"""

import struct

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

    def __init__(self, **kept) -> None:
        super().__init__(**kept)
        self.picture = Picture(0.0, 0.0)
        self.set_draw_func(self._drawn)

    def show(self, picture: Picture) -> None:
        self.picture = picture
        self.set_size_request(int(picture.width + 2 * MARGIN),
                              int(picture.height + 2 * MARGIN))
        self.queue_draw()

    def _drawn(self, area, context, width: int, height: int) -> None:
        words = self.get_color()  # the colour of text in this theme
        for part in self.picture.parts:
            if part.width and part.height:
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
                    context.set_line_width(1.0)
                    context.stroke()
            if part.text:
                self._written(context, part, words)

    def _written(self, context, part, words) -> None:
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
        context.set_source_rgba(words.red, words.green, words.blue,
                               words.alpha * (0.6 if part.dim else 1.0))
        PangoCairo.show_layout(context, layout)


class Pixels(Gtk.DrawingArea):
    """The bitmap display: one word of memory is one unit of the picture, and the
    low 24 bits of that word are its red, green and blue.

    The units arrive as the numbers they are (`BitmapDisplay.looks`) and are packed
    into an image in one call, because a picture of 512 by 256 is a hundred and
    thirty thousand of them and a loop in Python over that is a tenth of a second.
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
        units = self.looks.get("units", ())
        columns = int(self.looks.get("columns", 0))
        rows = int(self.looks.get("rows", 0))
        if not units or columns < 1 or rows < 1:
            return
        held = bytearray(struct.pack(f"<{len(units)}I", *units))
        image = cairo.ImageSurface.create_for_data(held, cairo.FORMAT_RGB24,
                                                   columns, rows, columns * 4)
        context.scale(int(self.looks.get("unit_width", 1)),
                      int(self.looks.get("unit_height", 1)))
        context.set_source_surface(image, 0, 0)
        context.get_source().set_filter(cairo.FILTER_NEAREST)
        context.paint()
