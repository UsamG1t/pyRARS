"""Cause codes of the traps.

The numbers are those of the `ucause` register (RISC-V ISA manual v20260120, the
table of exception causes; RARS uses the same ones). The machinery around them -
the pending slots, the priority and the entry into a handler - is built in stage
19; what exists here is what the memory needs to say why an access failed.
"""

INSTRUCTION_ADDRESS_MISALIGNED = 0
INSTRUCTION_ACCESS_FAULT = 1
ILLEGAL_INSTRUCTION = 2
LOAD_ADDRESS_MISALIGNED = 4
LOAD_ACCESS_FAULT = 5
STORE_ADDRESS_MISALIGNED = 6
STORE_ACCESS_FAULT = 7
ENVIRONMENT_CALL = 8


class Trap(Exception):
    """An instruction that cannot be carried out: a refused access, an illegal
    instruction, a call of the environment. The simulator turns it into a trap of
    the machine, writing `cause` into ucause and `value` into utval, so nothing
    of this reaches the user of the machine (INV-E).
    """

    def __init__(self, cause: int, value: int, message: str) -> None:
        super().__init__(message)
        self.cause = cause
        self.value = value
        self.message = message
