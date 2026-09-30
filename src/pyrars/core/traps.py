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
