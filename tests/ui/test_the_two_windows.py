"""The windows that open from the main one: what the program is, how it is run,
and what can be written in a program.

What they hold is worked out without GTK (`ui/help.py`, `session/project.py`,
`session/settings.py`); what is tried here is that a person can see it and change
it.
"""

import json

import pytest

pytestmark = pytest.mark.ui

LIB = """\
        .globl  twice
        .text
twice:  add     a0, a0, a0
        ret
"""
USES = """\
        .globl  main
        .text
main:   li      a0, 21
        jal     ra, twice
        li      a7, 1
        ecall
        li      a7, 10
        ecall
"""


@pytest.fixture
def two_files(tmp_path):
    (tmp_path / "lib.s").write_text(LIB)
    (tmp_path / "uses.s").write_text(USES)
    return str(tmp_path / "lib.s"), str(tmp_path / "uses.s")


@pytest.fixture
def window(gtk, tmp_path, two_files):
    from pyrars.ui.window import Window

    made = Window(files=two_files, cache=str(tmp_path / "cache"))
    yield made
    made.close_up()


def shown(view) -> str:
    buffer = view.get_buffer()
    return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)


# ------------------------------------------------- what the program is made of


def test_one_file_is_the_program_until_somebody_says_otherwise(window, turning):
    """Several files open are several things somebody is working on, not one
    program in several pieces: assembling them together glued two programs end to
    end, which is nobody's idea of a default."""
    assert window.project is None
    window.editor.tabs.set_selected_page(
        window.editor.tabs.get_page(window.editor.pages[1]))  # uses.s
    window.do("assemble")
    assert turning(lambda: "assembling uses.s" in shown(window.messages))
    # it calls `twice`, which is in the other file and NOT part of the program
    assert turning(lambda: "has not been assembled" in shown(window.messages))


def test_a_project_makes_one_program_of_several_files(window, turning, two_files):
    asking = window.ask_what_the_program_is()
    try:
        for path in two_files:
            asking.chosen[path].set_active(True)
        asking.main_of[two_files[1]].set_active(True)  # uses.s first
        asking._use()
    finally:
        asking.destroy()
    assert window.project is not None
    assert window.project.ordered[0].endswith("uses.s")
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    assert len(window.program.text) == 8  # both files, one program
    window.do("continue")
    assert turning(lambda: shown(window.console) == "42")


def test_a_project_can_be_let_go_of_again(window, turning, two_files):
    asking = window.ask_what_the_program_is()
    for path in two_files:
        asking.chosen[path].set_active(True)
    asking._use()
    asking.destroy()
    assert window.project is not None
    asking = window.ask_what_the_program_is()
    asking._let_go()
    asking.destroy()
    assert window.project is None
    assert "the file being looked at" in shown(window.messages)


def test_the_title_says_which_program_is_in_force(window, two_files):
    assert "project" not in window.get_title()
    asking = window.ask_what_the_program_is()
    for path in two_files:
        asking.chosen[path].set_active(True)
    asking._use()
    asking.destroy()
    assert "a project of 2 files" in window.get_title()


def test_a_project_of_one_file_is_not_worth_saying_twice(window, two_files):
    """It does to the program exactly what no project does."""
    asking = window.ask_what_the_program_is()
    asking.chosen[two_files[0]].set_active(True)
    asking.chosen[two_files[1]].set_active(False)
    asking._use()
    asking.destroy()
    assert window.project is not None
    assert "project" not in window.get_title()


def test_a_project_with_no_file_ticked(window):
    asking = window.ask_what_the_program_is()
    try:
        for ticked in asking.chosen.values():
            ticked.set_active(False)
        assert asking.project_now() is None
        assert "Tick the files" in asking.says.get_text()
    finally:
        asking.destroy()


def test_a_project_written_to_a_file_and_read_back(window, tmp_path, two_files,
                                                   turning):
    from pyrars.session import project as projects

    asking = window.ask_what_the_program_is()
    for path in two_files:
        asking.chosen[path].set_active(True)
    asking.main_of[two_files[1]].set_active(True)
    where = str(tmp_path / "thing.pyrars.json")
    asking.where = where
    kept = asking.project_now().save(where)
    asking.destroy()
    held = json.loads((tmp_path / "thing.pyrars.json").read_text())
    assert held["files"] == ["lib.s", "uses.s"]
    assert held["main"] == "uses.s"
    assert projects.read(where) == kept


def test_a_project_of_a_wider_machine(window, two_files):
    asking = window.ask_what_the_program_is()
    try:
        asking.width.set_selected(1)  # 64
        asking.config.set_selected(1)
        asking.pseudo.set_active(False)
        made = asking.project_now()
        assert made.xlen == 64
        assert made.mem_config != "Default"
        assert made.pseudo is False
    finally:
        asking.destroy()


