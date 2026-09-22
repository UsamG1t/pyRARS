"""Statement structure of a source line:

    [label: ...] [name [operand {, operand}]] [# comment]

- labels: any number (DEV-15), "name:" or a numeric local label "1:";
- name: a directive, an instruction mnemonic, or an identifier (a macro call,
  decided by the macro stage);
- operands: groups of tokens separated by commas (DEV-16).
"""

from dataclasses import dataclass

from pyrars.asm.lexer import Kind, Token
from pyrars.asm.source import SourceLine, is_label
from pyrars.isa.program import Diagnostic, SourceLoc


@dataclass(frozen=True)
class Statement:
    line: SourceLine
    labels: tuple[Token, ...]  # label names, without their colons
    name: Token | None  # None: the line has only labels and/or a comment
    operands: tuple[tuple[Token, ...], ...]


def parse_statement(line: SourceLine) -> tuple[Statement | None, list[Diagnostic]]:
    """Statement of a line, or None with the errors if its structure is wrong."""
    tokens = [t for t in line.tokens if t.kind is not Kind.COMMENT]
    labels = []
    index = 0
    while is_label(tokens, index):
        labels.append(tokens[index])
        index += 2

    def error(column: int, message: str) -> tuple[None, list[Diagnostic]]:
        return None, [Diagnostic("Error", SourceLoc(line.file, line.line, column), message)]

    if index == len(tokens):
        return Statement(line, tuple(labels), None, ()), []
    name = tokens[index]
    if name.kind not in (Kind.DIRECTIVE, Kind.OPERATOR, Kind.IDENTIFIER):
        return error(name.column, f'"{name.text}" is not a recognized operator')

    operands = []
    group: list[Token] = []
    for token in tokens[index + 1:]:
        if token.kind is not Kind.COMMA:
            group.append(token)
        elif group:
            operands.append(tuple(group))
            group = []
        else:
            return error(token.column, 'Missing operand before ","')
    if group:
        operands.append(tuple(group))
    elif len(tokens) > index + 1:  # the last token is a comma
        return error(tokens[-1].column, 'Missing operand after ","')
    return Statement(line, tuple(labels), name, tuple(operands)), []
