"""`.insn`: write an instruction word that the assembler does not know.

Three forms (asm manual):

    .insn <value>              one word with that value
    .insn <length>, <value>    the same, with the length in bytes checked
    .insn <type> <fields>      the fields of an instruction format

The fields of a format are listed from the least significant bits to the most
significant ones, grouped: opcode, function fields, registers, immediates
(asm manual, GNU as "RISC-V Formats"):

    .insn r  opcode, func3, func7, rd, rs1, rs2
    .insn r  opcode, func3, func2, rd, rs1, rs2, rs3
    .insn i  opcode, func3, rd, rs1, simm12      | opcode, func3, rd, simm12(rs1)
    .insn s  opcode, func3, rs2, simm12(rs1)
    .insn sb opcode, func3, rs1, rs2, symbol     | opcode, func3, rs2, simm12(rs1)
    .insn u  opcode, rd, simm20
    .insn uj opcode, rd, symbol

`b` is another name of `sb` and `j` of `uj`. The 16-bit types of the C
extension are not supported: we have no compressed instructions (D6), so an
instruction is always four bytes.
"""

from collections.abc import Sequence

from pyrars.asm.expressions import Value, evaluate
from pyrars.asm.lexer import Kind, Token
from pyrars.asm.operands import OperandError, expression
from pyrars.asm.parser import Statement
from pyrars.isa.formats import B, I, J, R, R4, S, U
from pyrars.isa.spec import Format

WORD = 4  # bytes of an instruction

# type -> (format, field names in the order they are written)
_TYPES: dict[str, tuple[type[Format], tuple[str, ...]]] = {
    "r": (R, ("opcode", "funct3", "funct7", "rd", "rs1", "rs2")),
    "r4": (R4, ("opcode", "rm", "funct2", "rd", "rs1", "rs2", "rs3")),
    "i": (I, ("opcode", "funct3", "rd", "rs1", "imm")),
    "s": (S, ("opcode", "funct3", "rs2", "imm", "rs1")),
    "sb": (B, ("opcode", "funct3", "rs1", "rs2", "imm")),
    "u": (U, ("opcode", "rd", "imm")),
    "uj": (J, ("opcode", "rd", "imm")),
}
_ALIASES = {"b": "sb", "j": "uj"}
_MEMORY_FORM = {"i": (I, ("opcode", "funct3", "rd", "imm", "rs1")),
                "s": (S, ("opcode", "funct3", "rs2", "imm", "rs1")),
                "sb": (B, ("opcode", "funct3", "rs2", "imm", "rs1"))}
_RELATIVE = (B, J)  # their immediate is a branch or jump target


def encode_insn(statement: Statement, resolve, address: int) -> int:
    """Word of a ".insn" statement; raises OperandError."""
    groups = list(statement.operands)
    column = statement.name.column
    if not groups:
        raise OperandError(column, '".insn" directive needs an instruction')
    name = groups[0][0]
    # a type name may also be an instruction mnemonic ("sb", "j"), so it is an
    # OPERATOR token then
    if name.kind in (Kind.IDENTIFIER, Kind.OPERATOR) and (name.text.lower() in _TYPES
                                                          or name.text.lower() in _ALIASES):
        groups[0] = groups[0][1:]  # the type and the first field share a group
        if not groups[0]:
            raise OperandError(column, '".insn" directive needs the fields of the instruction')
        return _by_type(name.text.lower(), statement, groups, resolve, address, column)
    values = [_number(statement, group, resolve, column) for group in groups]
    if len(values) == 1:
        return _word(values[0], column, groups[0])
    if len(values) == 2:
        if values[0] != WORD:
            raise OperandError(groups[0][0].column,
                               f'"{values[0]}": an instruction is {WORD} bytes long')
        return _word(values[1], column, groups[1])
    raise OperandError(column, '".insn" directive takes a value, a length and a value, or a type')


def _word(value: int, column: int, group: Sequence[Token]) -> int:
    if not 0 <= value <= 0xFFFFFFFF:
        raise OperandError(group[0].column, f'"{value}": operand is out of range')
    return value


def _by_type(type_name: str, statement: Statement, groups: list[Sequence[Token]],
             resolve, address: int, column: int) -> int:
    type_name = _ALIASES.get(type_name, type_name)
    fmt, names = _TYPES[type_name]
    if type_name == "r" and len(groups) == 7:
        fmt, names = _TYPES["r4"]
    memory = _memory_group(groups)
    if memory is not None and type_name in _MEMORY_FORM:
        fmt, names = _MEMORY_FORM[type_name]
        groups = groups[:memory] + list(_split_memory(groups[memory])) + groups[memory + 1:]
    if len(groups) != len(names):
        raise OperandError(column, f'".insn {type_name}" takes {len(names)} fields: '
                                   f"{', '.join(names)}")
    word = 0
    for field_name, group in zip(names, groups):
        value = _field_value(field_name, statement, group, resolve, address, fmt)
        field = fmt.fields[field_name]
        try:
            field.check(value)
        except ValueError:
            text = statement.line.expanded[group[0].column - 1:group[-1].end - 1]
            raise OperandError(group[0].column, f'"{text}": operand is out of range') from None
        word |= field.put(value)
    return word


def _memory_group(groups: list[Sequence[Token]]) -> int | None:
    """Index of a group written as "imm(rs1)", if there is one."""
    for index, group in enumerate(groups):
        if group[-1].kind is Kind.RIGHT_PAREN:
            return index
    return None


def _split_memory(group: Sequence[Token]) -> tuple[Sequence[Token], Sequence[Token]]:
    """"imm(rs1)" as two groups: the offset and the register."""
    return group[:-3], (group[-2],)


def _field_value(field_name: str, statement: Statement, group: Sequence[Token],
                 resolve, address: int, fmt: type[Format]) -> int:
    token = group[0]
    if len(group) == 1 and token.kind in (Kind.REGISTER_NAME, Kind.REGISTER_NUMBER,
                                          Kind.FP_REGISTER_NAME):
        return token.value
    if not group:
        raise OperandError(statement.name.column, '".insn" directive needs a value')
    text = statement.line.expanded[token.column - 1:group[-1].end - 1]
    value = evaluate(expression(tuple(group)), resolve)
    if field_name == "imm" and fmt in _RELATIVE:  # a branch or jump target
        return value.number - address if value.segment is not None else value.number
    if value.segment is not None:
        raise OperandError(token.column, f'"{text}": operand is of incorrect type')
    return value.number


def _number(statement: Statement, group: Sequence[Token], resolve, column: int) -> int:
    value: Value = evaluate(expression(tuple(group)), resolve)
    if value.segment is not None:
        text = statement.line.expanded[group[0].column - 1:group[-1].end - 1]
        raise OperandError(group[0].column, f'"{text}": operand is of incorrect type')
    return value.number