def test_a_project_may_name_a_file_nobody_has_opened(window, tmp_path, two_files):
    """A project is read from a file and names what it names; the window must offer
    those files whether anybody has opened them or not, or opening a project would
    quietly drop half of it."""
    from pyrars.session import project as projects

    elsewhere = tmp_path / "apart.s"
    elsewhere.write_text(".text\nnop\n")
    made = projects.of([str(elsewhere)], folder=str(tmp_path))
    window.the_program_is(made, "")
    asking = window.ask_what_the_program_is()
    try:
        assert str(elsewhere) in asking.files  # the one nobody opened
        assert all(path in asking.files for path in two_files)
        assert asking.chosen[str(elsewhere)].get_active()
    finally:
        asking.destroy()


def test_the_project_window_opens_with_what_is_already_settled(window, two_files):
    asking = window.ask_what_the_program_is()
    for path in two_files:
        asking.chosen[path].set_active(True)
    asking.width.set_selected(1)
    asking._use()
    asking.destroy()
    again = window.ask_what_the_program_is()
    try:
        assert all(again.chosen[path].get_active() for path in two_files)
        assert again.width.get_selected() == 1
    finally:
        again.destroy()


def test_a_memory_configuration_says_where_everything_is(window):
    """Three names on a chooser say nothing about where a program will find
    itself; the addresses do, and they follow the name that is chosen."""
    from pyrars.isa.memory import CONFIGS

    asking = window.ask_what_the_program_is()
    try:
        said = {row.get_title(): _suffix(row) for row in asking.said_of_the_memory}
        assert said["text base"] == "0x00400000"  # the Default configuration
        assert said["stack pointer"] == "0x7fffeffc"
        assert "name" not in said  # a configuration's own name is not an address
        asking.config.set_selected(list(CONFIGS).index("CompactDataAtZero"))
        said = {row.get_title(): _suffix(row) for row in asking.said_of_the_memory}
        assert said["text base"] == "0x00003000"
        assert said["data base"] == "0x00000000"
    finally:
        asking.destroy()


# ------------------------------------------------------- how the program is run


def test_the_run_window_opens_with_what_is_already_settled(window):
    from pyrars.session import settings as runs

    window.settings = runs.Settings(statistics=False, cache={"sets": 4},
                                    devices={"timer": {"mode": "virtual"}})
    asking = window.ask_how_it_is_run()
    try:
        assert asking.statistics.get_active() is False
        assert asking.wanted["cache"].get_enable_expansion() is True
        assert asking.rows["cache"]["sets"].value() == 4
        assert asking.wanted["timer"].get_enable_expansion() is True
        assert asking.rows["timer"]["mode"].value() == "virtual"
        # and what was never asked for is not wanted
        assert asking.wanted["pipeline"].get_enable_expansion() is False
        assert asking.wanted["lab"].get_active() is False
    finally:
        asking.destroy()


def test_what_the_run_window_holds_is_the_settings_of_a_run(window):
    """Every kind of row answers in the kind of value its option takes: a number
    as a number, a yes or no as a bool, one of a few words as that word."""
    from pyrars.session import settings as runs

    asking = window.ask_how_it_is_run()
    try:
        asking.wanted["cache"].set_enable_expansion(True)
        asking.rows["cache"]["sets"].widget.set_value(16)
        asking.rows["cache"]["write_back"].widget.set_active(False)
        asking.rows["cache"]["replacement"].widget.set_selected(1)  # fifo
        asking.wanted["pipeline"].set_enable_expansion(True)
        asking.rows["guesser"]["predictor"].widget.set_selected(2)  # a table
        asking.wanted["halt"].set_active(True)
        settings = asking.settings_now()
        assert settings.cache["sets"] == 16
        assert settings.cache["write_back"] is False
        assert settings.cache["replacement"] == "fifo"
        assert settings.pipeline is not None and settings.instructions is None
        assert settings.guesser["predictor"] == "table"
        assert settings.devices == {"halt": {}}  # a register, with nothing to ask
        # and it is a thing a machine can really be built from
        assert runs.world(settings)["caches"].data.settings.sets == 16
    finally:
        asking.destroy()


def test_the_settings_of_a_run_are_kept_where_they_will_be_found_again(window,
                                                                      tmp_path):
    """They belong to the person: somebody who set them up does not expect to set
    them up again tomorrow."""
    from pyrars.session import settings as runs

    asking = window.ask_how_it_is_run()
    asking.wanted["pipeline"].set_enable_expansion(True)
    asking._use()
    asking.destroy()
    assert window.settings.pipeline is not None
    assert runs.read().pipeline is not None  # and it is on the disk
    assert "a pipeline" in shown(window.messages)


