"""RARS 1.6 as the reference assembler and simulator for devel tests.

RARS is used only through its command line (RARS source: src/rars/Launch.java):

    java -jar rars1_6.jar nc a ae1 dump .text HexText <f> dump .data HexText <f>
                                   dump .text SegmentWindow <f> <options> <files>
    java -jar rars1_6.jar nc ae1 se1 <max steps> <options> <files>

nc   - no copyright banner
a    - assemble only, do not simulate
ae1  - exit code 1 if assembling failed
se1  - exit code 1 if the program failed while running
dump - write a segment to a file; RARS writes no dump files if assembling failed.
"""

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

JAR = Path(__file__).with_name("rars1_6.jar")
JAVA = shutil.which("java")
ASSEMBLY_ERROR_EXIT = 1


def available() -> bool:
    return JAVA is not None and JAR.is_file()


@dataclass(frozen=True)
class ListingRow:
    """One row of the SegmentWindow dump of .text: one 32-bit word."""

    address: int
    code: int
    basic: str  # RARS cuts this column to 29 characters
    line: int | None  # None for the 2nd and later words of an expanded pseudo-instruction
    source: str


@dataclass(frozen=True)
class Message:
    """An error or warning printed by RARS."""

    kind: str  # "Error" or "Warning"
    file: str
    line: int | None
    column: int | None
    text: str


@dataclass(frozen=True)
class Result:
    exit_code: int
    text: list[int]  # .text words
    data: list[int]  # .data words, up to the end of the last used 4 KiB block
    listing: list[ListingRow]
    messages: list[Message]
    stdout: str


def assemble(files: list[Path], options: tuple[str, ...] = ()) -> Result:
    """Assemble files with RARS; options are extra RARS command line arguments."""
    if not available():
        raise RuntimeError("RARS oracle needs `java` in PATH and " + str(JAR))
    with tempfile.TemporaryDirectory() as tmp:
        text_hex = Path(tmp, "text.hex")
        data_hex = Path(tmp, "data.hex")
        text_lst = Path(tmp, "text.lst")
        command = [
            JAVA, "-jar", str(JAR), "nc", "a", f"ae{ASSEMBLY_ERROR_EXIT}",
            "dump", ".text", "HexText", str(text_hex),
            "dump", ".data", "HexText", str(data_hex),
            "dump", ".text", "SegmentWindow", str(text_lst),
            *options,
            *(str(f) for f in files),
        ]
        run = subprocess.run(command, capture_output=True, text=True, timeout=60)
        return Result(
            exit_code=run.returncode,
            text=read_words(text_hex),
            data=read_words(data_hex),
            listing=read_listing(text_lst),
            messages=parse_messages(run.stdout),
            stdout=run.stdout,
        )


@dataclass(frozen=True)
class RunResult:
    exit_code: int
    stdout: str  # what the program printed, plus the messages of RARS
    stderr: str  # a Java stack trace when RARS itself fails
    messages: list[Message]


def run(files: list[Path], options: tuple[str, ...] = (), max_steps: int = 200_000,
        stdin: str = "", timeout: int = 120) -> RunResult:
    """Assemble and run a program with RARS; the program reports through syscalls."""
    if not available():
        raise RuntimeError("RARS oracle needs `java` in PATH and " + str(JAR))
    command = [
        JAVA, "-jar", str(JAR), "nc", f"ae{ASSEMBLY_ERROR_EXIT}", "se1", str(max_steps),
        *options,
        *(str(f) for f in files),
    ]
    done = subprocess.run(command, capture_output=True, text=True, input=stdin, timeout=timeout)
    return RunResult(
        exit_code=done.returncode,
        stdout=done.stdout,
        stderr=done.stderr,
        messages=parse_messages(done.stdout),
    )


def read_words(path: Path) -> list[int]:
    """HexText dump: one word per line, 8 hex digits."""
    if not path.exists():
        return []
    return [int(line, 16) for line in path.read_text().split()]


def read_listing(path: Path) -> list[ListingRow]:
    """SegmentWindow dump of .text (RARS: SegmentWindowDumpFormat.java).

    Header line and an empty line, then one row per word with fixed columns:
    address [0:10], code [12:22], basic [24:53], line [53:58], source [58:].
    """
    if not path.exists():
        return []
    rows = []
    for row in path.read_text().splitlines()[2:]:
        line = row[53:58].strip()
        rows.append(ListingRow(
            address=int(row[0:10], 16),
            code=int(row[12:22], 16),
            basic=row[24:53].rstrip(),
            line=int(line) if line else None,
            source=row[58:],
        ))
    return rows


# RARS: ErrorMessage.generateReport(). The line number may be preceded by a
# macro expansion history ending with "->".
MESSAGE = re.compile(
    r"^(Error|Warning) in (.*?)(?: line (?:\S*->)?(\d+))?(?: column (\d+))?: (.*)$"
)


def parse_messages(stdout: str) -> list[Message]:
    """Messages in RARS output. A message text may span several lines, e.g.
    "<source line>\nInvalid language element: <token>"; it ends at an empty line
    or at the next message.
    """
    messages = []
    continues = False
    for line in stdout.splitlines():
        match = MESSAGE.match(line)
        if match:
            kind, file, line_no, column, text = match.groups()
            messages.append(Message(
                kind=kind,
                file=file,
                line=int(line_no) if line_no else None,
                column=int(column) if column else None,
                text=text,
            ))
            continues = True
        elif line and continues:
            messages[-1] = replace(messages[-1], text=messages[-1].text + "\n" + line)
        else:
            continues = False
    return messages
