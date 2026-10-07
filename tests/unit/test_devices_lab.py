"""The digital lab: two displays, sixteen keys and the counter.

Expected values are the verified protocol of RARS (R-DEV-DLAB, read from the byte
code of `tools/DigitalLabSim` 2026-10-08): the five byte registers, the table of key
codes, the row that must be asked for EXACTLY, the interrupt 0x200 of a key and
0x100 of the counter, and the period of 31 notices - every instruction carried out
and every access of the four registers the counter watches.
"""

import pytest

from pyrars.core.machine import Machine
from pyrars.core.options import Options
from pyrars.core.simulator import Simulator
from pyrars.devices import DeviceBus, make
from pyrars.devices.lab import (COUNTER, COUNTER_INTERRUPT, DigitalLab, KEYBOARD_KEY,
                                KEYBOARD_ROW, KEY_CODES, KEY_INTERRUPT, LEFT_DISPLAY,
                                PERIOD, RIGHT_DISPLAY)
from pyrars.isa.codec import encode
from pyrars.isa.instructions import find
from pyrars.isa.memory import DEFAULT

MMIO = DEFAULT.mmio_base
TEXT = DEFAULT.text_base
NOP = 0x00000013

# The codes RARS gives the sixteen keys (R-DEV-DLAB), written out as they are there.
CODES_OF_RARS = (0x11, 0x21, 0x41, 0x81, 0x12, 0x22, 0x42, 0x82,
                 0x14, 0x24, 0x44, 0x84, 0x18, 0x28, 0x48, 0x88)


def word(mnemonic: str, xlen: int = 32, **fields: int) -> int:
    return encode(find(mnemonic, xlen), fields)


def lab() -> tuple[Machine, DigitalLab]:
    device = DigitalLab()
    bus = DeviceBus([device])
    machine = Machine(Options(), bus=bus)
    bus.connect(machine)
    return machine, device


def put(machine: Machine, which: int, value: int) -> None:
    machine.memory.write(MMIO + which, 1, value)


def get(machine: Machine, which: int) -> int:
    return machine.memory.read(MMIO + which, 1)


# ------------------------------------------------------------------ the displays


def test_the_two_displays_take_their_segments():
    machine, device = lab()
    put(machine, RIGHT_DISPLAY, 0x7F)
    put(machine, LEFT_DISPLAY, 0x80)
    assert (device.right, device.left) == (0x7F, 0x80)
    assert device.lit(device.right) == ("a", "b", "c", "d", "e", "f", "g")
    assert device.lit(device.left) == ("dot",)


def test_a_display_keeps_the_low_eight_bits():
    """The registers are bytes, but nothing stops a program from writing a word at
    the first of them. RARS then tells only the display of the first register, and
    it lights the segments of the low eight bits (its `paint` walks the bits from
    0 up, a to g and the dot); the other three cells take their bytes of the word
    and no display hears of them."""
    machine, device = lab()
    machine.memory.write(MMIO + RIGHT_DISPLAY, 4, 0x12345678)
    assert device.right == 0x78
    assert device.left == 0  # the left display was not told
    assert machine.memory.peek(MMIO + LEFT_DISPLAY, 1) == 0x56  # though its cell took it


# ------------------------------------------------------------------ the keyboard


def test_the_codes_of_the_keys_are_the_ones_of_rars():
    assert KEY_CODES == CODES_OF_RARS


def test_a_key_is_told_of_when_its_row_is_asked_for():
    machine, device = lab()
    device.press(5)  # the second key of the second row
    assert get(machine, KEYBOARD_KEY) == 0  # nothing until the program asks
    put(machine, KEYBOARD_ROW, 0b0010)  # the second row
    assert get(machine, KEYBOARD_KEY) == 0x22


def test_another_row_tells_nothing():
    machine, device = lab()
    device.press(5)
    put(machine, KEYBOARD_ROW, 0b0001)
    assert get(machine, KEYBOARD_KEY) == 0


def test_asking_for_every_row_at_once_tells_nothing():
    """RARS compares the row asked for with the row of the key, so a mask of
    several rows matches none."""
    machine, device = lab()
    device.press(5)
    put(machine, KEYBOARD_ROW, 0b1111)
    assert get(machine, KEYBOARD_KEY) == 0


