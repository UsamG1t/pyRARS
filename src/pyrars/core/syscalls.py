"""The services a program asks for with `ecall`: the forty-one of RARS.

The numbers are those of RARS (`Syscall.properties` in its jar). Seven of them -
17, 57, 62, 63, 64, 93 and 1024 - are the numbers of the system itself, which RARS
took from Spike and the tools of Linux, and they keep the conventions of the
standard: the flags of `open`, the three places `lseek` counts from, the
descriptors 0, 1 and 2 of the streams, and a negative error number when something
fails. The rest come from MARS and have no standard behind them.

Two decisions shape them (D20, user decision 2026-10-03):
  - every service works with values as wide as the machine, because the
    convention of the standard (`syscall(2)`: the number in a7, the arguments in
    a0..a5, the result in a0) speaks of registers, and the registers of a 64-bit
    machine are 64 bits wide. Splitting a value across a pair of registers is what
    a 32-bit machine has to do, so `Time` gives the whole count in a0 on a 64-bit
    machine and leaves a1 at zero - which still answers a program that puts the
    pair together itself. RARS reads only the low 32 bits everywhere, by its own
    admission;
  - a service that fails gives back the negative of its error number, where RARS
    answers -1 to everything.
The dialogs of a window system become the console in a text session (user decision
2026-10-03): a message is printed, a question is printed and its answer read.

The message of a service that cannot do what it was asked keeps the words of RARS
(D10) in the shape every message of the machine has (DEV-54): `Invalid integer
input (syscall 5)` and its relatives, and `Invalid or unimplemented syscall
service 777` for a number nobody serves.
"""

import os
import random

from pyrars.core import traps
from pyrars.core.history import Kind
from pyrars.core.regs import as_signed
from pyrars.core.systemio import Dialog
from pyrars.core.traps import Trap
from pyrars.softfloat.formats import BINARY32, BINARY64
from pyrars.softfloat.rounding import RNE, round_value
from pyrars.softfloat.text import from_text, to_text

# The registers the services use, by number.
A0, A1, A2, A7 = 10, 11, 12, 17
FA0, FA1 = 10, 11


class Exited(Exception):
    """The program asked to stop (services 10 and 93)."""

    def __init__(self, code: int) -> None:
        super().__init__(f"exit {code}")
        self.code = code


def call(machine) -> None:
    """Carry out the service the program named in a7."""
    number = machine.x.read(A7)
    service = SERVICES.get(number)
    if service is None:
        raise Trap(traps.ENVIRONMENT_CALL, 0,
                   f"Invalid or unimplemented syscall service {number}")
    service(machine)


# --------------------------------------------------------------- the pieces


def _text(machine, address: int) -> str:
    """A string of memory, up to its zero byte."""
    letters = bytearray()
    while True:
        byte = machine.memory.read(address, 1)
        if byte == 0:
            return letters.decode("utf-8", "replace")
        letters.append(byte)
        address = (address + 1) & machine.mask


def _keep(machine, address: int, text: str, room: int) -> None:
    """Put a string in a buffer of `room` bytes, the zero byte included."""
    if room <= 0:
        return
    machine.memory.write_bytes(address, text.encode()[:room - 1] + b"\0")


def _say(machine, text: str) -> None:
    machine.io.write(1, text.encode())


def _number(machine, text: str, service: int, kind: str) -> int:
    """A whole number read from the input, or the message of RARS."""
    try:
        return int(text.strip())
    except ValueError:
        raise Trap(traps.ENVIRONMENT_CALL, 0,
                   f"Invalid {kind} input (syscall {service})") from None


def _real(machine, text: str, service: int, kind: str, fmt) -> int:
    try:
        return from_text(text.strip(), fmt)[0]
    except ValueError:
        raise Trap(traps.ENVIRONMENT_CALL, 0,
                   f"Invalid {kind} input (syscall {service})") from None


def _result(machine, call) -> None:
    """Carry out something of the world and put its answer in a0: the negative of
    the error number when it fails (the convention of the standard)."""
    try:
        answer = call()
    except OSError as problem:
        answer = -(problem.errno or 0)
    machine.x.write(A0, answer if answer is not None else 0)


def _generator(machine, index: int) -> random.Random:
    return _keep_stream(machine, index)


def _keep_stream(machine, index: int) -> random.Random:
    """The stream of an index, written down before it moves on so that a step
    back gives the same number again (DEV-51; RARS does not).

    The stream is made before it is written down, so that taking a step back
    puts a state back instead of leaving a stream to be made anew - which would
    draw from a new seed and give another number.
    """
    stream = machine.generators.setdefault(index, random.Random())
    if machine.history is not None:
        machine.history.record(Kind.RANDOM, index, (stream, stream.getstate()))
    return stream


