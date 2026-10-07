"""The bus: which device answers which address, and who hears of what.

`core/memory.py` sends every access of the device area to a `Bus`; this is that
bus. It keeps the map of addresses, hands an access to the device whose range holds
it, and answers from plain memory where no device stands - which is what RARS does
when no tool is connected.

The bus is built empty, handed to the machine, and `connect(machine)` then gives
every device its `Connection`. From that moment on the simulator tells the bus of
every instruction carried out, and the bus passes that on to the devices that asked
for it (`counts`), because that loop runs on every instruction.

Sources: the decisions of 2026-10-07 in the M5 entry of the architecture spec.
"""

import random
from collections.abc import Iterable, Sequence

from pyrars.core.memory import ADDRESS_MASK, Memory
from pyrars.devices.base import Connection, Device, Interrupts, Part


class DeviceBus:
    """The devices of one machine."""

    def __init__(self, devices: Iterable[Part] = (), seed: int | None = None) -> None:
        self.parts: list[Part] = []
        self.devices: list[Device] = []  # the ones that answer addresses
        self.seed = seed
        self.connection: Connection | None = None
        self._counting: tuple[Part, ...] = ()
        self._memory: Memory | None = None
        for device in devices:
            self.add(device)

    # ------------------------------------------------------------- building

    def add(self, device: Part) -> Part:
        """Attach a device. A range that runs outside the area of the devices, or
        over the range of a device already there, is refused: an address answered by
        two devices has no meaning."""
        offset = getattr(device, "offset", None)
        if offset is not None:
            self._check(device)
            self.devices.append(device)
        self.parts.append(device)
        if self.connection is not None:  # attached to a machine already
            device.connect(self.connection)
        self._counting = tuple(part for part in self.parts if part.counts)
        return device

    def _check(self, device: Device) -> None:
        if device.offset < 0 or device.size <= 0:
            raise ValueError(f"{device.name}: a range of {device.size} bytes "
                             f"at the offset {device.offset}")
        for other in self.devices:
            if (device.offset < other.offset + other.size
                    and other.offset < device.offset + device.size):
                raise ValueError(f"{device.name} and {other.name} answer the same "
                                 f"addresses")
        if self.connection is not None:
            self._fits(device, self.connection)

    def _fits(self, device: Device, connection: Connection) -> None:
        config = connection.config
        last = config.mmio_base + device.offset + device.size - 1
        if last > config.mmap_limit:
            raise ValueError(f"{device.name}: its range ends at 0x{last:08x}, past "
                             f"the area of the devices of {config.name}")

    def connect(self, machine) -> None:
        """Give every device what it may reach of the machine."""
        self.connection = Connection(
            interrupts=Interrupts(machine.pending),
            memory=machine.memory,
            csr=machine.csr,
            clock=machine.csr.clock,
            random=random.Random(self.seed),
            config=machine.options.config,
        )
        self._memory = machine.memory
        for device in self.devices:
            self._fits(device, self.connection)
        for part in self.parts:
            part.connect(self.connection)

    # ---------------------------------------------------- what a program does

    def read(self, address: int, size: int) -> int:
        device = self._at(address)
        if device is None:  # nobody answers here: plain memory, as in RARS
            return self._cell(address, size)
        return device.read(address, size)

    def write(self, address: int, size: int, value: int) -> None:
        device = self._at(address)
        if device is None:
            self._poke(address, size, value)
            return
        device.write(address, size, value)

    def _at(self, address: int) -> Device | None:
        base = self.connection.config.mmio_base if self.connection else 0
        for device in self.devices:
            start = base + device.offset
            if start <= address < start + device.size:
                return device
        return None

    def _cell(self, address: int, size: int) -> int:
        return 0 if self._memory is None else self._memory.peek(address, size)

    def _poke(self, address: int, size: int, value: int) -> None:
        if self._memory is not None:
            self._memory.poke(address & ADDRESS_MASK, size, value)

    # ------------------------------------------------- what the machine does

    def on_retire(self, count: int = 1) -> None:
        """Instructions have been carried out: the devices that count hear of it."""
        for part in self._counting:
            part.on_retire(count)

    def reset(self) -> None:
        for part in self.parts:
            part.reset()
