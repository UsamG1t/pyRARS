"""The keyboard and the display.

Expected values are the verified protocol of RARS (R-DEV-KBD, read from the byte
code of `tools/KeyboardAndDisplaySimulator` 2026-10-07): the four registers and
their ready and interrupt bits, a key kept until the program reads it, a delay
counted in instructions, the interrupt numbers 0x40 and 0x80, and the two
characters that mean something of their own - 12 clears the display, 7 says where
the next character goes. The size of the display is ours (DEV-56), since the
display of RARS is as large as its window.
"""

import pytest

from pyrars.core.machine import Machine
from pyrars.core.options import Options
from pyrars.core.simulator import Simulator
from pyrars.devices import DeviceBus, make
from pyrars.devices.keyboard import (DISPLAY_INTERRUPT, KEY_INTERRUPT, KeyboardDisplay,
                                     RECEIVER_CONTROL, RECEIVER_DATA, READY, INTERRUPT,
                                     TRANSMITTER_CONTROL, TRANSMITTER_DATA)
from pyrars.isa.codec import encode
from pyrars.isa.instructions import find
from pyrars.isa.memory import DEFAULT

MMIO = DEFAULT.mmio_base
TEXT = DEFAULT.text_base
NOP = 0x00000013


def word(mnemonic: str, xlen: int = 32, **fields: int) -> int:
    return encode(find(mnemonic, xlen), fields)


def keyboard(**options) -> tuple[Machine, KeyboardDisplay]:
    """A machine with the keyboard and display attached."""
    seed = options.pop("seed", None)
    device = KeyboardDisplay(**options)
    bus = DeviceBus([device], seed=seed)
    machine = Machine(Options(), bus=bus)
    bus.connect(machine)
    return machine, device


def tick(device: KeyboardDisplay, count: int = 1) -> None:
    """Instructions have been carried out, as the simulator tells the devices."""
    for _ in range(count):
        device.on_retire(1)


def register(machine: Machine, which: int) -> int:
    """What a program reads from one of the four registers."""
    return machine.memory.read(MMIO + which, 4)


def put(machine: Machine, which: int, value: int) -> None:
    machine.memory.write(MMIO + which, 4, value)


# -------------------------------------------------------------- the keyboard


def test_a_key_typed_waits_until_the_program_reads_it():
    machine, device = keyboard()
    assert device.waiting_for_a_key is True
    device.type_key("x")
    assert register(machine, RECEIVER_CONTROL) == READY
    assert device.waiting_for_a_key is False
    assert register(machine, RECEIVER_DATA) == ord("x")
    assert register(machine, RECEIVER_CONTROL) == 0  # the read took the key
    assert device.waiting_for_a_key is True


def test_only_the_last_key_is_kept():
    """As in RARS: a program that does not read fast enough loses a key."""
    machine, device = keyboard()
    device.type_key("a")
    device.type_key("b")
    assert register(machine, RECEIVER_DATA) == ord("b")


def test_a_key_is_taken_by_its_code_as_well():
    machine, device = keyboard()
    device.type_key(0x1FF)
    assert register(machine, RECEIVER_DATA) == 0xFF  # the low eight bits


def test_a_key_asks_for_attention_only_where_the_program_said_so():
    machine, device = keyboard()
    device.type_key("a")
    assert machine.pending.external is None

    machine, device = keyboard()
    put(machine, RECEIVER_CONTROL, INTERRUPT)
    device.type_key("a")
    assert machine.pending.external == KEY_INTERRUPT
    assert register(machine, RECEIVER_CONTROL) == INTERRUPT | READY


# ------------------------------------------------------------- the display


def test_the_display_is_ready_as_soon_as_it_is_there():
    machine, device = keyboard()
    assert register(machine, TRANSMITTER_CONTROL) == READY


def test_a_write_to_a_control_register_shows_nothing():
    """The program sets its own bits there; only `TxData` holds a character."""
    machine, device = keyboard(delay=1)
    put(machine, TRANSMITTER_CONTROL, INTERRUPT | READY)
    put(machine, RECEIVER_CONTROL, INTERRUPT)
    tick(device, 4)
    assert device.shown() == ""
    assert register(machine, TRANSMITTER_CONTROL) == INTERRUPT | READY
    assert machine.pending.external is None


def test_a_character_appears_when_the_delay_is_over():
    """The instruction that wrote the character does not count, as in RARS: a delay
    of three means three instructions after it."""
    machine, device = keyboard(delay=3)
    put(machine, TRANSMITTER_DATA, ord("A"))
    assert register(machine, TRANSMITTER_CONTROL) == 0  # busy
    tick(device, 3)  # the writing instruction and two after it
    assert device.shown() == ""
    tick(device)
    assert device.shown() == "A"
    assert register(machine, TRANSMITTER_CONTROL) == READY