# ------------------------------------------------------------- what is printed


def _print_int(machine) -> None:
    _say(machine, str(machine.x.signed(A0)))


def _print_float(machine) -> None:
    _say(machine, to_text(machine.f.single(FA0), BINARY32))


def _print_double(machine) -> None:
    _say(machine, to_text(machine.f.double(FA0), BINARY64))


def _print_string(machine) -> None:
    _say(machine, _text(machine, machine.x.read(A0)))


def _print_char(machine) -> None:
    _say(machine, chr(machine.x.read(A0) & 0xFF))


def _print_hex(machine) -> None:
    _say(machine, f"0x{machine.x.read(A0):0{machine.xlen // 4}x}")


def _print_binary(machine) -> None:
    _say(machine, f"{machine.x.read(A0):0{machine.xlen}b}")


def _print_unsigned(machine) -> None:
    _say(machine, str(machine.x.read(A0)))


# --------------------------------------------------------------- what is read


def _read_int(machine) -> None:
    machine.x.write(A0, _number(machine, machine.io.read_line(), 5, "integer"))


def _read_float(machine) -> None:
    machine.f.set_single(FA0, _real(machine, machine.io.read_line(), 6, "float", BINARY32))


def _read_double(machine) -> None:
    machine.f.set_double(FA0, _real(machine, machine.io.read_line(), 7, "double", BINARY64))


def _read_char(machine) -> None:
    letter = machine.io.read(0, 1)
    if not letter:
        raise Trap(traps.ENVIRONMENT_CALL, 0, "Invalid char input (syscall 12)")
    machine.x.write(A0, letter[0])


def _read_string(machine) -> None:
    """A line into a buffer: at most room for the zero byte less, and the newline
    of a line that fitted is kept, as in RARS."""
    room = machine.x.read(A1)
    _keep(machine, machine.x.read(A0), machine.io.read_line(), room)


# ----------------------------------------------------------- the machine itself


def _sbrk(machine) -> None:
    """Hand out the next piece of the heap and remember where it ends."""
    amount = machine.x.signed(A0)
    machine.x.write(A0, machine.heap)
    machine.heap = (machine.heap + amount) & machine.mask


def _exit(machine) -> None:
    raise Exited(0)


def _exit2(machine) -> None:
    raise Exited(machine.x.signed(A0))


def _cwd(machine) -> None:
    """The path of the working directory, or -1 when the buffer is too small."""
    path = machine.io.cwd().encode()
    if len(path) + 1 > machine.x.read(A1):
        machine.x.write(A0, -1)
        return
    machine.memory.write_bytes(machine.x.read(A0), path + b"\0")


def _time(machine) -> None:
    """The milliseconds since the epoch. A 64-bit machine takes the whole count in
    a0 and reads a1 as zero; a 32-bit one takes the halves apart."""
    milliseconds = machine.csr.clock()
    if machine.xlen >= 64:
        machine.x.write(A0, milliseconds)
        machine.x.write(A1, 0)
    else:
        machine.x.write(A0, milliseconds & 0xFFFFFFFF)
        machine.x.write(A1, (milliseconds >> 32) & 0xFFFFFFFF)


def _sleep(machine) -> None:
    machine.io.sleep(machine.x.read(A0))


def _midi(machine) -> None:
    """No sound: the services of MIDI are answered and nothing is played
    (OPEN-2)."""


# ---------------------------------------------------------- the random numbers


def _rand_seed(machine) -> None:
    index = machine.x.read(A0)
    _keep_stream(machine, index)
    machine.generators[index] = random.Random(machine.x.signed(A1))


def _rand_int(machine) -> None:
    machine.x.write(A0, _generator(machine, machine.x.read(A0)).getrandbits(machine.xlen))


def _rand_range(machine) -> None:
    """A number below the bound, as RARS gives it (its own text says the bound is
    included, its behaviour says it is not; the common convention agrees with the
    behaviour)."""
    bound = machine.x.signed(A1)
    generator = _generator(machine, machine.x.read(A0))
    machine.x.write(A0, generator.randrange(bound) if bound > 0 else 0)


def _rand_real(machine, fmt) -> int:
    """A value of [0, 1) picked as a whole number of steps of the format: as many
    bits as the significand holds, which needs no rounding and no host float."""
    bits = fmt.significand_bits + 1
    steps = _generator(machine, machine.x.read(A0)).getrandbits(bits)
    return round_value(False, -bits, steps, fmt, RNE)[0]


def _rand_float(machine) -> None:
    machine.f.set_single(FA0, _rand_real(machine, BINARY32))


