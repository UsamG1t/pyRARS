"""Pseudo-instructions: source statements that stand for one or more basic
instructions (`mv t0, t1` = `addi t0, t1, 0`, `la t0, msg` = `auipc` + `addi`).

A pseudo-instruction is one row of TABLE: a mnemonic, the syntax of its
operands and the templates of the basic instructions it becomes. Operands are
numbered from 1 in the order they appear in the syntax, and a template refers
to them by that number: `Reg(1)` is the register of the first operand, `Lo(2)`
the lower 12 bits of the value of the second one.

Rows of the same mnemonic are tried in the order of the table (first fit, like
RARS): the short variant of `li` stands before the long one. The chosen row
fixes how many instructions the statement takes, which pass 1 needs for the
addresses; while a value is still unknown, the longest variant is reserved
(DEV-24) - a long variant is correct for a small value as well.

Deviations from RARS (skill §7): `mv` becomes `addi rd, rs, 0` of the ISA
manual (DEV-22); the writing CSR pseudo-instructions take the CSR first, as in
the asm manual (DEV-23); an unknown value reserves the longest variant
(DEV-24); `fence` without operands (DEV-3) and `pause`, `lla`, `jump`,
`call rt, symbol` and the `jalr`/`jr` forms of the asm manual are added
(DEV-26). The rounding mode of a floating point instruction is an optional
operand of the basic instruction instead of ~30 pseudo-instructions (DEV-25,
asm/operands.py).
"""

import re
from dataclasses import dataclass

from pyrars.asm.expressions import ExprError, Value, evaluate, hi20, lo12
from pyrars.asm.lexer import Kind
from pyrars.asm.operands import Operand, OperandError, check_range, expression, incorrect_type
from pyrars.asm.parser import Statement
from pyrars.isa.instructions import find as basic
from pyrars.isa.spec import Instr

# --------------------------------------------------- what a template puts into a field


@dataclass(frozen=True)
class Reg:
    """Register number of the n-th operand."""

    n: int


@dataclass(frozen=True)
class Imm:
    """Value of the n-th operand as it is (a CSR number, a small immediate)."""

    n: int


@dataclass(frozen=True)
class Lo:
    """Lower 12 bits of the value of the n-th operand."""

    n: int


@dataclass(frozen=True)
class Hi:
    """Upper 20 bits of that value, for lui."""

    n: int


@dataclass(frozen=True)
class PcLo:
    """Lower 12 bits of (value of the n-th operand - address of the statement)."""

    n: int


@dataclass(frozen=True)
class PcHi:
    """Upper 20 bits of that difference, for auipc."""

    n: int


@dataclass(frozen=True)
class Target:
    """Branch or jump target: value of the n-th operand - address of this instruction."""

    n: int


@dataclass(frozen=True)
class Const:
    """A number written in the template itself (x0, a shift amount, a CSR number)."""

    value: int


type Part = Reg | Imm | Lo | Hi | PcLo | PcHi | Target | Const


@dataclass(frozen=True)
class Template:
    """One basic instruction of an expansion; parts follow the order of its operands."""

    mnemonic: str
    parts: tuple[Part, ...]


@dataclass(frozen=True)
class Pseudo:
    mnemonic: str
    syntax: str  # operand kinds, e.g. "rd, imm12" or "rd, imm12(rs)"
    templates: tuple[Template, ...]
    xlen: int | None = None  # None: both
    alias: bool = False  # another name of a row above; not used when reading a word back

    def exists_in(self, xlen: int) -> bool:
        return self.xlen is None or self.xlen == xlen

    @property
    def kinds(self) -> tuple[str, ...]:
        """Operand kinds in source order; the memory form gives two of them."""
        return tuple(re.findall(r"[a-z][a-z0-9.]*", self.syntax))


def t(mnemonic: str, *parts: Part) -> Template:
    return Template(mnemonic, parts)


# ------------------------------------------------------------------- the table

_INTEGER_REGISTER = ("rd", "rs", "rt")
_FP_REGISTER = ("fd", "fs", "ft")
_RANGES = {"imm12": (-2048, 2047), "imm32": (-2**31, 2**32 - 1), "uimm5": (0, 31)}

X0, RA = Const(0), Const(1)
FCSR, FRM, FFLAGS = Const(0x003), Const(0x002), Const(0x001)