def test_a_character_written_while_the_display_is_busy_is_lost():
    machine, device = keyboard(delay=2)
    put(machine, TRANSMITTER_DATA, ord("A"))
    put(machine, TRANSMITTER_DATA, ord("B"))
    assert register(machine, TRANSMITTER_DATA) == ord("B")  # the cell took it
    tick(device, 3)
    assert device.shown() == "A"  # but the display never heard of it


def test_the_display_asks_for_attention_only_where_the_program_said_so():
    machine, device = keyboard(delay=1)
    put(machine, TRANSMITTER_DATA, ord("A"))
    tick(device, 2)
    assert machine.pending.external is None

    machine, device = keyboard(delay=1)
    put(machine, TRANSMITTER_CONTROL, INTERRUPT | READY)
    put(machine, TRANSMITTER_DATA, ord("A"))
    tick(device, 2)
    assert machine.pending.external == DISPLAY_INTERRUPT
    assert register(machine, TRANSMITTER_CONTROL) == INTERRUPT | READY


def test_a_character_can_be_shown_at_once_and_still_cost_the_delay():
    machine, device = keyboard(delay=3, show_after_delay=False)
    put(machine, TRANSMITTER_DATA, ord("A"))
    assert device.shown() == "A"
    assert register(machine, TRANSMITTER_CONTROL) == 0
    tick(device, 4)
    assert register(machine, TRANSMITTER_CONTROL) == READY


def test_the_characters_follow_one_another():
    machine, device = keyboard(delay=1)
    for letter in "hi\n":
        put(machine, TRANSMITTER_DATA, ord(letter))
        tick(device, 2)
    assert device.shown() == "hi\n"


# --------------------------------------------------------------- the delay


@pytest.mark.parametrize("technique, expected", [
    ("fixed", 5),
    ("uniform", 4),  # our own stream with the seed 0: randrange(5) + 1
    ("normal", 5),  # int(abs(gauss(0, 1) * 5) + 1) of the same stream
])
def test_how_long_the_delay_is(technique, expected):
    machine, device = keyboard(delay=5, technique=technique, seed=0)
    put(machine, TRANSMITTER_DATA, ord("A"))
    assert device.limit == expected
    tick(device, expected)  # the writing instruction and the ones after it
    assert device.shown() == ""
    tick(device)
    assert device.shown() == "A"


def test_a_drawn_delay_is_drawn_anew_for_every_character():
    machine, device = keyboard(delay=5, technique="normal", seed=0)
    put(machine, TRANSMITTER_DATA, ord("A"))
    first = device.limit
    tick(device, first + 1)
    put(machine, TRANSMITTER_DATA, ord("B"))
    assert (first, device.limit) == (5, 7)  # the stream goes on


def test_a_delay_nobody_knows_is_refused():
    with pytest.raises(ValueError, match="fixed or uniform or normal"):
        KeyboardDisplay(technique="sometimes")
    with pytest.raises(ValueError, match="at least 1"):
        KeyboardDisplay(delay=0)


def test_the_delay_is_counted_by_the_machine_itself():
    """The simulator tells the devices of every instruction carried out, which is
    what replaces the text-fetch observation of RARS."""
    machine, device = keyboard(delay=3)
    machine.x.write(5, MMIO + TRANSMITTER_DATA)
    machine.x.write(6, ord("A"))
    machine.memory.poke(TEXT, 4, word("sw", rs1=5, rs2=6, imm=0))
    for index in range(1, 5):
        machine.memory.poke(TEXT + 4 * index, 4, NOP)
    simulator = Simulator(machine)
    simulator.step()  # the store starts the delay and does not count towards it
    simulator.step()
    simulator.step()
    assert device.shown() == ""
    simulator.step()
    assert device.shown() == "A"


# ---------------------------------------------- the two characters of its own


def test_a_form_feed_clears_the_display():
    machine, device = keyboard(delay=1)
    for code in (ord("a"), 12):
        put(machine, TRANSMITTER_DATA, code)
        tick(device, 2)
    assert device.shown() == ""


def test_the_bell_says_where_the_next_character_goes():
    machine, device = keyboard(delay=1, rows=4, columns=8)
    put(machine, TRANSMITTER_DATA, (3 << 20) | (2 << 8) | 7)
    tick(device, 2)
    assert device.told_where is True and device.place == (3, 2)
    put(machine, TRANSMITTER_DATA, ord("X"))
    tick(device, 2)
    assert device.shown().splitlines()[2] == "   X    "
    assert device.place == (4, 2)


def test_a_place_outside_the_display_is_cut_to_it():
    machine, device = keyboard(delay=1, rows=4, columns=8)
    put(machine, TRANSMITTER_DATA, (100 << 20) | (100 << 8) | 7)
    tick(device, 2)
    assert device.place == (7, 3)


def test_the_place_stands_still_at_the_last_one():
    machine, device = keyboard(delay=1, rows=1, columns=2)
    put(machine, TRANSMITTER_DATA, 7)  # the bell with the place 0, 0
    tick(device, 2)
    for letter in "abc":
        put(machine, TRANSMITTER_DATA, ord(letter))
        tick(device, 2)
    assert device.shown() == "ac"  # the last character overwrote the one before


