"""Macro definitions and substitution in a macro body.

A macro is defined by

    .macro name %p, \\q          # .end_macro or .endm ends the definition
    ...body...
    .end_macro

and called like an instruction: `name arg1, arg2`. Parameters are written
`%p` (RARS) or `\\p` (GNU as, asm manual); in the body they are replaced by the
text of the arguments of the call. Labels defined in the body get the suffix
"_M<n>" of the expansion, so that every expansion has its own labels (RARS).

The reader of the source stage keeps the macros and expands the calls; this
module holds the macro itself and the two operations on its text.

Deviations from RARS (skill §7): parameters and labels are replaced by tokens,
not by text search (DEV-17); arguments and parameters are separated by commas
(DEV-18); SPIM style parameters "$p" are not a parameter kind (DEV-21).
"""

from dataclasses import dataclass, field

from pyrars.asm.lexer import Kind, Token
from pyrars.isa.program import SourceLoc


@dataclass(frozen=True)
class BodyLine:
    """A line of a macro body, as written (no .eqv substitution yet)."""

    file: str
    line: int
    text: str


@dataclass(eq=False)  # macros are compared by identity (the expansion stack)
class Macro:
    name: str
    params: tuple[str, ...]
    loc: SourceLoc  # the .macro directive
    body: list[BodyLine] = field(default_factory=list)
    labels: set[str] = field(default_factory=set)  # labels defined in the body


def is_parameter(token: Token) -> bool:
    """A macro parameter: "%p" (RARS) or "\\p" (GNU as), one token of its own."""
    return token.kind is Kind.MACRO_PARAMETER


def parse_definition(tokens: list[Token], start: int,
                     loc: SourceLoc) -> tuple[Macro | None, list[tuple[int, str]]]:
    """Macro of a ".macro name %p, %q" statement and the errors (column, message).

    A macro without a valid name is None: RARS does not start a definition then.
    """
    directive = tokens[start]
    rest = [t for t in tokens[start + 1:] if t.kind is not Kind.COMMENT]
    if not rest:
        return None, [(directive.column, '".macro" directive requires at least one argument.')]
    name = rest[0]
    if name.kind is not Kind.IDENTIFIER:
        return None, [(name.column, f'Invalid Macro name "{name.text}"')]

    macro = Macro(name.text, (), loc)
    params: list[str] = []
    after_parameter = False  # a comma must follow
    for token in rest[1:]:
        if after_parameter:
            if token.kind is not Kind.COMMA:
                return macro, [(token.column, 'Macro parameters must be separated by ","')]
            after_parameter = False
        elif not is_parameter(token):
            return macro, [(token.column, f"Invalid macro argument '{token.text}'")]
        else:
            params.append(token.text)
            after_parameter = True
    if rest[1:] and not after_parameter:  # the list ends with a comma
        return macro, [(rest[-1].column, 'Missing macro parameter after ","')]
    macro.params = tuple(params)
    return macro, []


def find(macros: list[Macro], name: str, arguments: int) -> Macro | None:
    """The macro of this name taking this many arguments, the last one defined."""
    matching = [m for m in macros if m.name == name and len(m.params) == arguments]
    return matching[-1] if matching else None


def defined(macros: list[Macro], name: str) -> bool:
    return any(m.name == name for m in macros)


def substitute(text: str, tokens: list[Token], arguments: dict[str, str],
               labels: set[str], counter: int) -> tuple[str, list[Token]]:
    """A body line with its parameters and labels replaced, and the unknown parameters.

    Tokens are replaced from right to left, so that the columns of the tokens
    still to be replaced stay valid. A parameter inside a string is not a token
    of its own and therefore stays as it is (RARS).
    """
    unknown = []
    for token in reversed(tokens):
        if token.kind is Kind.MACRO_PARAMETER or token.kind is Kind.IDENTIFIER:
            if token.text in arguments:  # a parameter: its name starts with % or \\
                replacement = arguments[token.text]
            elif token.kind is Kind.IDENTIFIER and token.text in labels:
                replacement = f"{token.text}_M{counter}"
            else:
                if token.kind is Kind.MACRO_PARAMETER:
                    unknown.append(token)
                continue
            text = text[:token.column - 1] + replacement + text[token.end - 1:]
    return text, unknown[::-1]
