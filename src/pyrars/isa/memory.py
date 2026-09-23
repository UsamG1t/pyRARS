"""Memory configurations: where the segments of a program live.

The three configurations are those of RARS (`MemoryConfigurations.java`); the
assembler needs the bases of the text, data and extern areas, the simulator the
rest. Addresses are unsigned 32-bit numbers.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryConfig:
    name: str  # as the command line writes it
    text_base: int
    data_segment_base: int
    extern_base: int
    global_pointer: int
    data_base: int
    heap_base: int
    stack_pointer: int
    stack_base: int
    user_high: int
    kernel_base: int
    mmio_base: int
    kernel_high: int
    data_segment_limit: int
    text_limit: int
    stack_limit: int
    mmap_limit: int


DEFAULT = MemoryConfig(
    name="Default",
    text_base=0x00400000, data_segment_base=0x10000000, extern_base=0x10000000,
    global_pointer=0x10008000, data_base=0x10010000, heap_base=0x10040000,
    stack_pointer=0x7FFFEFFC, stack_base=0x7FFFFFFC, user_high=0x7FFFFFFF,
    kernel_base=0x80000000, mmio_base=0xFFFF0000, kernel_high=0xFFFFFFFF,
    data_segment_limit=0x7FFFFFFF, text_limit=0x0FFFFFFC, stack_limit=0x10040000,
    mmap_limit=0xFFFFFFFF,
)

COMPACT_DATA_AT_ZERO = MemoryConfig(
    name="CompactDataAtZero",
    text_base=0x00003000, data_segment_base=0x00000000, extern_base=0x00001000,
    global_pointer=0x00001800, data_base=0x00000000, heap_base=0x00002000,
    stack_pointer=0x00002FFC, stack_base=0x00002FFC, user_high=0x00003FFF,
    kernel_base=0x00004000, mmio_base=0x00007F00, kernel_high=0x00007FFF,
    data_segment_limit=0x00002FFF, text_limit=0x00003FFC, stack_limit=0x00002000,
    mmap_limit=0x00007FFF,
)

COMPACT_TEXT_AT_ZERO = MemoryConfig(
    name="CompactTextAtZero",
    text_base=0x00000000, data_segment_base=0x00001000, extern_base=0x00001000,
    global_pointer=0x00001800, data_base=0x00002000, heap_base=0x00003000,
    stack_pointer=0x00003FFC, stack_base=0x00003FFC, user_high=0x00003FFF,
    kernel_base=0x00004000, mmio_base=0x00007F00, kernel_high=0x00007FFF,
    data_segment_limit=0x00003FFF, text_limit=0x00000FFC, stack_limit=0x00003000,
    mmap_limit=0x00007FFF,
)

CONFIGS = {config.name: config for config in (DEFAULT, COMPACT_DATA_AT_ZERO, COMPACT_TEXT_AT_ZERO)}
