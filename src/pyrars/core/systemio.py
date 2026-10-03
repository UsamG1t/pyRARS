"""How a program reaches the world outside the machine.

A program asks for input and output with `ecall`; `core/syscalls.py` turns those
requests into the few operations of this protocol, and what they do then is the
business of the implementation. The console one below reads and writes text
streams, the user interface will put them in its own windows, and a test gives one
that remembers what it was asked for instead of doing it - which is how a program
that sleeps costs a test no time at all.

The file descriptors follow the convention of the system: 0, 1 and 2 are the
input, the output and the error stream of the program, and an opened file takes
the lowest free number from 3 up. An operation that fails raises `OSError`, whose
number the service turns into a negative result (user decision 2026-10-03: the
convention of the standard, where RARS answers -1 to everything).

The flags of `open` are those of the standard: 0 read, 1 write, 2 read and write,
9 (write and append). RARS documents the first, the second and the fourth; the
third costs nothing and breaks nothing (D20).
"""

import errno
import os
import sys
import time
from enum import StrEnum
from typing import IO, Protocol

# What a program asks of a dialog, and what it gets back:
#   MESSAGE  -> None; the text to show is the whole message
#   CONFIRM  -> 0 yes, 1 no, 2 cancel
#   INTEGER, FLOAT, DOUBLE -> (number, status)
#   STRING   -> (text, status)
# A status is 0 when something was read, -1 when it was no number, -2 when the
# answer was cancelled (the input ended) and -3 when nothing was entered.
Dialog = StrEnum("Dialog", ["MESSAGE", "CONFIRM", "INTEGER", "FLOAT", "DOUBLE", "STRING"])

STANDARD_INPUT = 0
STANDARD_OUTPUT = 1
STANDARD_ERROR = 2
FIRST_FILE = 3

# The flags of `open` that have a meaning here, and the mode each one opens with.
MODES = {0: "rb", 1: "wb", 2: "r+b", 9: "ab"}


class SystemIO(Protocol):
    """What the services of a program need from the world around the machine."""

    def write(self, fd: int, data: bytes) -> int: ...

    def read(self, fd: int, count: int) -> bytes: ...

    def read_line(self) -> str: ...

    def open(self, path: str, flags: int) -> int: ...

    def close(self, fd: int) -> None: ...

    def lseek(self, fd: int, offset: int, whence: int) -> int: ...

    def sleep(self, milliseconds: int) -> None: ...

    def cwd(self) -> str: ...

    def dialog(self, kind: Dialog, message: str, payload: object) -> object: ...


class ConsoleIO:
    """The world as a text session: two streams out, one in, and real files."""

    def __init__(self, out: IO[str] | None = None, errors: IO[str] | None = None,
                 reader: IO[str] | None = None) -> None:
        self.out = out if out is not None else sys.stdout
        self.errors = errors if errors is not None else sys.stderr
        self.reader = reader if reader is not None else sys.stdin
        self.files: dict[int, IO[bytes]] = {}

    # ------------------------------------------------------------- the streams

    def write(self, fd: int, data: bytes) -> int:
        if fd == STANDARD_OUTPUT:
            self.out.write(data.decode("utf-8", "replace"))
            return len(data)
        if fd == STANDARD_ERROR:
            self.errors.write(data.decode("utf-8", "replace"))
            return len(data)
        return self._file(fd).write(data)

    def read(self, fd: int, count: int) -> bytes:
        if fd == STANDARD_INPUT:
            return self.reader.read(count).encode()
        return self._file(fd).read(count)

    def read_line(self) -> str:
        """One line of the input, with its newline where there was one; the text
        is empty at the end of the input."""
        return self.reader.readline()

    # --------------------------------------------------------------- the files

    def open(self, path: str, flags: int) -> int:
        mode = MODES.get(flags)
        if mode is None:
            raise OSError(errno.EINVAL, os.strerror(errno.EINVAL), path)
        file = open(path, mode)  # noqa: SIM115 - the program closes it
        fd = FIRST_FILE
        while fd in self.files:
            fd += 1
        self.files[fd] = file
        return fd

    def close(self, fd: int) -> None:
        self.files.pop(self._known(fd)).close()

    def lseek(self, fd: int, offset: int, whence: int) -> int:
        if whence not in (os.SEEK_SET, os.SEEK_CUR, os.SEEK_END):
            raise OSError(errno.EINVAL, os.strerror(errno.EINVAL))
        return self._file(fd).seek(offset, whence)

    def _file(self, fd: int) -> IO[bytes]:
        return self.files[self._known(fd)]

    def _known(self, fd: int) -> int:
        if fd not in self.files:
            raise OSError(errno.EBADF, os.strerror(errno.EBADF))
        return fd

    # ---------------------------------------------------------- time, dialogs

    def sleep(self, milliseconds: int) -> None:
        time.sleep(milliseconds / 1000)

    def cwd(self) -> str:
        return os.getcwd()

    def dialog(self, kind: Dialog, message: str, payload: object) -> object:
        """A dialog in a text session is the console: a message is printed, a
        question is printed and the answer read from the input."""
        if kind is Dialog.MESSAGE:
            self.out.write(message)
            return None
        self.out.write(message)
        answer = self.read_line()
        if not answer:  # the input ended: as if the dialog had been cancelled
            return 2 if kind is Dialog.CONFIRM else ("", -2)
        answer = answer.strip()
        if kind is Dialog.CONFIRM:
            return {"y": 0, "yes": 0, "n": 1, "no": 1}.get(answer.lower(), 2)
        if not answer:
            return ("", -3)
        return (answer, 0)