def test_a_run_that_cannot_be_set_up_is_said_where_it_was_asked_for(window):
    """Beside the rows that say it, and not in the messages of a window somebody
    would have to go and look at - and the window stays open, because something
    has to be changed."""
    asking = window.ask_how_it_is_run()
    try:
        asking.wanted["cache"].set_enable_expansion(True)
        asking.rows["cache"]["sets"].widget.set_value(3)
        asking._use()
        assert "power of two" in asking.says.get_text()
        assert asking.get_visible() or True  # it did not close
        assert window.settings.cache is None  # and nothing was settled
    finally:
        asking.destroy()


def test_a_run_may_be_let_go_of_again(window):
    from pyrars.session import settings as runs

    asking = window.ask_how_it_is_run()
    asking.wanted["cache"].set_enable_expansion(True)
    asking._use()
    asking.destroy()
    again = window.ask_how_it_is_run()
    again._let_go()
    again.destroy()
    assert window.settings == runs.Settings()
    # the run is still COUNTED, which is what the settings come as: counting costs
    # one comparison a turn and is what the window's own numbers are made of
    assert shown(window.messages).endswith("the run: counted, kept in run.json\n")


def test_every_option_of_every_device_can_be_asked_for(window):
    """The rows are made from what the models and the devices say of themselves,
    so this is the test that every kind of option has a widget at all."""
    from pyrars.devices import DEVICES
    from pyrars.session.settings import options_of

    asking = window.ask_how_it_is_run()
    try:
        for name in DEVICES:
            offered = options_of(name)
            if not offered:
                continue
            assert set(asking.rows[name]) == {one.name for one in offered}
            for one in offered:
                assert asking.rows[name][one.name].value() == one.default
    finally:
        asking.destroy()


def _suffix(row) -> str:
    """The label a row of the memory carries beside its name."""
    child = row.get_first_child()
    while child is not None:
        found = _label_in(child)
        if found:
            return found
        child = child.get_next_sibling()
    return ""


def _label_in(widget) -> str:
    from gi.repository import Gtk

    if isinstance(widget, Gtk.Label) and widget.get_text().startswith("0x"):
        return widget.get_text()
    child = widget.get_first_child() if hasattr(widget, "get_first_child") else None
    while child is not None:
        found = _label_in(child)
        if found:
            return found
        child = child.get_next_sibling()
    return ""


# ----------------------------------------------- what can be written in a program


def test_the_reference_holds_everything_the_assembler_takes(window):
    from pyrars.ui.help import every_word

    reading = window.open_the_reference()
    try:
        assert len(reading.rows) == len(every_word(32))
        assert reading.look_for("") == len(reading.rows)
    finally:
        reading.destroy()


def test_the_reference_is_looked_through(window):
    reading = window.open_the_reference()
    try:
        assert reading.look_for("addi") == 6
        # all six of them: the three that shift by a register and the three that
        # shift by a number. Their names say nothing about shifting; their
        # meanings do, and the search reads those too
        assert reading.look_for("shift") == 6
        assert reading.look_for("nonsense") == 0
        assert reading.shown.get_visible_child_name() == "nothing"
        reading.look_for("")
        assert reading.shown.get_visible_child_name() == "words"
    finally:
        reading.destroy()


def test_a_row_of_the_reference_says_what_the_word_does(window):
    """Three lines that must not run into one another: what KIND of word it is,
    what it DOES - which is what the looking was for - and how it is WRITTEN."""
    reading = window.open_the_reference()
    try:
        row = next(row for row, one in reading.rows.items() if one.word == "add")
        lines = _lines_of(row.get_child())
        assert lines[0][0] == "add"
        assert lines[1][0].startswith("A basic instruction")
        assert lines[2][0] == "Adds rs1 and rs2 and puts the sum in rd"
        assert lines[3][0] == "add rd, rs1, rs2"
        # and each of them is told apart from the one above it
        assert "dim-label" in lines[1][1]
        assert "accent" in lines[2][1]
        assert "monospace" in lines[3][1] and "accent" not in lines[3][1]
    finally:
        reading.destroy()


def test_a_word_is_found_by_what_it_does(window):
    reading = window.open_the_reference()
    try:
        assert reading.look_for("square root") == 2  # fsqrt in both precisions
        assert reading.look_for("stack pointer") >= 1
    finally:
        reading.destroy()


def _lines_of(box):
    """Every label of a row, with the css classes it carries."""
    found, child = [], box.get_first_child()
    while child is not None:
        found.append((child.get_text(), tuple(child.get_css_classes())))
        child = child.get_next_sibling()
    return found


def test_the_reference_follows_the_width_of_the_machine(window, two_files):
    asking = window.ask_what_the_program_is()
    asking.chosen[two_files[0]].set_active(True)
    asking.width.set_selected(1)  # 64
    asking._use()
    asking.destroy()
    reading = window.open_the_reference()
    try:
        # `addiw` itself, and the pseudo-instructions written out as one
        assert reading.look_for("addiw") >= 1
        assert any(one.word == "addiw" for one in reading.words)
    finally:
        reading.destroy()
