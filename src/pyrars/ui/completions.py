"""What the editor offers while a line is being typed.

The words are those of the assembler itself (`ui/help.py` gathers them), and WHICH
of them are offered depends on where in the line the typing is: an instruction
begins a line, a directive begins with a stop, and everything after the first word
is an operand - a register, a control register, or a name the program gives
something. That rule is here, where it can be tested, and the widget only shows
what it answers.

Nothing is offered inside a comment, and nothing until a letter has been typed: a
list of two hundred words over an empty line is not help.
"""

import re

from pyrars.asm import pseudo
from pyrars.asm.directives import DIRECTIVES
from pyrars.isa.instructions import mnemonics
from pyrars.isa.registers import CSRS, F_NAMES, X_ALIASES, X_NAMES

# What a word of a program is made of; a directive begins with a stop and a local
# label is a number, so both belong to the word being typed.
WORD = re.compile(r"[A-Za-z0-9_.$]*$")
# A line may begin with a label, and what follows it is still the first word.
LABEL = re.compile(r"^\s*(?:[A-Za-z_.$][A-Za-z0-9_.$]*|[0-9]+)\s*:")


def typing(before: str) -> str:
    """The word being typed at the end of what has been typed so far."""
    return WORD.search(before).group(0)


def beginning(before: str) -> bool:
    """Whether the word being typed is the first of its line, which is where an
    instruction goes - after a label as well as without one."""
    line = before[:len(before) - len(typing(before))]
    return not LABEL.sub("", line).strip()


def registers() -> tuple[str, ...]:
    return tuple(sorted(set(X_NAMES) | set(X_ALIASES) | set(F_NAMES)
                        | {f"x{number}" for number in range(32)}
                        | {f"f{number}" for number in range(32)}))


def words(before: str, labels=(), xlen: int = 32) -> tuple[str, ...]:
    """What may be meant by the word being typed, in the order it is offered."""
    if "#" in before:  # inside a comment nothing is a word of the program
        return ()
    word = typing(before)
    if not word:
        return ()
    if word.startswith("."):
        return _like(word, sorted(DIRECTIVES))
    if beginning(before):
        return _like(word, sorted(mnemonics(xlen) | pseudo.mnemonics(xlen)))
    # An operand: a register, a control register, or something the program named.
    return _like(word, sorted(set(labels)) + list(registers()) + sorted(CSRS))


def _like(word: str, among) -> tuple[str, ...]:
    """Those of them that begin as this word does, whatever its case.

    The one that is already written is not offered: there is nothing to complete
    about a word that is complete.
    """
    lower = word.lower()
    return tuple(one for one in among
                 if one.lower().startswith(lower) and one.lower() != lower)