def _memory(mnemonic: str, first: str, xlen: int | None = None) -> list[Pseudo]:
    """Address forms of a load or store: near address, far address, label.

    An integer load computes the address in the register it loads; the other
    forms need a temporary register, given as the last operand (RARS).
    """
    own = first == "rd"
    temp = Reg(1) if own else Reg(3)
    extra = "" if own else ", rt"
    return [
        Pseudo(mnemonic, f"{first}, imm12", (t(mnemonic, Reg(1), Lo(2), X0),), xlen),
        Pseudo(mnemonic, f"{first}, imm32{extra}",
               (t("lui", temp, Hi(2)), t(mnemonic, Reg(1), Lo(2), temp)), xlen),
        Pseudo(mnemonic, f"{first}, symbol{extra}",
               (t("auipc", temp, PcHi(2)), t(mnemonic, Reg(1), PcLo(2), temp)), xlen),
    ]


def _csr_read(mnemonic: str, csr: Const, alias: bool = False) -> Pseudo:
    return Pseudo(mnemonic, "rd", (t("csrrs", Reg(1), csr, X0),), alias=alias)


def _csr_write(mnemonic: str, csr: Const, alias: bool = False) -> list[Pseudo]:
    """"<name> rd, rs" swaps the register with the CSR, "<name> rs" only writes it."""
    return [Pseudo(mnemonic, "rd, rs", (t("csrrw", Reg(1), csr, Reg(2)),), alias=alias),
            Pseudo(mnemonic, "rs", (t("csrrw", X0, csr, Reg(1)),), alias=alias)]


