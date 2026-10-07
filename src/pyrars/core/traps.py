"""Traps and interrupts: what happens when an instruction cannot be carried out,
and what happens when something outside the program asks for attention.

Three slots hold what is waiting - one for an external event, one for a timer
event, one for the trap of an instruction - and while a slot is full a new event
of its kind is dropped, as in RARS. Before every instruction the machine looks at
them in the order of RARS: an external event first, then a software interrupt
(whose bit the program sets in `uip` itself), then a timer event, and only then
the trap of the instruction before.

Taking any of them writes `ucause`, `uepc` and `utval` and goes to the handler at
`utvec`, but only when `ustatus.UIE` is set and something is actually there to
run; otherwise the machine stops and the message of the event is reported. Inside
a handler UIE is clear and UPIE holds what it was, which `uret` puts back.

All of it is verified behaviour of RARS (2026-10-03): the registers a handler
sees, that `uepc` holds the address of the faulting instruction itself, that
`utval` is zero for an illegal instruction, that a second trap inside a handler
stops the machine, that the vectored mode of `utvec` applies to interrupts only,
that a breakpoint never reaches a handler, and that a faulting instruction does
not count as retired.

Sources: R-TRAP and R-SIM-LOOP in `rars-behavior.md`; the cause numbers from the
RISC-V ISA manual v20260120.
"""

from dataclasses import dataclass

from pyrars.isa.registers import CSRS

# Causes of a trap, as they appear in `ucause`.
INSTRUCTION_ADDRESS_MISALIGNED = 0
INSTRUCTION_ACCESS_FAULT = 1
ILLEGAL_INSTRUCTION = 2
BREAKPOINT = 3  # `ebreak`; RARS never gives it to a handler
LOAD_ADDRESS_MISALIGNED = 4
LOAD_ACCESS_FAULT = 5
STORE_ADDRESS_MISALIGNED = 6
STORE_ACCESS_FAULT = 7
ENVIRONMENT_CALL = 8

# Causes of an interrupt: the highest bit tells them from a trap.
SOFTWARE_INTERRUPT = 0x80000000
TIMER_INTERRUPT = 0x80000004
EXTERNAL_INTERRUPT = 0x80000008

# The bits of `uie` and `uip`, and of `ustatus`.
SOFTWARE = 0x001
TIMER = 0x010
EXTERNAL = 0x100
UIE_BIT = 0x01  # interrupts are allowed
UPIE_BIT = 0x10  # whether they were allowed before the handler was entered

NO_HANDLER = "Interrupt handler was not supplied, but interrupt enable was high"

# Which bit of `uip` an interrupt answers: taking it clears that bit, so the same
# interrupt is not taken twice over (verified in RARS 2026-10-03: a handler reads
# `uip` as zero after a software interrupt was taken).
BITS = {SOFTWARE_INTERRUPT: SOFTWARE, TIMER_INTERRUPT: TIMER, EXTERNAL_INTERRUPT: EXTERNAL}


class Trap(Exception):
    """An instruction that cannot be carried out: a refused access, an illegal
    instruction, a call of the environment, a breakpoint. The simulator turns it
    into a trap of the machine, so nothing of this reaches the user (INV-E)."""

    def __init__(self, cause: int, value: int, message: str) -> None:
        super().__init__(message)
        self.cause = cause
        self.value = value
        self.message = message


class Waiting(Exception):
    """`wfi` with nothing to wait for. The simulator stops with a reason of its
    own, and the session carries the machine on when a device raises an interrupt
    (user decision 2026-10-03; RARS blocks its thread for ever here)."""


@dataclass
class Pending:
    """What is waiting to be taken. One slot for each kind: an event that arrives
    while its slot is full is dropped, as in RARS."""

    external: int | None = None  # the value a handler reads in `utval`
    timer: int | None = None
    trap: tuple[int, int, int, str] | None = None  # cause, value, pc, message

    def add_external(self, value: int) -> bool:
        if self.external is not None:
            return False
        self.external = value
        return True

    def add_timer(self, value: int) -> bool:
        if self.timer is not None:
            return False
        self.timer = value
        return True

    def add_trap(self, cause: int, value: int, pc: int, message: str) -> bool:
        if self.trap is not None:
            return False
        self.trap = (cause, value, pc, message)
        return True