def test_the_place_moves_to_the_next_row():
    machine, device = keyboard(delay=1, rows=2, columns=2)
    put(machine, TRANSMITTER_DATA, 7)
    tick(device, 2)
    for letter in "abc":
        put(machine, TRANSMITTER_DATA, ord(letter))
        tick(device, 2)
    assert device.shown() == "ab\nc "


def test_switching_to_the_mode_of_places_clears_what_was_there():
    machine, device = keyboard(delay=1, rows=2, columns=4)
    put(machine, TRANSMITTER_DATA, ord("a"))
    tick(device, 2)
    put(machine, TRANSMITTER_DATA, 7)
    tick(device, 2)
    assert device.shown() == "    \n    "


def test_a_form_feed_keeps_the_mode_of_places():
    machine, device = keyboard(delay=1, rows=1, columns=3)
    for code in (7, ord("a"), 12):
        put(machine, TRANSMITTER_DATA, code)
        tick(device, 2)
    assert device.told_where is True and device.shown() == "   "


# ------------------------------------------------------------- what is around


def test_the_registers_live_in_memory():
    """So a dump or the debugger sees them without asking the device."""
    machine, device = keyboard()
    device.type_key("q")
    assert machine.memory.peek(MMIO + RECEIVER_DATA, 4) == ord("q")
    assert machine.memory.peek(MMIO + TRANSMITTER_CONTROL, 4) == READY


def test_a_reset_empties_the_display_and_the_registers():
    machine, device = keyboard(delay=1)
    device.type_key("q")
    put(machine, TRANSMITTER_DATA, ord("a"))
    tick(device, 2)
    device.reset()
    assert device.shown() == ""
    assert register(machine, RECEIVER_CONTROL) == 0
    assert register(machine, TRANSMITTER_CONTROL) == READY
    assert device.counting is False


def test_a_watcher_is_told_of_a_change():
    machine, device = keyboard(delay=1)
    changes = []
    stop = device.subscribe(lambda: changes.append(device.shown()))
    device.type_key("q")
    put(machine, TRANSMITTER_DATA, ord("a"))
    tick(device, 2)
    assert changes[-1] == "a"
    told = len(changes)
    stop()
    device.type_key("w")
    assert len(changes) == told


# ------------------------------------------------------------ the queue of keys


def test_a_keyboard_that_holds_several_keys():
    """Ours alone (DEV-58): RARS keeps one key and loses the rest."""
    machine, device = keyboard(queue=3)
    for letter in "abcd":
        device.type_key(letter)
    assert device.lost == 1  # three fit, the fourth had nowhere to wait
    assert [chr(register(machine, RECEIVER_DATA)) for _ in range(3)] == ["a", "b", "c"]
    assert device.waiting_for_a_key is True


def test_a_key_of_the_queue_follows_the_one_the_program_read():
    machine, device = keyboard(queue=2)
    device.type_key("a")
    device.type_key("b")
    assert register(machine, RECEIVER_CONTROL) == READY
    assert register(machine, RECEIVER_DATA) == ord("a")
    assert register(machine, RECEIVER_CONTROL) == READY  # the next one is there
    assert register(machine, RECEIVER_DATA) == ord("b")
    assert register(machine, RECEIVER_CONTROL) == 0


def test_a_key_of_the_queue_asks_for_attention_as_well():
    machine, device = keyboard(queue=2)
    put(machine, RECEIVER_CONTROL, INTERRUPT)
    device.type_key("a")
    device.type_key("b")
    machine.pending.external = None  # the machine took the first one
    register(machine, RECEIVER_DATA)  # the program reads, the next key comes up
    assert machine.pending.external == KEY_INTERRUPT


def test_a_keyboard_of_one_key_keeps_the_last_as_rars_does():
    machine, device = keyboard(queue=1)
    device.type_key("a")
    device.type_key("b")
    assert (device.keys, device.lost) == ([], 0)
    assert register(machine, RECEIVER_DATA) == ord("b")


def test_whether_another_key_may_be_typed():
    machine, device = keyboard(queue=2)
    assert device.room is True
    device.type_key("a")
    assert device.room is True  # one may still wait
    device.type_key("b")
    assert device.room is False
    register(machine, RECEIVER_DATA)
    assert device.room is True


def test_a_reset_forgets_the_keys_that_waited():
    machine, device = keyboard(queue=3)
    for letter in "abcd":
        device.type_key(letter)
    device.reset()
    assert (device.keys, device.lost) == ([], 0)


def test_a_keyboard_that_holds_nothing():
    with pytest.raises(ValueError, match="at least one key"):
        KeyboardDisplay(queue=0)


def test_the_device_is_known_by_name():
    assert isinstance(make("keyboard"), KeyboardDisplay)
    assert isinstance(make("keyboard", delay=10, technique="uniform"), KeyboardDisplay)
    assert make("keyboard", queue=4).queue == 4
