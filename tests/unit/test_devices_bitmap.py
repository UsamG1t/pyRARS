"""The bitmap display: a piece of memory seen as a picture.

Expected values are the verified protocol of RARS (R-DEV-BITMAP, read from the byte
code of `tools/BitmapDisplay` 2026-10-08): one word of memory per unit of the
picture, row by row, the colour in the low 24 bits, the five places the picture may
lie at, the range watched from the base over as many words as the picture holds, cut
off at 0xfffffffc, and the WORD of memory taken on a write - not the value written.
"""

import pytest

from pyrars.core.machine import Machine
from pyrars.core.options import Options
from pyrars.devices import DeviceBus, make
from pyrars.devices.bitmap import BitmapDisplay
from pyrars.isa.memory import CONFIGS, DEFAULT


def screen(**options) -> tuple[Machine, BitmapDisplay]:
    config = options.pop("config", DEFAULT)
    before = options.pop("before", ())  # words put in memory before it is attached
    device = BitmapDisplay(**options)
    bus = DeviceBus([device])
    machine = Machine(Options(config=config), bus=bus)
    for address, value in before:
        machine.memory.poke(address, 4, value)
    bus.connect(machine)
    return machine, device


# ------------------------------------------------------- what it looks like


def test_what_the_display_looks_like_is_the_bytes_of_an_image():
    """`state` is what to read ABOUT the display; `looks` is the picture itself,
    which is the one thing a table of words cannot say - and it is handed over as
    the BYTES of the words, which is one copy of memory and no work at all."""
    from array import array

    # a word of memory is four bytes of the image, and that is what the whole of
    # this rests on: the picture is drawn straight from them
    assert array("I").itemsize == 4
    # twelve pixels across in units of three is four units across, as RARS counts
    machine, device = screen(width=12, height=10, unit_width=3, unit_height=5)
    machine.memory.write(device.base, 4, 0xFF0000)
    machine.memory.write(device.base + 4, 4, 0x00FF00)
    looks = device.looks()
    # blue, green, red, unused - the word as this machine holds it
    assert looks["pixels"][:8] == bytes((0x00, 0x00, 0xFF, 0x00,
                                         0x00, 0xFF, 0x00, 0x00))
    assert len(looks["pixels"]) == 8 * 4  # four bytes to each of eight units
    assert (looks["columns"], looks["rows"]) == (4, 2)
    assert (looks["unit_width"], looks["unit_height"]) == (3, 5)
    # a copy, because whoever draws it has a thread of its own
    assert looks["pixels"] is not device.frame


# ------------------------------------------------------------------- the place


def test_the_picture_lies_where_the_data_of_a_program_does():
    machine, device = screen(width=4, height=2)
    assert device.base == DEFAULT.data_base


@pytest.mark.parametrize("place, where", [
    ("data", "data_segment_base"), ("global", "global_pointer"),
    ("static", "data_base"), ("heap", "heap_base"), ("devices", "mmio_base"),
])
def test_the_five_places_of_rars(place, where):
    machine, device = screen(place=place, width=4, height=2)
    assert device.base == getattr(DEFAULT, where)


def test_a_place_of_the_configuration_follows_it():
    config = CONFIGS["CompactDataAtZero"]
    machine, device = screen(place="static", width=4, height=2, config=config)
    assert device.base == config.data_base


def test_a_place_can_be_an_address_of_its_own():
    machine, device = screen(place=DEFAULT.data_base + 0x40, width=4, height=2)
    assert device.base == DEFAULT.data_base + 0x40
    machine.memory.write(DEFAULT.data_base + 0x40, 4, 0x010203)
    assert device.unit(0, 0) == 0x010203


def test_a_place_that_is_no_word():
    """As in RARS, where a watched range has to start at a word."""
    with pytest.raises(ValueError, match="starts at a word"):
        screen(place=DEFAULT.data_base + 2, width=2, height=2)


