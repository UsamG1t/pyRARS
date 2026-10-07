"""The devices of pyRARS: models of what a program can talk to.

A device is named, so that the command line and the interface can ask for it by
name. The table below is the registry, and the built-in devices are put in it at
the end of this module - they know nothing of it themselves. Reading the entry
points of installed packages, which would pick up devices of others as well, comes
when the project becomes installable (decision of 2026-10-07).
"""

from collections.abc import Callable

from pyrars.devices.base import Connection, Device, Interrupts, Model, Part
from pyrars.devices.bus import DeviceBus

__all__ = ["Connection", "Device", "DeviceBus", "Interrupts", "Model", "Part",
           "DEVICES", "register", "make", "names"]

# name -> how to build it. A built-in registers itself when its module is read.
DEVICES: dict[str, Callable[..., Part]] = {}


def register(name: str, factory: Callable[..., Part]) -> None:
    """Make a device known under a name. A name already taken is refused, because
    the command line would have no way of saying which one was meant."""
    if name in DEVICES:
        raise ValueError(f'"{name}": a device of that name is known already')
    DEVICES[name] = factory


def make(name: str, **options: object) -> Part:
    """Build the device of a name. Raises ValueError for a name nobody has."""
    factory = DEVICES.get(name)
    if factory is None:
        known = ", ".join(sorted(DEVICES)) or "none"
        raise ValueError(f'"{name}": no device of that name (known: {known})')
    return factory(**options)


def names() -> tuple[str, ...]:
    return tuple(sorted(DEVICES))


# The built-in devices, each known by its own name. The imports are down here so
# that a device module needs nothing of this one.
from pyrars.devices.bitmap import BitmapDisplay  # noqa: E402
from pyrars.devices.keyboard import KeyboardDisplay  # noqa: E402
from pyrars.devices.lab import DigitalLab  # noqa: E402
from pyrars.devices.timer import Timer  # noqa: E402

for _built_in in (KeyboardDisplay, DigitalLab, Timer, BitmapDisplay):
    register(_built_in.name, _built_in)
