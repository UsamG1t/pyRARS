"""Traps and interrupts: the slots, the order they are taken in, the entry into a
handler, and the way back.

Expected values are the verified behaviour of RARS (R-TRAP, R-SIM-LOOP, and the
probes of 2026-10-03): the registers a handler sees, `uepc` holding the address of
the faulting instruction itself, `utval` being zero for an illegal instruction, a
handler used only while `ustatus.UIE` is set and something is there to run, the
vectored mode of `utvec` applying to interrupts only, and a breakpoint never
reaching a handler.
"""

import pytest

from pyrars.core import traps
from pyrars.core.executor import execute
from pyrars.core.machine import Machine
from pyrars.core.options import Options
from pyrars.core.traps import (EXTERNAL, EXTERNAL_INTERRUPT, SOFTWARE, SOFTWARE_INTERRUPT,
                               TIMER, TIMER_INTERRUPT, UIE_BIT, UPIE_BIT, Pending, Trap,
                               Waiting)
from pyrars.isa.codec import encode
from pyrars.isa.instructions import find
from pyrars.isa.memory import DEFAULT
from pyrars.isa.registers import CSRS

TEXT, DATA = DEFAULT.text_base, DEFAULT.data_base
HANDLER = TEXT + 0x100
NOP = 0x00000013  # addi x0, x0, 0


def word(mnemonic: str, xlen: int = 32, **fields: int) -> int:
    return encode(find(mnemonic, xlen), fields)


def machine(handler: bool = True, allow: bool = True, **csrs: int) -> Machine:
    """A machine with a handler in place (unless told otherwise) and interrupts
    allowed, which is the usual starting point of these tests."""
    m = Machine(Options())
    m.memory.poke(TEXT, 4, NOP)
    if handler:
        m.memory.poke(HANDLER, 4, NOP)
        m.csr.write(CSRS["utvec"], HANDLER)
    if allow:
        m.csr.write(CSRS["ustatus"], UIE_BIT)
    for name, value in csrs.items():
        m.csr.write(CSRS[name], value)
    return m


def read(m: Machine, name: str) -> int:
    return m.csr.read(CSRS[name])


# ------------------------------------------------------------------ the slots


def test_a_slot_holds_one_event_and_drops_the_next():
    pending = Pending()
    assert pending.add_external(0x40) is True
    assert pending.add_external(0x80) is False  # dropped while the slot is full
    assert pending.external == 0x40
    assert pending.add_timer(0x10) is True and pending.add_timer(0x20) is False
    assert pending.add_trap(4, 1, TEXT, "one") is True
    assert pending.add_trap(5, 2, TEXT, "two") is False
    assert pending.trap == (4, 1, TEXT, "one")


def test_a_trap_of_an_instruction_goes_into_its_slot():
    m = machine()
    assert traps.register(m, Trap(traps.LOAD_ACCESS_FAULT, 0x50000000, "out"), TEXT) is True
    assert m.pending.trap == (traps.LOAD_ACCESS_FAULT, 0x50000000, TEXT, "out")


def test_an_illegal_instruction_leaves_no_value_behind():
    """RARS puts zero in `utval` there, which the manual allows (verified)."""
    m = machine()
    traps.register(m, Trap(traps.ILLEGAL_INSTRUCTION, 0x11223344, "undefined"), TEXT)
    assert m.pending.trap[1] == 0


def test_a_breakpoint_is_no_trap_of_the_machine():
    """RARS never gives it to a handler: the caller is told instead."""
    m = machine()
    assert traps.register(m, Trap(traps.BREAKPOINT, 0, "ebreak"), TEXT) is False
    assert m.pending.trap is None


def test_nothing_waiting_means_nothing_to_do():
    assert traps.take(machine()) is None


# ---------------------------------------------------------- entering a handler


def test_a_trap_with_a_handler():
    m = machine()
    traps.register(m, Trap(traps.LOAD_ADDRESS_MISALIGNED, 1, "not aligned"), TEXT + 0x10)
    taken = traps.take(m)
    assert taken.handled and taken.cause == traps.LOAD_ADDRESS_MISALIGNED
    assert read(m, "ucause") == 4
    assert read(m, "uepc") == TEXT + 0x10  # the faulting instruction itself
    assert read(m, "utval") == 1
    assert read(m, "ustatus") == UPIE_BIT  # UIE is gone, UPIE holds what it was
    assert m.x.pc == HANDLER


def test_a_trap_without_interrupts_allowed_stops_the_machine():
    m = machine(allow=False)
    traps.register(m, Trap(traps.LOAD_ADDRESS_MISALIGNED, 1, "not aligned"), TEXT)
    taken = traps.take(m)
    assert not taken.handled and taken.message == "not aligned"
    assert m.x.pc == TEXT  # nothing moved
    assert read(m, "ucause") == 4 and read(m, "utval") == 1  # but the registers are written


def test_a_trap_with_nowhere_to_go_stops_the_machine():
    m = machine(handler=False)  # utvec still zero: no instruction there
    traps.register(m, Trap(traps.STORE_ACCESS_FAULT, 0, "no"), TEXT)
    assert traps.take(m).handled is False


def test_the_low_bits_of_utvec_are_no_part_of_the_address():
    m = machine()
    m.csr.write(CSRS["utvec"], HANDLER | 3)
    traps.register(m, Trap(traps.ILLEGAL_INSTRUCTION, 0, "no"), TEXT)
    assert traps.take(m).handled and m.x.pc == HANDLER


# ------------------------------------------------------------- the interrupts