def test_a_place_nobody_knows():
    with pytest.raises(ValueError, match="the picture lies at one of"):
        BitmapDisplay(place="somewhere")
    with pytest.raises(ValueError, match="at least one pixel"):
        BitmapDisplay(width=0)


# ---------------------------------------------------------------- the geometry


def test_how_many_units_the_picture_holds():
    machine, device = screen(width=512, height=256)  # what RARS starts with
    assert (device.columns, device.rows) == (512, 256)
    assert len(device.frame) == 512 * 256

    machine, device = screen(width=64, height=32, unit_width=8, unit_height=4)
    assert (device.columns, device.rows) == (8, 8)


def test_the_units_are_read_row_by_row():
    machine, device = screen(width=3, height=2)
    base = device.base
    for index in range(6):
        machine.memory.write(base + 4 * index, 4, index + 1)
    assert device.units() == [[1, 2, 3], [4, 5, 6]]
    assert device.unit(2, 1) == 6


# ------------------------------------------------------------------ the writing


def test_a_word_written_reaches_the_picture():
    machine, device = screen(width=2, height=2)
    machine.memory.write(device.base + 4, 4, 0x00FF8000)
    assert device.unit(1, 0) == 0x00FF8000


def test_a_word_outside_the_picture_is_no_part_of_it():
    machine, device = screen(width=2, height=2)
    machine.memory.write(device.base + 4 * 4, 4, 0x123456)
    assert list(device.frame) == [0, 0, 0, 0]


def test_a_byte_written_takes_the_whole_word_with_it():
    """RARS reads the word of memory the address belongs to, not the value of the
    access, so a program may paint a unit a byte at a time."""
    machine, device = screen(width=2, height=2)
    machine.memory.write(device.base, 4, 0x00112233)
    machine.memory.write(device.base + 1, 1, 0xEE)  # the second byte from the bottom
    assert device.unit(0, 0) == 0x0011EE33


def test_the_picture_starts_as_the_memory_holds_it():
    """A program whose data is already there sees it from the first moment."""
    base = DEFAULT.data_base
    machine, device = screen(width=2, height=1, before=((base, 0x010000), (base + 4, 2)))
    assert list(device.frame) == [0x010000, 2]


def test_a_reset_reads_the_memory_again():
    machine, device = screen(width=2, height=1)
    machine.memory.poke(device.base, 4, 0x314159)  # nobody was told
    assert list(device.frame) == [0, 0]
    device.reset()
    assert list(device.frame) == [0x314159, 0]


def test_the_range_watched_is_cut_off_at_the_end_of_the_memory():
    """A picture at the area of the devices would run past the last word; RARS cuts
    the range off at 0xfffffffc and so do we."""
    machine, device = screen(place="devices", width=1024, height=1024)
    assert len(device.frame) == 1024 * 1024
    machine.memory.write(0xFFFFFFFC, 4, 0x777)
    assert device.unit(16383, 0) == 0x777  # (0xfffffffc - 0xffff0000) / 4


# ------------------------------------------------------------- what is around


def test_the_colour_of_a_word():
    machine, device = screen(width=1, height=1)
    assert device.colour(0x00FF8040) == (255, 128, 64)
    assert device.colour(0xFF123456) == (0x12, 0x34, 0x56)  # the highest byte is none


def test_a_watcher_is_told_which_unit_changed():
    machine, device = screen(width=2, height=2)
    changes = []
    stop = device.subscribe(changes.append)
    machine.memory.write(device.base + 8, 4, 1)
    assert changes == [2]
    device.reset()
    assert changes[-1] is None  # the whole picture
    stop()
    machine.memory.write(device.base, 4, 1)
    assert changes[-1] is None


def test_the_display_answers_no_address():
    """It is no device of MMIO: a program talks to it by writing into memory."""
    machine, device = screen(width=2, height=2)
    assert machine.memory.bus.devices == []
    assert not hasattr(device, "offset")


def test_the_device_is_known_by_name():
    assert isinstance(make("bitmap"), BitmapDisplay)
    assert make("bitmap", width=64, height=64).columns == 64
