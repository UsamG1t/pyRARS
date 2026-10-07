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

A world can also be asked where it stands (`mark`) and to go back there
(`rewind`), which is how a step back of `core/history.py` takes the world with
it under a debugger: what the program read is handed out again, the files stand
where they stood, and text the world owns is taken back. The record is kept
whatever the machine does with it; `Options.debug` only decides whether a step
back reads it (user decision 2026-10-04). What has really left - a line on a
terminal, bytes written into a file, a file opened or closed - stays as it is.
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

    def mark(self) -> object: ...

    def rewind(self, mark: object) -> None: ...


class ConsoleIO:
    """The world as a text session: two streams out, one in, and real files."""

    def __init__(self, out: IO[str] | None = None, errors: IO[str] | None = None,
                 reader: IO[str] | None = None) -> None:
        self.out = out if out is not None else sys.stdout
        self.errors = errors if errors is not None else sys.stderr
        self.reader = reader if reader is not None else sys.stdin
        self.files: dict[int, IO[bytes]] = {}
        self.taken = ""  # everything read from the input, kept for a step back
        self.cursor = 0  # how much of it the program has read

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
            return self._input(count).encode()
        return self._file(fd).read(count)

    def read_line(self) -> str:
        """One line of the input, with its newline where there was one; the text
        is empty at the end of the input."""
        end = self.taken.find("\n", self.cursor)
        if end >= 0:  # a line the program has read before and read back
            line = self.taken[self.cursor:end + 1]
        else:
            line = self.taken[self.cursor:] + self.reader.readline()
            self.taken = self.taken[:self.cursor] + line
        self.cursor += len(line)
        return line

    def _input(self, count: int) -> str:
        """Characters of the input: those the program has read before first, the
        rest from the reader. Everything read is kept, so that a step back can
        hand it out again."""
        text = self.taken[self.cursor:self.cursor + count]
        if len(text) < count:
            more = self.reader.read(count - len(text))
            self.taken += more
            text += more
        self.cursor += len(text)
        return text

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

    # ------------------------------------------------------ going back with a step

    def mark(self) -> object:
        """Where the world stands: what the program has read, how much has been
        written, and where every open file is."""
        return (self.cursor, _position(self.out), _position(self.errors),
                {fd: file.tell() for fd, file in self.files.items()})

    def rewind(self, mark: object) -> None:
        """Back to a mark: what was read is handed out again, the files go back to
        where they were, and written text is taken back where the world owns it -
        a buffer can be cut, a terminal cannot. Bytes already in a file stay, so a
        program run forward again writes the same bytes in the same place."""
        cursor, out, errors, positions = mark
        self.cursor = cursor
        _cut(self.out, out)
        _cut(self.errors, errors)
        for fd, place in positions.items():
            file = self.files.get(fd)  # a file closed since is simply gone
            if file is not None:
                file.seek(place)


def _position(stream: IO[str]) -> int | None:
    """How much of a stream has been written, where that can be told at all."""
    try:
        return stream.tell() if stream.seekable() else None
    except (OSError, ValueError):
        return None


def _cut(stream: IO[str], length: int | None) -> None:
    """Take back the text of an undone step, where the world owns it."""
    if length is None:
        return
    try:
        stream.seek(length)
        stream.truncate()
    except (OSError, ValueError):
        pass