def _rand_double(machine) -> None:
    machine.f.set_double(FA0, _rand_real(machine, BINARY64))


# ---------------------------------------------------------------- the dialogs


def _confirm(machine) -> None:
    message = _text(machine, machine.x.read(A0))
    machine.x.write(A0, machine.io.dialog(Dialog.CONFIRM, message, None))


def _input_number(machine, kind: Dialog) -> None:
    """A question that wants a number: a0 (or fa0) takes it and a1 the status."""
    message = _text(machine, machine.x.read(A0))
    answer, status = machine.io.dialog(kind, message, None)
    if status:
        machine.x.write(A0, 0)
        machine.x.write(A1, status)
        return
    try:
        if kind is Dialog.INTEGER:
            machine.x.write(A0, int(answer))
        else:
            fmt = BINARY32 if kind is Dialog.FLOAT else BINARY64
            bits = from_text(answer, fmt)[0]
            (machine.f.set_single if kind is Dialog.FLOAT else machine.f.set_double)(FA0, bits)
    except ValueError:
        machine.x.write(A0, 0)
        machine.x.write(A1, -1)  # the answer was no number
        return
    machine.x.write(A1, 0)


def _input_string(machine) -> None:
    """A question that wants a string: the buffer takes it, a1 the status, and a
    text longer than the buffer is cut with the status -4."""
    message = _text(machine, machine.x.read(A0))
    answer, status = machine.io.dialog(Dialog.STRING, message, None)
    room = machine.x.read(A2)
    if status:
        machine.x.write(A1, status)
        return
    _keep(machine, machine.x.read(A1), answer, room)
    machine.x.write(A1, -4 if len(answer.encode()) + 1 > room else 0)


def _show(machine, text: str) -> None:
    """A message of a dialog: the interface will have a window for it, the console
    simply prints it."""
    machine.io.dialog(Dialog.MESSAGE, text, None)


def _message(machine) -> None:
    _show(machine, _text(machine, machine.x.read(A0)))


def _message_int(machine) -> None:
    _show(machine, _text(machine, machine.x.read(A0)) + str(machine.x.signed(A1)))


def _message_string(machine) -> None:
    _show(machine, _text(machine, machine.x.read(A0)) + _text(machine, machine.x.read(A1)))


def _message_float(machine) -> None:
    _show(machine, _text(machine, machine.x.read(A0))
          + to_text(machine.f.single(FA1), BINARY32))


def _message_double(machine) -> None:
    _show(machine, _text(machine, machine.x.read(A0))
          + to_text(machine.f.double(FA0), BINARY64))


# ----------------------------------------------------------------- the files


def _open(machine) -> None:
    path = _text(machine, machine.x.read(A0))
    flags = machine.x.read(A1)
    _result(machine, lambda: machine.io.open(path, flags))


def _close(machine) -> None:
    fd = machine.x.read(A0)
    _result(machine, lambda: machine.io.close(fd))


def _lseek(machine) -> None:
    fd, offset, whence = machine.x.read(A0), machine.x.signed(A1), machine.x.read(A2)
    _result(machine, lambda: machine.io.lseek(fd, offset, whence))


def _read_file(machine) -> None:
    fd, address, count = machine.x.read(A0), machine.x.read(A1), machine.x.read(A2)

    def read() -> int:
        data = machine.io.read(fd, count)
        machine.memory.write_bytes(address, data)
        return len(data)

    _result(machine, read)


def _write_file(machine) -> None:
    fd, address, count = machine.x.read(A0), machine.x.read(A1), machine.x.read(A2)
    data = machine.memory.read_bytes(address, count)
    _result(machine, lambda: machine.io.write(fd, data))


SERVICES = {
    1: _print_int, 2: _print_float, 3: _print_double, 4: _print_string,
    5: _read_int, 6: _read_float, 7: _read_double, 8: _read_string,
    9: _sbrk, 10: _exit, 11: _print_char, 12: _read_char,
    17: _cwd, 30: _time, 31: _midi, 32: _sleep, 33: _midi,
    34: _print_hex, 35: _print_binary, 36: _print_unsigned,
    40: _rand_seed, 41: _rand_int, 42: _rand_range, 43: _rand_float, 44: _rand_double,
    50: _confirm,
    51: lambda machine: _input_number(machine, Dialog.INTEGER),
    52: lambda machine: _input_number(machine, Dialog.FLOAT),
    53: lambda machine: _input_number(machine, Dialog.DOUBLE),
    54: _input_string,
    55: _message, 56: _message_int, 57: _close, 58: _message_double,
    59: _message_string, 60: _message_float,
    62: _lseek, 63: _read_file, 64: _write_file, 93: _exit2, 1024: _open,
}