TABLE: tuple[Pseudo, ...] = (
    # ------------------------------------------------------------- arithmetic
    Pseudo("nop", "", (t("addi", X0, X0, Const(0)),)),
    Pseudo("mv", "rd, rs", (t("addi", Reg(1), Reg(2), Const(0)),)),  # DEV-22
    Pseudo("not", "rd, rs", (t("xori", Reg(1), Reg(2), Const(-1)),)),
    Pseudo("neg", "rd, rs", (t("sub", Reg(1), X0, Reg(2)),)),
    Pseudo("negw", "rd, rs", (t("subw", Reg(1), X0, Reg(2)),), 64),
    Pseudo("seqz", "rd, rs", (t("sltiu", Reg(1), Reg(2), Const(1)),)),
    Pseudo("snez", "rd, rs", (t("sltu", Reg(1), X0, Reg(2)),)),
    Pseudo("sltz", "rd, rs", (t("slt", Reg(1), Reg(2), X0),)),
    Pseudo("sgtz", "rd, rs", (t("slt", Reg(1), X0, Reg(2)),)),
    Pseudo("sgt", "rd, rs, rt", (t("slt", Reg(1), Reg(3), Reg(2)),)),
    Pseudo("sgtu", "rd, rs, rt", (t("sltu", Reg(1), Reg(3), Reg(2)),)),
    # sign and zero extension: shift the bits out and back (XLEN - width)
    Pseudo("sext.b", "rd, rs", (t("slli", Reg(1), Reg(2), Const(24)),
                                t("srai", Reg(1), Reg(1), Const(24))), 32),
    Pseudo("sext.b", "rd, rs", (t("slli", Reg(1), Reg(2), Const(56)),
                                t("srai", Reg(1), Reg(1), Const(56))), 64),
    Pseudo("sext.h", "rd, rs", (t("slli", Reg(1), Reg(2), Const(16)),
                                t("srai", Reg(1), Reg(1), Const(16))), 32),
    Pseudo("sext.h", "rd, rs", (t("slli", Reg(1), Reg(2), Const(48)),
                                t("srai", Reg(1), Reg(1), Const(48))), 64),
    Pseudo("sext.w", "rd, rs", (t("addiw", Reg(1), Reg(2), Const(0)),), 64),
    Pseudo("zext.b", "rd, rs", (t("andi", Reg(1), Reg(2), Const(255)),)),
    Pseudo("zext.h", "rd, rs", (t("slli", Reg(1), Reg(2), Const(16)),
                                t("srli", Reg(1), Reg(1), Const(16))), 32),
    Pseudo("zext.h", "rd, rs", (t("slli", Reg(1), Reg(2), Const(48)),
                                t("srli", Reg(1), Reg(1), Const(48))), 64),
    Pseudo("zext.w", "rd, rs", (t("slli", Reg(1), Reg(2), Const(32)),
                                t("srli", Reg(1), Reg(1), Const(32))), 64),
    # ------------------------------------------------------ values and addresses
    Pseudo("li", "rd, imm12", (t("addi", Reg(1), X0, Lo(2)),)),
    Pseudo("li", "rd, imm32", (t("lui", Reg(1), Hi(2)),
                               t("addi", Reg(1), Reg(1), Lo(2))), 32),
    Pseudo("li", "rd, imm32", (t("lui", Reg(1), Hi(2)),
                               t("addiw", Reg(1), Reg(1), Lo(2))), 64),
    Pseudo("la", "rd, symbol", (t("auipc", Reg(1), PcHi(2)),
                                t("addi", Reg(1), Reg(1), PcLo(2)))),
    Pseudo("lla", "rd, symbol", (t("auipc", Reg(1), PcHi(2)),
                                 t("addi", Reg(1), Reg(1), PcLo(2)))),  # DEV-26
    # ------------------------------------------------------------ floating point
    Pseudo("fmv.s", "fd, fs", (t("fsgnj.s", Reg(1), Reg(2), Reg(2)),)),
    Pseudo("fabs.s", "fd, fs", (t("fsgnjx.s", Reg(1), Reg(2), Reg(2)),)),
    Pseudo("fneg.s", "fd, fs", (t("fsgnjn.s", Reg(1), Reg(2), Reg(2)),)),
    Pseudo("fmv.d", "fd, fs", (t("fsgnj.d", Reg(1), Reg(2), Reg(2)),)),
    Pseudo("fabs.d", "fd, fs", (t("fsgnjx.d", Reg(1), Reg(2), Reg(2)),)),
    Pseudo("fneg.d", "fd, fs", (t("fsgnjn.d", Reg(1), Reg(2), Reg(2)),)),
    Pseudo("fgt.s", "rd, fs, ft", (t("flt.s", Reg(1), Reg(3), Reg(2)),)),
    Pseudo("fge.s", "rd, fs, ft", (t("fle.s", Reg(1), Reg(3), Reg(2)),)),
    Pseudo("fgt.d", "rd, fs, ft", (t("flt.d", Reg(1), Reg(3), Reg(2)),)),
    Pseudo("fge.d", "rd, fs, ft", (t("fle.d", Reg(1), Reg(3), Reg(2)),)),
    # ------------------------------------------------------------------ branches
    Pseudo("b", "symbol", (t("jal", X0, Target(1)),), alias=True),  # RARS, another name of "j"
    Pseudo("beqz", "rs, symbol", (t("beq", Reg(1), X0, Target(2)),)),
    Pseudo("bnez", "rs, symbol", (t("bne", Reg(1), X0, Target(2)),)),
    Pseudo("bgez", "rs, symbol", (t("bge", Reg(1), X0, Target(2)),)),
    Pseudo("bltz", "rs, symbol", (t("blt", Reg(1), X0, Target(2)),)),
    Pseudo("bgtz", "rs, symbol", (t("blt", X0, Reg(1), Target(2)),)),
    Pseudo("blez", "rs, symbol", (t("bge", X0, Reg(1), Target(2)),)),
    Pseudo("bgt", "rs, rt, symbol", (t("blt", Reg(2), Reg(1), Target(3)),)),
    Pseudo("ble", "rs, rt, symbol", (t("bge", Reg(2), Reg(1), Target(3)),)),
    Pseudo("bgtu", "rs, rt, symbol", (t("bltu", Reg(2), Reg(1), Target(3)),)),
    Pseudo("bleu", "rs, rt, symbol", (t("bgeu", Reg(2), Reg(1), Target(3)),)),
    # --------------------------------------------------------- jumps and calls
    Pseudo("j", "symbol", (t("jal", X0, Target(1)),)),
    Pseudo("jal", "symbol", (t("jal", RA, Target(1)),)),
    Pseudo("jr", "rs", (t("jalr", X0, Reg(1), Const(0)),)),
    Pseudo("jr", "rs, imm12", (t("jalr", X0, Reg(1), Lo(2)),)),  # RARS
    Pseudo("jr", "imm12(rs)", (t("jalr", X0, Reg(2), Lo(1)),)),  # DEV-26
    Pseudo("jalr", "rs", (t("jalr", RA, Reg(1), Const(0)),)),
    Pseudo("jalr", "rd, rs", (t("jalr", Reg(1), Reg(2), Const(0)),)),  # DEV-26
    Pseudo("jalr", "rs, imm12", (t("jalr", RA, Reg(1), Lo(2)),)),  # RARS
    Pseudo("jalr", "imm12(rs)", (t("jalr", RA, Reg(2), Lo(1)),)),  # DEV-26
    Pseudo("jalr", "rd, imm12(rs)", (t("jalr", Reg(1), Reg(3), Lo(2)),)),  # RARS
    Pseudo("ret", "", (t("jalr", X0, RA, Const(0)),)),
    Pseudo("call", "symbol", (t("auipc", Const(6), PcHi(1)),
                              t("jalr", RA, Const(6), PcLo(1)))),
    Pseudo("call", "rt, symbol", (t("auipc", Reg(1), PcHi(2)),
                                  t("jalr", RA, Reg(1), PcLo(2)))),  # DEV-26
    Pseudo("tail", "symbol", (t("auipc", Const(6), PcHi(1)),
                              t("jalr", X0, Const(6), PcLo(1)))),
    Pseudo("jump", "symbol, rt", (t("auipc", Reg(2), PcHi(1)),
                                  t("jalr", X0, Reg(2), PcLo(1)))),  # DEV-26
    # ---------------------------------------------------- control and status
    Pseudo("csrr", "rd, csr", (t("csrrs", Reg(1), Imm(2), X0),)),
    Pseudo("csrw", "csr, rs", (t("csrrw", X0, Imm(1), Reg(2)),)),  # DEV-23
    Pseudo("csrs", "csr, rs", (t("csrrs", X0, Imm(1), Reg(2)),)),
    Pseudo("csrc", "csr, rs", (t("csrrc", X0, Imm(1), Reg(2)),)),
    Pseudo("csrwi", "csr, uimm5", (t("csrrwi", X0, Imm(1), Imm(2)),)),
    Pseudo("csrsi", "csr, uimm5", (t("csrrsi", X0, Imm(1), Imm(2)),)),
    Pseudo("csrci", "csr, uimm5", (t("csrrci", X0, Imm(1), Imm(2)),)),
    _csr_read("frcsr", FCSR),
    _csr_read("frsr", FCSR, alias=True),  # RARS, another name of "frcsr"
    _csr_read("frrm", FRM),
    _csr_read("frflags", FFLAGS),
    _csr_read("rdcycle", Const(0xC00)),
    _csr_read("rdtime", Const(0xC01)),
    _csr_read("rdinstret", Const(0xC02)),
    _csr_read("rdcycleh", Const(0xC80)),
    _csr_read("rdtimeh", Const(0xC81)),
    _csr_read("rdinstreth", Const(0xC82)),
    # ------------------------------------------------------------------ fences
    Pseudo("fence", "", (t("fence", Const(15), Const(15)),)),  # DEV-3
    Pseudo("pause", "", (t("fence", Const(1), Const(0)),)),  # DEV-26
)

