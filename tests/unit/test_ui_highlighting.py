"""The language definition the editor colours with, made from our own tables.

What is tested is that it IS the tables: every mnemonic the assembler takes is in
it, every directive, every register, every control register - and nothing that is
not. That is what makes it impossible for the editor to know a word the assembler
does not, which is the whole reason the file is made rather than written.

That GtkSourceView accepts it, and what it paints, is tested in `tests/ui/`.
"""

from xml.etree import ElementTree

import pytest

from pyrars.asm import pseudo
from pyrars.asm.directives import DIRECTIVES
from pyrars.isa.instructions import mnemonics
from pyrars.isa.registers import CSRS, F_NAMES, X_ALIASES, X_NAMES
from pyrars.ui.highlighting import ID, STYLES, instructions, language, registers


@pytest.fixture
def made():
    return ElementTree.fromstring(language())


def words(root, context: str) -> set[str]:
    found = root.find(f".//context[@id='{context}']")
    return {one.text for one in found.findall("keyword")}


def test_the_definition_is_a_language_gtksourceview_could_read(made):
    assert made.tag == "language"
    assert made.get("id") == ID
    assert made.get("version") == "2.0"
    assert made.find("metadata/property[@name='globs']").text == "*.s;*.asm;*.S"


def test_every_style_is_tied_to_one_a_theme_already_knows(made):
    """Our colours follow the scheme the person chose, instead of being invented
    here."""
    for one, name, to in STYLES:
        style = made.find(f".//style[@id='{one}']")
        assert style is not None, one
        assert style.get("map-to") == to
        assert style.get("map-to").startswith("def:")


def test_every_instruction_the_assembler_takes_is_coloured(made):
    assert words(made, "instruction") == set(instructions(64))
    assert words(made, "instruction") == mnemonics(64) | pseudo.mnemonics(64)
    for one in ("add", "fmadd.d", "li", "la", "ret", "ecall"):
        assert one in words(made, "instruction")


def test_the_wider_machine_is_coloured_by_default(made):
    """An editor is not told the width of the machine a program will run on, so it
    colours what either of them takes: a program of RV64 is not a program of
    mistakes."""
    assert set(instructions(32)) < set(instructions(64))
    assert "addiw" in words(made, "instruction")  # which only RV64 has


def test_every_directive_is_coloured_without_its_stop(made):
    """The full stop is matched by the prefix, because it is no word character and
    a keyword that began with one would never match."""
    assert words(made, "directive") == {one.lstrip(".") for one in DIRECTIVES}
    assert "data" in words(made, "directive")
    assert ".data" not in words(made, "directive")
    directive = made.find(".//context[@id='directive']")
    assert directive.find("prefix") is not None
    assert directive.find("suffix") is not None


def test_every_name_a_register_answers_to_is_coloured(made):
    held = words(made, "register")
    assert held == set(registers())
    assert {f"x{number}" for number in range(32)} <= held
    assert set(X_NAMES) <= held and set(X_ALIASES) <= held
    assert set(F_NAMES) <= held and {f"f{number}" for number in range(32)} <= held
    assert "x32" not in held and "f32" not in held


def test_the_control_registers_are_coloured_apart(made):
    """They are not registers of the machine and are not written like them, so they
    are their own kind of word."""
    assert words(made, "control-register") == set(CSRS)
    assert not words(made, "control-register") & words(made, "register")


def test_what_is_not_a_word_of_the_program(made):
    """Comments, strings, labels, numbers and the two shapes of a macro parameter
    are matched by their shape and not by a list."""
    for context in ("comment", "string", "character", "label", "number",
                    "relocation", "parameter"):
        assert made.find(f".//context[@id='{context}']") is not None, context


def test_everything_that_is_defined_is_used_exactly_once(made):
    """The one context that holds the rest names each of the others exactly once:
    a context nobody includes would colour nothing at all.

    The ORDER of them is not pinned here, because it changes nothing: no two of
    these contexts can begin at the same place - a comment begins with `#`, a
    string with `"`, and the lists of words are disjoint - and that was tried both
    ways through GtkSourceView itself before this was written.
    """
    inside = [one.get("ref") for one in
              made.findall(f".//context[@id='{ID}']/include/context")]
    assert len(inside) == len(set(inside))
    defined = {one.get("id") for one in made.findall(".//definitions/context")}
    assert set(inside) == defined - {ID}


def test_nothing_of_a_table_is_lost_on_the_way(made):
    """Every word in the file comes from a table of ours, and every word of those
    tables is in the file: one list, in two places, that cannot drift apart."""
    held = (words(made, "instruction") | words(made, "control-register")
            | words(made, "register"))
    ours = (set(instructions(64)) | set(CSRS) | set(registers()))
    assert held == ours


def test_a_name_with_a_character_xml_cannot_hold():
    """Nothing in our tables needs escaping today, and the day one does the file
    must still be readable."""
    from pyrars.ui.highlighting import _words

    assert "<keyword>a&amp;b</keyword>" in _words("register", ("a&b",))
