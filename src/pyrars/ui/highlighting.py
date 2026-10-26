"""How the editor colours a program, made from the tables that assemble it.

A syntax definition is a list of words, and we already have every one of those
lists: the mnemonics come from `pyrars.isa.instructions` and `pyrars.asm.pseudo`,
the directives from `pyrars.asm.directives`, the registers from
`pyrars.isa.registers`. Writing them out again in an XML file by hand would mean
two lists of the same thing, and one of them would quietly go stale the first time
an instruction was added. So the file is MADE from the tables, and what the editor
colours is by construction what the assembler knows.

The format is the language definition of GtkSourceView 5 (`language2.rng`). Nothing
here imports `gi`: this is text, and it is tested like any other text we make.
"""

from xml.sax.saxutils import escape

from pyrars.asm import pseudo
from pyrars.asm.directives import DIRECTIVES
from pyrars.isa.instructions import mnemonics
from pyrars.isa.registers import CSRS, F_NAMES, X_ALIASES, X_NAMES

ID = "riscv-pyrars"
NAME = "RISC-V (pyRARS)"

# The styles the editor paints with, each tied to one a theme already knows about,
# so that our colours follow whatever scheme the person has chosen.
STYLES = (
    ("comment", "Comment", "def:comment"),
    ("string", "String", "def:string"),
    ("character", "Character", "def:character"),
    ("instruction", "Instruction", "def:keyword"),
    ("directive", "Directive", "def:preprocessor"),
    ("register", "Register", "def:identifier"),
    ("control-register", "Control register", "def:identifier"),
    ("label", "Label", "def:function"),
    ("number", "Number", "def:decimal"),
    ("relocation", "Relocation", "def:builtin"),
    ("parameter", "Macro parameter", "def:special-constant"),
    ("escape", "Escaped character", "def:special-char"),
)


def registers() -> tuple[str, ...]:
    """Every name a register answers to: the numbered ones, the names the
    convention gives them, and the one alias of RARS."""
    numbered = [f"x{number}" for number in range(32)]
    floats = [f"f{number}" for number in range(32)]
    return tuple(sorted(set(numbered) | set(X_NAMES) | set(X_ALIASES)
                        | set(floats) | set(F_NAMES)))


def instructions(xlen: int = 64) -> tuple[str, ...]:
    """Every mnemonic the assembler takes, basic and pseudo alike. The wider
    machine is used by default, so that an editor colours a program it is not
    being told the width of."""
    return tuple(sorted(mnemonics(xlen) | pseudo.mnemonics(xlen)))


def language(xlen: int = 64) -> str:
    """The language definition, as a `.lang` file holds it."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- Made by pyrars.ui.highlighting from the tables of the assembler itself.
     Do not write in this file: write in the tables. -->
<language id="{ID}" name="{escape(NAME)}" version="2.0" _section="Source">
  <metadata>
    <property name="mimetypes">text/x-asm;text/x-assembly</property>
    <property name="globs">*.s;*.asm;*.S</property>
    <property name="line-comment-start">#</property>
  </metadata>

  <styles>
{_styles()}  </styles>

  <definitions>
    <context id="comment" style-ref="comment" class="comment" class-disabled="no-spell-check" end-at-line-end="true">
      <start>#</start>
    </context>

    <context id="string" style-ref="string" class="string" class-disabled="no-spell-check" end-at-line-end="true">
      <start>"</start>
      <end>"</end>
      <include>
        <context id="string-escape" style-ref="escape">
          <match>\\\\.</match>
        </context>
      </include>
    </context>

    <context id="character" style-ref="character" class="string" end-at-line-end="true">
      <start>'</start>
      <end>'</end>
      <include>
        <context ref="string-escape"/>
      </include>
    </context>

    <context id="label" style-ref="label">
      <match>^\\s*([A-Za-z_.$][A-Za-z0-9_.$]*|[0-9]+)\\s*:</match>
    </context>

    <context id="relocation" style-ref="relocation">
      <match>%(hi|lo)\\b</match>
    </context>

    <context id="parameter" style-ref="parameter">
      <match>(%[A-Za-z_][A-Za-z0-9_]*|\\\\[A-Za-z_][A-Za-z0-9_]*)</match>
    </context>

    <context id="number" style-ref="number">
      <match extended="true">
        (?&lt;![\\w.])
        [-+]?
        ( 0[xX][0-9a-fA-F]+
        | 0[bB][01]+
        | [0-9]+\\.[0-9]*([eE][-+]?[0-9]+)?
        | \\.[0-9]+([eE][-+]?[0-9]+)?
        | [0-9]+([eE][-+]?[0-9]+)?
        )
        (?![\\w.])
      </match>
    </context>

{_words("directive", sorted(DIRECTIVES), word=False)}
{_words("control-register", sorted(CSRS))}
{_words("register", registers())}
{_words("instruction", instructions(xlen))}

    <context id="{ID}" class="no-spell-check">
      <include>
        <context ref="comment"/>
        <context ref="string"/>
        <context ref="character"/>
        <context ref="label"/>
        <context ref="directive"/>
        <context ref="relocation"/>
        <context ref="parameter"/>
        <context ref="instruction"/>
        <context ref="control-register"/>
        <context ref="register"/>
        <context ref="number"/>
      </include>
    </context>
  </definitions>
</language>
"""


def _styles() -> str:
    return "".join(f'    <style id="{one}" name="{escape(name)}" map-to="{to}"/>\n'
                   for one, name, to in STYLES)


def _words(style: str, words, word: bool = True) -> str:
    """One context made of a list of words.

    A directive begins with a full stop, which is no word character, so its
    boundary is marked by hand; everything else is a word and is matched as one,
    without regard to the case, as the assembler reads it.
    """
    inside = "".join(f"        <keyword>{escape(one)}</keyword>\n"
                     for one in words)
    if word:
        return (f'    <context id="{style}" style-ref="{style}">\n{inside}'
                f"    </context>\n")
    marks = ('      <prefix>(?&lt;![\\w.])\\.</prefix>\n'
             "      <suffix>(?![\\w.])</suffix>\n")
    plain = "".join(f"        <keyword>{escape(one.lstrip('.'))}</keyword>\n"
                    for one in words)
    return (f'    <context id="{style}" style-ref="{style}">\n{marks}{plain}'
            f"    </context>\n")