TABLE += tuple(_csr_write("fscsr", FCSR)) + tuple(_csr_write("fssr", FCSR, alias=True))
TABLE += tuple(_csr_write("fsrm", FRM)) + tuple(_csr_write("fsflags", FFLAGS))
TABLE += tuple(p for name in ("lb", "lbu", "lh", "lhu", "lw") for p in _memory(name, "rd"))
TABLE += tuple(p for name in ("lwu", "ld") for p in _memory(name, "rd", 64))
TABLE += tuple(p for name in ("sb", "sh", "sw") for p in _memory(name, "rs"))
TABLE += tuple(_memory("sd", "rs", 64))
TABLE += tuple(p for name in ("flw", "fld") for p in _memory(name, "fd"))
TABLE += tuple(p for name in ("fsw", "fsd") for p in _memory(name, "fs"))


def mnemonics(xlen: int) -> frozenset[str]:
    """Mnemonics of the pseudo-instructions, lower case (lexer operators)."""
    return frozenset(p.mnemonic for p in TABLE if p.exists_in(xlen))


def variants(mnemonic: str, xlen: int) -> tuple[Pseudo, ...]:
    """Rows of the table for this mnemonic, in the order they are tried."""
    return tuple(p for p in TABLE if p.mnemonic == mnemonic and p.exists_in(xlen))