@pytest.mark.parametrize("key", range(16))
def test_every_key_in_its_own_row(key):
    machine, device = lab()
    device.press(key)
    put(machine, KEYBOARD_ROW, 1 << (key // 4))
    assert get(machine, KEYBOARD_KEY) == CODES_OF_RARS[key]


def test_a_key_asks_for_attention_where_the_program_said_so():
    machine, device = lab()
    put(machine, KEYBOARD_ROW, 0x80)  # any bit of the high half asks to be told
    assert device.key_interrupts is True
    device.press(3)
    assert machine.pending.external == KEY_INTERRUPT


@pytest.mark.parametrize("row, asks", [(0x00, False), (0x0F, False), (0x10, True),
                                       (0x20, True), (0x40, True), (0x80, True)])
def test_which_rows_ask_to_be_told(row, asks):
    """Any of the four high bits does it, not only the highest."""
    machine, device = lab()
    put(machine, KEYBOARD_ROW, row)
    assert device.key_interrupts is asks
    device.press(0)
    assert (machine.pending.external == KEY_INTERRUPT) is asks


def test_a_key_pressed_again_goes_up():
    machine, device = lab()
    put(machine, KEYBOARD_ROW, 0b0001)
    device.press(0)
    assert get(machine, KEYBOARD_KEY) == 0  # the row was asked for before the press
    put(machine, KEYBOARD_ROW, 0b0001)
    assert get(machine, KEYBOARD_KEY) == 0x11
    device.press(0)  # the same key again: it goes up
    assert device.pressed is None and get(machine, KEYBOARD_KEY) == 0


def test_any_key_releases_the_one_that_is_down():
    """Which is what a row of buttons that stay down does in RARS."""
    machine, device = lab()
    device.press(5)
    device.press(9)
    assert device.pressed is None


def test_a_key_can_be_let_go_of():
    machine, device = lab()
    device.press(5)
    put(machine, KEYBOARD_ROW, 0b0010)
    device.release()
    assert device.pressed is None and get(machine, KEYBOARD_KEY) == 0


def test_a_key_the_keyboard_has_not_got():
    machine, device = lab()
    with pytest.raises(ValueError, match="the keys 0 to 15"):
        device.press(16)


# ------------------------------------------------------------------- the counter


def test_the_counter_starts_and_stops():
    machine, device = lab()
    put(machine, COUNTER, 1)
    # The write itself is a notice, as it is in RARS, so one is gone already.
    assert device.counter_on is True and device.counter == PERIOD - 2
    put(machine, COUNTER, 0)
    assert device.counter_on is False


def test_the_counter_asks_for_attention_every_thirty_first_notice():
    machine, device = lab()
    put(machine, COUNTER, 1)  # the first notice
    device.on_retire(PERIOD - 2)
    assert machine.pending.timer is None
    device.on_retire(1)
    assert machine.pending.timer == COUNTER_INTERRUPT
    assert device.counter == PERIOD - 1  # and it starts over


def test_the_attention_of_the_counter_is_a_timer_event():
    machine, device = lab()
    put(machine, COUNTER, 1)
    device.on_retire(PERIOD)
    assert machine.pending.timer == COUNTER_INTERRUPT
    assert machine.pending.external is None


def test_an_access_of_the_watched_registers_is_a_notice():
    machine, device = lab()
    put(machine, COUNTER, 1)
    before = device.counter
    get(machine, RIGHT_DISPLAY)
    put(machine, LEFT_DISPLAY, 1)
    get(machine, KEYBOARD_ROW)
    get(machine, COUNTER)
    assert device.counter == before - 4


def test_the_register_of_the_key_is_no_notice():
    """The counter of RARS watches 0x10..0x13, and the key is at 0x14."""
    machine, device = lab()
    put(machine, COUNTER, 1)
    before = device.counter
    get(machine, KEYBOARD_KEY)
    put(machine, KEYBOARD_KEY, 0)
    assert device.counter == before


def test_a_counter_that_is_off_counts_nothing():
    machine, device = lab()
    device.on_retire(100)
    get(machine, RIGHT_DISPLAY)
    assert (device.counter, machine.pending.timer) == (0, None)


def test_the_counter_is_counted_by_the_machine_itself():
    machine, device = lab()
    machine.x.write(5, MMIO + COUNTER)
    machine.x.write(6, 1)
    machine.memory.poke(TEXT, 4, word("sb", rs1=5, rs2=6, imm=0))  # start it
    for index in range(1, PERIOD + 2):
        machine.memory.poke(TEXT + 4 * index, 4, NOP)
    simulator = Simulator(machine)
    simulator.step()  # the store is a notice, and so is the instruction itself
    assert device.counter == PERIOD - 3
    for _ in range(PERIOD - 3):
        simulator.step()
    assert machine.pending.timer is None
    simulator.step()
    assert machine.pending.timer == COUNTER_INTERRUPT


# ------------------------------------------------------------------ what is around


def test_the_registers_live_in_memory():
    machine, device = lab()
    put(machine, RIGHT_DISPLAY, 0x7F)
    device.press(2)
    put(machine, KEYBOARD_ROW, 0b0001)
    assert machine.memory.peek(MMIO + RIGHT_DISPLAY, 1) == 0x7F
    assert machine.memory.peek(MMIO + KEYBOARD_KEY, 1) == 0x41


def test_a_reset_empties_everything():
    machine, device = lab()
    put(machine, RIGHT_DISPLAY, 0x7F)
    put(machine, COUNTER, 1)
    device.press(1)
    device.reset()
    assert (device.right, device.left, device.pressed) == (0, 0, None)
    assert (device.counter_on, device.counter, device.key_interrupts) == (False, 0, False)
    assert get(machine, RIGHT_DISPLAY) == 0


def test_a_watcher_is_told_of_a_change():
    machine, device = lab()
    changes = []
    stop = device.subscribe(lambda: changes.append((device.right, device.pressed)))
    put(machine, RIGHT_DISPLAY, 0x06)
    device.press(4)
    assert changes[-1] == (0x06, 4)
    told = len(changes)
    stop()
    device.release()
    assert len(changes) == told


def test_the_device_is_known_by_name():
    assert isinstance(make("lab"), DigitalLab)