def test_a_software_interrupt_is_asked_for_by_the_program():
    m = machine(uie=SOFTWARE, uip=SOFTWARE)
    taken = traps.take(m)
    assert taken.handled and taken.cause == SOFTWARE_INTERRUPT
    assert read(m, "ucause") == SOFTWARE_INTERRUPT
    assert read(m, "uepc") == TEXT  # where the machine stood
    assert read(m, "utval") == 0
    # taking it clears the bit, so the same interrupt is not taken twice over
    # (verified in RARS: a handler reads `uip` as zero)
    assert read(m, "uip") & SOFTWARE == 0


def test_an_interrupt_needs_both_its_own_bit_and_the_general_one():
    without_bit = machine(uip=SOFTWARE)
    assert traps.take(without_bit) is None
    without_general = machine(allow=False, uie=SOFTWARE, uip=SOFTWARE)
    assert traps.take(without_general) is None


def test_an_external_event_is_taken_from_its_slot():
    m = machine(uie=EXTERNAL)
    m.pending.add_external(0x40)
    taken = traps.take(m)
    assert taken.cause == EXTERNAL_INTERRUPT and taken.value == 0x40
    assert read(m, "utval") == 0x40 and m.pending.external is None


def test_a_timer_event_is_taken_from_its_slot():
    m = machine(uie=TIMER)
    m.pending.add_timer(0x100)
    assert traps.take(m).cause == TIMER_INTERRUPT
    assert read(m, "utval") == 0x100 and m.pending.timer is None


def test_the_order_the_events_are_taken_in():
    """External first, then a software interrupt, then a timer, then the trap of
    the instruction before (R-SIM-LOOP)."""
    m = machine(uie=EXTERNAL | TIMER | SOFTWARE, uip=SOFTWARE)
    m.pending.add_external(1)
    m.pending.add_timer(2)
    traps.register(m, Trap(traps.ILLEGAL_INSTRUCTION, 0, "no"), TEXT)
    order = []
    for _ in range(4):
        # entering a handler takes the permission away, as `uret` gives it back
        m.csr.write(CSRS["ustatus"], UIE_BIT)
        order.append(traps.take(m).cause)
    assert order == [EXTERNAL_INTERRUPT, SOFTWARE_INTERRUPT, TIMER_INTERRUPT,
                     traps.ILLEGAL_INSTRUCTION]


def test_a_trap_waits_while_an_interrupt_is_taken():
    m = machine(uie=SOFTWARE, uip=SOFTWARE)
    traps.register(m, Trap(traps.LOAD_ACCESS_FAULT, 0, "fault"), TEXT)
    assert traps.take(m).cause == SOFTWARE_INTERRUPT
    assert m.pending.trap is not None  # still waiting


def test_what_is_waiting_shows_in_uip():
    m = machine(uie=0)
    m.pending.add_external(1)
    m.pending.add_timer(2)
    traps.take(m)  # nothing may be taken, but the bits are shown
    assert read(m, "uip") == EXTERNAL | TIMER


def test_the_vectored_mode_sends_each_interrupt_to_its_own_place():
    m = machine(uie=TIMER)
    m.csr.write(CSRS["utvec"], HANDLER | 2)
    m.memory.poke(HANDLER + 4 * 4, 4, NOP)  # the place of the timer cause
    m.pending.add_timer(0)
    assert traps.take(m).handled and m.x.pc == HANDLER + 16


def test_the_vectored_mode_does_not_touch_a_trap():
    """Verified in RARS: the offset by the cause is for interrupts only."""
    m = machine()
    m.csr.write(CSRS["utvec"], HANDLER | 2)
    traps.register(m, Trap(traps.LOAD_ADDRESS_MISALIGNED, 1, "no"), TEXT)
    assert traps.take(m).handled and m.x.pc == HANDLER


# -------------------------------------------------------- the way back, and wfi


def test_uret_puts_back_what_was_allowed():
    m = machine()
    m.memory.poke(TEXT, 4, word("uret"))
    traps.register(m, Trap(traps.ILLEGAL_INSTRUCTION, 0, "no"), TEXT)
    traps.take(m)
    assert read(m, "ustatus") == UPIE_BIT
    m.csr.poke("uepc", TEXT + 0x40)
    m.x.pc = TEXT
    execute(m, m.fetch())
    assert read(m, "ustatus") == UIE_BIT  # allowed again, UPIE cleared
    assert m.x.pc == TEXT + 0x40


def test_uret_from_a_handler_entered_while_nothing_was_allowed():
    m = machine(allow=False)
    m.memory.poke(TEXT, 4, word("uret"))
    m.csr.poke("uepc", TEXT + 0x40)
    execute(m, m.fetch())
    assert read(m, "ustatus") == 0 and m.x.pc == TEXT + 0x40


def test_wfi_waits_when_there_is_nothing_to_wait_for():
    m = machine()
    m.memory.poke(TEXT, 4, word("wfi"))
    with pytest.raises(Waiting):
        execute(m, m.fetch())


@pytest.mark.parametrize("kind", ["external", "timer"])
def test_wfi_carries_on_when_something_is_already_waiting(kind):
    m = machine()
    m.memory.poke(TEXT, 4, word("wfi"))
    getattr(m.pending, f"add_{kind}")(1)
    execute(m, m.fetch())
    assert m.x.pc == TEXT + 4


def test_a_software_interrupt_does_not_wake_wfi():
    """RARS waits for an external or a timer event only (verified)."""
    m = machine(uie=SOFTWARE, uip=SOFTWARE)
    m.memory.poke(TEXT, 4, word("wfi"))
    with pytest.raises(Waiting):
        execute(m, m.fetch())
