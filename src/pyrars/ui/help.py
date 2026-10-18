"""What one word of a program is, told from the tables that assemble it.

The editor shows this when the pointer rests on a word. Everything in it comes
from `pyrars.isa` and `pyrars.asm` - the forms an instruction takes, what a
pseudo-instruction turns into, which register answers to which name - so there is
no second description of anything to go stale, and no prose borrowed from anybody.

Nothing here imports `gi`: it is words about words.
"""

from dataclasses import dataclass

from pyrars.asm import pseudo
from pyrars.asm.directives import MANUAL_DIRECTIVES, RARS_DIRECTIVES
from pyrars.isa.instructions import find, instructions
from pyrars.isa.registers import CSRS, F_NAMES, X_ALIASES, X_NAMES

INSTRUCTION = "instruction"
PSEUDO = "pseudo-instruction"
DIRECTIVE = "directive"
REGISTER = "register"
FLOAT = "floating point register"
CONTROL = "control register"


@dataclass(frozen=True, slots=True)
class About:
    """What a word is, as a window tells it."""

    word: str
    kind: str
    about: str  # one line, which is what a tooltip shows first
    forms: tuple[str, ...] = ()  # how it is written
    becomes: tuple[str, ...] = ()  # what a pseudo-instruction turns into


def about(word: str, xlen: int = 32) -> About | None:
    """What this word is, or nothing where it is a word of the program's own."""
    word = word.strip()
    if not word:
        return None
    lower = word.lower()
    for telling in (_instruction, _pseudo, _directive, _register, _control):
        found = telling(lower, xlen)
        if found is not None:
            return found
    return None


def _instruction(word: str, xlen: int) -> About | None:
    one = find(word, xlen)
    if one is None:
        return None
    where = {32: " (32-bit machines only)", 64: " (64-bit machines only)"}
    return About(word, INSTRUCTION,
                 f"A basic instruction of the {one.ext} extension, "
                 f"{one.format.__name__} format"
                 + where.get(one.xlen, ""),
                 forms=(f"{one.mnemonic} {one.syntax}".strip(),))


def _pseudo(word: str, xlen: int) -> About | None:
    rows = pseudo.variants(word, xlen)
    if not rows:
        return None
    alias = all(row.alias for row in rows)
    return About(word, PSEUDO,
                 "Another name of an instruction" if alias
                 else "A pseudo-instruction: the assembler writes it out",
                 forms=tuple(f"{row.mnemonic} {row.syntax}".strip() for row in rows),
                 becomes=tuple(_becomes(row) for row in rows))


def _becomes(row: pseudo.Pseudo) -> str:
    return " + ".join(one.mnemonic for one in row.templates) or "nothing"


def _directive(word: str, xlen: int) -> About | None:
    if word in RARS_DIRECTIVES:
        return About(word, DIRECTIVE, "A directive of the RARS dialect")
    if word in MANUAL_DIRECTIVES:
        return About(word, DIRECTIVE,
                     "A directive of the assembly manual")
    return None


def _register(word: str, xlen: int) -> About | None:
    number = _numbered(word, "x", X_NAMES, X_ALIASES)
    if number is not None:
        names = [f"x{number}", X_NAMES[number]]
        names += [one for one, which in X_ALIASES.items() if which == number]
        return About(word, REGISTER,
                     f"A register of the machine, {xlen} bits wide; "
                     + _also(word, names))
    number = _numbered(word, "f", F_NAMES, {})
    if number is not None:
        return About(word, FLOAT, "A floating point register, 64 bits wide; "
                     + _also(word, [f"f{number}", F_NAMES[number]]))
    return None


def _control(word: str, xlen: int) -> About | None:
    if word not in CSRS:
        return None
    return About(word, CONTROL,
                 f"A control and status register, number 0x{CSRS[word]:03x}")


def _numbered(word: str, letter: str, names: tuple[str, ...],
              aliases: dict[str, int]) -> int | None:
    if word in aliases:
        return aliases[word]
    if word in names:
        return names.index(word)
    if word.startswith(letter) and word[1:].isdigit() and int(word[1:]) < 32:
        return int(word[1:])
    return None


def _also(word: str, names: list[str]) -> str:
    """The other names of a register, which is what somebody looking it up wants."""
    others = [one for one in names if one != word]
    return "also written " + ", ".join(others) if others else "it has no other name"


def every_word(xlen: int = 32) -> frozenset[str]:
    """Every word this module can tell of, which is what the editor completes
    from."""
    return frozenset(
        {one.mnemonic for one in instructions(xlen)}
        | pseudo.mnemonics(xlen) | RARS_DIRECTIVES | MANUAL_DIRECTIVES
        | set(X_NAMES) | set(X_ALIASES) | set(F_NAMES) | set(CSRS)
        | {f"x{number}" for number in range(32)}
        | {f"f{number}" for number in range(32)})