@dataclass(frozen=True, slots=True)
class Taken:
    """What the machine did with a waiting event."""

    cause: int
    value: int
    pc: int  # what `uepc` holds: where the machine was when it happened
    handled: bool  # False: the machine must stop, and `message` says why
    message: str


def register(machine, trap: Trap, pc: int) -> bool:
    """Put the trap of an instruction in its slot, to be taken before the next
    one. A breakpoint is no trap of the machine - RARS never gives it to a
    handler - so it is handed back to the caller instead (False)."""
    if trap.cause == BREAKPOINT:
        return False
    # RARS leaves `utval` at zero for an illegal instruction, which the manual
    # allows as well; a refused access puts its address there.
    value = 0 if trap.cause == ILLEGAL_INSTRUCTION else trap.value
    return machine.pending.add_trap(trap.cause, value, pc, trap.message)


def take(machine) -> Taken | None:
    """Look at the waiting events before an instruction is fetched, and take the
    first one that may be taken. Returns None when there is nothing to do."""
    pending = machine.pending
    allowed = bool(machine.csr.read(CSRS["ustatus"]) & UIE_BIT)
    enabled = machine.csr.read(CSRS["uie"])
    asked = machine.csr.read(CSRS["uip"])

    taken = None
    if allowed and pending.external is not None and enabled & EXTERNAL:
        value, pending.external = pending.external, None
        taken = _interrupt(machine, EXTERNAL_INTERRUPT, value)
    elif allowed and asked & SOFTWARE and enabled & SOFTWARE:
        taken = _interrupt(machine, SOFTWARE_INTERRUPT, 0)
    elif allowed and pending.timer is not None and enabled & TIMER:
        value, pending.timer = pending.timer, None
        taken = _interrupt(machine, TIMER_INTERRUPT, value)
    elif pending.trap is not None:
        cause, value, pc, message = pending.trap
        pending.trap = None
        taken = _enter(machine, cause, value, pc,
                       machine.csr.read(CSRS["utvec"]) & ~3, message)

    _show_pending(machine)
    return taken


def _interrupt(machine, cause: int, value: int) -> Taken:
    """An interrupt is taken where the machine stands, and the vectored mode of
    `utvec` sends each cause to its own place."""
    machine.csr.poke("uip", machine.csr.read(CSRS["uip"]) & ~BITS[cause])
    utvec = machine.csr.read(CSRS["utvec"])
    address = utvec & ~3
    if utvec & 3 == 2:
        address += 4 * (cause & 0x7FFFFFFF)
    return _enter(machine, cause, value, machine.x.pc, address, NO_HANDLER)


def _enter(machine, cause: int, value: int, pc: int, address: int,
           message: str) -> Taken:
    """Write what a handler reads and go to it, if there is one to go to."""
    machine.csr.poke("ucause", cause)
    machine.csr.poke("uepc", pc)
    machine.csr.poke("utval", value)
    status = machine.csr.read(CSRS["ustatus"])
    handled = bool(status & UIE_BIT) and _holds_instruction(machine, address)
    if handled:
        machine.csr.poke("ustatus", (status | UPIE_BIT) & ~UIE_BIT)
        machine.x.pc = address & machine.mask
    return Taken(cause, value, pc, handled, message)


def _holds_instruction(machine, address: int) -> bool:
    """Whether there is anything to run at the address of the handler."""
    try:
        return machine.memory.fetch(address) is not None
    except Trap:
        return False


def _show_pending(machine) -> None:
    """The bits of `uip` follow the slots: a program reads there what is waiting
    (R-SIM-LOOP; the software bit belongs to the program and is left alone)."""
    asked = machine.csr.read(CSRS["uip"])
    waiting = ((EXTERNAL if machine.pending.external is not None else 0)
               | (TIMER if machine.pending.timer is not None else 0))
    if asked | waiting != asked:
        machine.csr.poke("uip", asked | waiting)