# ---------------------------------------------------------------- matching


@dataclass(frozen=True)
class Candidate:
    """A row of the table whose operand shape fits the statement."""

    pseudo: Pseudo
    operands: tuple[Operand, ...]


@dataclass(frozen=True)
class Expanded:
    """One basic instruction of an expansion, ready for isa.codec.encode."""

    instr: Instr
    fields: dict[str, int]


def match(statement: Statement, xlen: int) -> list[Candidate]:
    """Rows that fit the operands of the statement, in table order.

    An empty list means the mnemonic is not a pseudo-instruction; a mnemonic
    that is one but does not fit raises OperandError.
    """
    rows = variants(statement.name.text.lower(), xlen)
    if not rows:
        return []
    candidates, errors = [], []
    for pseudo in rows:
        try:
            candidates.append(Candidate(pseudo, _operands(statement, pseudo)))
        except OperandError as error:
            errors.append((len(pseudo.kinds), error))
    if candidates:
        return candidates
    _reversed_csr_operands(statement, rows[0])
    # The error of a row with as many operands as the statement says more than
    # "wrong number of operands", so prefer it (RARS shows the first row).
    same_shape = [e for count, e in errors if count == len(statement.operands)]
    raise same_shape[0] if same_shape else errors[0][1]


def _operands(statement: Statement, pseudo: Pseudo) -> tuple[Operand, ...]:
    """Operands of the statement as the row wants them; raises OperandError."""
    patterns = [re.findall(r"[a-z][a-z0-9.]*|[()]", group) for group in pseudo.syntax.split(",")] \
        if pseudo.syntax else []
    groups = statement.operands
    if len(groups) != len(patterns):
        raise _format_error(statement, pseudo, "few" if len(groups) < len(patterns) else "many")
    operands: list[Operand] = []
    for pattern, tokens in zip(patterns, groups):
        text = statement.line.expanded[tokens[0].column - 1:tokens[-1].end - 1]
        if len(pattern) == 4:  # imm ( rs )
            if len(tokens) < 3 or tokens[-3].kind is not Kind.LEFT_PAREN \
                    or tokens[-1].kind is not Kind.RIGHT_PAREN:
                raise _format_error(statement, pseudo, "few")
            offset, base = tokens[:-3], tokens[-2]
            operands.append(Operand(expression(offset) if offset else 0, text, tokens[0].column))
            operands.append(_register(base, pattern[2]))
        elif pattern[0] in _INTEGER_REGISTER or pattern[0] in _FP_REGISTER:
            if len(tokens) > 1:
                raise _format_error(statement, pseudo, "many")
            operands.append(_register(tokens[0], pattern[0]))
        elif pattern[0] == "csr" and len(tokens) == 1 and tokens[0].kind is Kind.CSR_NAME:
            operands.append(Operand(tokens[0].value, text, tokens[0].column))
        else:
            operands.append(Operand(expression(tokens), text, tokens[0].column))
    return tuple(operands)


def _register(token, kind: str) -> Operand:
    wanted = (Kind.FP_REGISTER_NAME,) if kind in _FP_REGISTER \
        else (Kind.REGISTER_NAME, Kind.REGISTER_NUMBER)
    if token.kind not in wanted:
        raise incorrect_type(token)
    return Operand(token.value, token.text, token.column)


def expected(pseudo: Pseudo) -> str:
    """Syntax shown in an error message: kinds without their widths (DEV-14)."""
    syntax = re.sub(r"imm\d+", "imm", pseudo.syntax).replace("uimm5", "uimm")
    return f"{pseudo.mnemonic} {syntax}".rstrip()


def _format_error(statement: Statement, pseudo: Pseudo, too: str) -> OperandError:
    name = statement.name
    return OperandError(name.column, f'"{name.text}": Too {too} or incorrectly formatted operands. '
                                     f"Expected: {expected(pseudo)}")


def _reversed_csr_operands(statement: Statement, pseudo: Pseudo) -> None:
    """DEV-23: RARS writes "csrw t0, fcsr"; we take the CSR first, like the asm
    manual, and say so instead of complaining about the operand type."""
    if pseudo.kinds[:1] == ("csr",) and len(statement.operands) == len(pseudo.kinds) \
            and statement.operands[0][0].kind in (Kind.REGISTER_NAME, Kind.REGISTER_NUMBER):
        name = statement.name
        raise OperandError(name.column, f'"{name.text}": operands are reversed. '
                                        f"Expected: {expected(pseudo)}")


# ------------------------------------------------- choosing a row and expanding


def choose(candidates: list[Candidate], resolve, size: int | None = None) -> Candidate:
    """The row to use: the first one whose values fit (RARS: first fit).

    resolve - gives the Value of a symbol (see expressions.evaluate)
    size    - number of instructions reserved in pass 1; without it (pass 1) a
              value that cannot be evaluated yet reserves the longest row
    """
    fitting = [c for c in candidates if size is None or len(c.pseudo.templates) == size]
    unknown = False
    for candidate in fitting:
        values = _values(candidate, resolve, strict=size is not None)
        if None in values:
            unknown = True
            continue
        if _fits(candidate, values):
            return candidate
    if unknown:  # keep room for the longest row until the value is known (DEV-24)
        return max(fitting, key=lambda c: len(c.pseudo.templates))
    raise _value_error(fitting or candidates, resolve)


def size(candidates: list[Candidate], resolve) -> int:
    """Number of basic instructions the statement takes (pass 1)."""
    return len(choose(candidates, resolve).pseudo.templates)


def expand(candidate: Candidate, resolve, pc: int) -> list[Expanded]:
    """Basic instructions of the expansion; pc is the address of the statement."""
    values = _values(candidate, resolve, strict=True)
    result = []
    for number, template in enumerate(candidate.pseudo.templates):
        instr = basic(template.mnemonic, 64 if candidate.pseudo.xlen == 64 else 32)
        fields = {}
        for name, part in zip(instr.operands, template.parts):
            value = _part_value(part, values, pc, pc + 4 * number)
            if isinstance(part, Const):  # written in the template, always in range
                fields[name] = value
            else:
                fields[name] = check_range(instr, name, value, candidate.operands[part.n - 1])
        result.append(Expanded(instr, fields))
    return result


def _values(candidate: Candidate, resolve, strict: bool) -> tuple[Value | None, ...]:
    """Value of every operand; None for one that cannot be evaluated yet."""
    values = []
    for operand in candidate.operands:
        if isinstance(operand.value, int):
            values.append(Value(operand.value))
            continue
        try:
            values.append(evaluate(operand.value, resolve))
        except ExprError:
            if strict:
                raise
            values.append(None)
    return tuple(values)


def _fits(candidate: Candidate, values: tuple[Value, ...]) -> bool:
    return all(_fits_kind(kind, value) for kind, value in zip(candidate.pseudo.kinds, values))


def _fits_kind(kind: str, value: Value) -> bool:
    if kind == "symbol":
        return value.segment is not None
    if kind in _RANGES:
        low, high = _RANGES[kind]
        return value.segment is None and low <= value.number <= high
    return True  # registers and CSRs were checked while matching


def _value_error(candidates: list[Candidate], resolve) -> OperandError:
    """Why no row fits: the first operand of the first row that is wrong."""
    candidate = candidates[0]
    values = _values(candidate, resolve, strict=True)
    for kind, value, operand in zip(candidate.pseudo.kinds, values, candidate.operands):
        if _fits_kind(kind, value):
            continue
        if (kind == "symbol") == (value.segment is None):  # an address for a number, or the other way
            return OperandError(operand.column, f'"{operand.text}": operand is of incorrect type')
        return OperandError(operand.column, f'"{operand.text}": operand is out of range')
    raise AssertionError("a row without a wrong operand")


def _part_value(part: Part, values: tuple[Value, ...], pc: int, address: int) -> int:
    match part:
        case Const(value):
            return value
        case Reg(n) | Imm(n):
            return values[n - 1].number
        case Lo(n):
            return lo12(values[n - 1].number)
        case Hi(n):
            return hi20(values[n - 1].number)
        case PcLo(n):
            return lo12(values[n - 1].number - pc)
        case PcHi(n):
            return hi20(values[n - 1].number - pc)
        case Target(n):
            return values[n - 1].number - address
    raise TypeError(part)
