"""What the window writes, worked out where no widget can be seen."""

from pyrars.isa.program import Diagnostic, SourceLoc
from pyrars.ui.shown import (
    CHANGED, ERROR, UNTITLED, WARNING, Problem, problems, said, tab_about, tab_title,
    window_title)


def test_a_tab_says_the_name_of_its_file():
    assert tab_title("/home/someone/programs/sum.s") == "sum.s"


def test_a_tab_says_that_a_file_has_been_changed():
    assert tab_title("/home/someone/sum.s", modified=True) == f"sum.s {CHANGED}"


def test_a_file_that_has_never_been_saved():
    assert tab_title(None) == UNTITLED
    assert tab_title(None, modified=True) == f"{UNTITLED} {CHANGED}"
    assert tab_about(None) == "not saved anywhere yet"


def test_a_tab_says_where_its_file_really_is(tmp_path):
    (tmp_path / "sum.s").write_text("")
    assert tab_about(str(tmp_path / "deeper" / ".." / "sum.s")) == str(
        tmp_path / "sum.s")


def test_what_the_program_is_called_in_the_title():
    from pyrars.ui.shown import project_called

    # one kept in a file is called by that file
    assert project_called("/home/someone/thing.pyrars.json", 3) == "thing.pyrars.json"
    # one made in the window is called by what it holds, which is all there is
    assert project_called("", 3) == "a project of 3 files"
    # and one of a single file is called nothing: it does to the program exactly
    # what no project does, and a title saying so twice says nothing
    assert project_called("", 1) == ""
    assert project_called("", 0) == ""


def test_the_window_says_what_is_being_worked_on():
    assert window_title("/home/someone/sum.s") == "sum.s - pyRARS"
    assert window_title("/home/someone/sum.s", False, "thing.pyrars.json") == (
        "sum.s - thing.pyrars.json - pyRARS")
    assert window_title("/home/someone/sum.s", True) == f"sum.s {CHANGED} - pyRARS"
    assert window_title(None) == f"{UNTITLED} - pyRARS"


# ------------------------------------------- what the assembler had to say


def diagnostic(kind: str, file: str | None, line: int, message: str) -> Diagnostic:
    return Diagnostic(kind, SourceLoc(file, line, 1) if file else None, message)


def test_the_speeds_a_run_may_be_held_to():
    from pyrars.session.control import EVERY
    from pyrars.ui.shown import SPEEDS, speed_text

    assert SPEEDS[0] is None  # as fast as it can, which is where everything begins
    assert speed_text(None) == "As fast as it can"
    assert speed_text(30.0) == "30 a second"  # and not "30.0 a second"
    assert speed_text(1.0) == "1 a second"
    assert len(set(SPEEDS)) == len(SPEEDS)
    chosen = [speed for speed in SPEEDS if speed is not None]
    assert chosen == sorted(chosen, reverse=True)  # the fastest first, as a list reads
    # A speed above the rate at which snapshots go out could not be told from any
    # other such speed: nothing on the screen would differ.
    assert max(chosen) <= 1 / EVERY
    assert min(chosen) > 0  # a run that carries out nothing is a run that is stopped


# ----------------------- the things around the machine, and the models of it


def _setting(name, value):
    from pyrars.session.debug import Setting

    return Setting(name, value)


def test_what_one_device_is_and_holds():
    """Where it answers comes first: that is what a program needs of a device, and
    the device itself never says it."""
    from pyrars.session.debug import DeviceSeen
    from pyrars.ui.shown import one_state

    seen = DeviceSeen("timer", 0x18, 16, {"clock": "virtual (1 ms)", "time": 256,
                                          "armed": False})
    rows = one_state(seen, base=0xFFFF0000)
    assert rows[0] == ("where", "0xffff0018")
    assert rows[1] == ("size", "16 bytes")
    assert rows[2] == ("clock", "virtual (1 ms)")  # its own words, as they come
    assert rows[3] == ("time", "0x00000100")  # a number, in the format chosen
    assert rows[4] == ("armed", "no")  # and never "False"
    assert one_state(seen, "dec", 0xFFFF0000)[3] == ("time", "256")
    assert one_state(None) == ()


def test_a_device_that_answers_no_address_of_its_own():
    """The bitmap display watches memory instead; a number there would be read as
    an address it answers at, and it answers at none."""
    from pyrars.session.debug import DeviceSeen
    from pyrars.ui.shown import one_state

    rows = one_state(DeviceSeen("bitmap", None, None, {"painted": "0 of 4"}),
                     base=0xFFFF0000)
    assert rows == (("where", "no address of its own"), ("painted", "0 of 4"))


def test_how_a_cache_was_built_and_how_it_has_fared():
    from pyrars.session.debug import CacheSeen
    from pyrars.ui.shown import caches

    seen = [CacheSeen("cache", True, (_setting("sets", 4), _setting("ways", 2)),
                      accesses=10, hits=7, misses=3, rate=0.7, writebacks=1,
                      through=0)]
    rows = caches(seen)
    assert rows[0] == ("cache", "sets", "4")  # a count is a count, never 0x4
    assert ("cache", "the instructions reach it", "yes") in rows
    assert ("cache", "accesses", "10") in rows
    assert ("cache", "hit rate", "0.7000") in rows
    assert ("cache", "written through", "0") in rows


def test_what_the_pipeline_counted_with_the_guesser_under_it():
    from pyrars.session.debug import GuesserSeen, PipelineSeen
    from pyrars.ui.shown import pipeline

    seen = PipelineSeen(cycle=-1, settings=(_setting("forwarding", True),),
                        cycles=48, instructions=31, cpi=48 / 31, lost=10,
                        stalls=(_setting("branch", 6), _setting("load", 4)),
                        branches=4, wrong=3)
    guesser = GuesserSeen("a table of 4 entries", (_setting("entries", 4),),
                          guesses=4, right=1, wrong=3, accuracy=0.25)
    rows = dict(pipeline(seen, guesser))
    assert rows["forwarding"] == "yes"
    assert rows["cycles"] == "48" and rows["cycles an instruction"] == "1.5484"
    assert rows["lost to branch"] == "6" and rows["cycles lost"] == "10"
    assert rows["guesser"] == "a table of 4 entries"
    assert rows["guesser entries"] == "4"
    assert rows["how often rightly"] == "0.2500"
    assert pipeline(None) == ()  # nobody asked for one


def test_what_the_run_was_made_of():
    from pyrars.session.debug import StatisticsSeen
    from pyrars.ui.shown import counted

    seen = StatisticsSeen(turns=31, instructions=31, traps=0, unknown=0, taken=3,
                          not_taken=1, kinds=(_setting("branch", 4),),
                          categories=(_setting("ALU", 20),))
    rows = dict(counted(seen))
    assert rows["instructions"] == "31" and rows["branches that went"] == "3"
    assert rows["of kind branch"] == "4"
    assert rows["alu instructions"] == "20"
    assert counted(None) == ()


def test_where_a_memory_configuration_puts_everything():
    from pyrars.isa.memory import CONFIGS
    from pyrars.ui.shown import memory

    rows = dict(memory(CONFIGS["Default"]))
    assert rows["text_base"] == "0x00400000"
    assert rows["stack_pointer"] == "0x7fffeffc"
    assert rows["mmio_base"] == "0xffff0000"
    assert "name" not in rows  # the name of a configuration is no address of one
    assert len(rows) == 16


def test_what_a_run_is_set_up_as_in_one_line():
    from pyrars.session.settings import Settings
    from pyrars.ui.shown import run_called

    assert run_called(Settings()) == "counted"
    assert run_called(Settings(statistics=False)) \
        == "nothing modelled and nothing attached"
    assert run_called(Settings(cache={}, fetches=True)) \
        == "counted; a cache of the data and of the instructions"
    assert run_called(Settings(cache={}, instructions={})) \
        == "counted; a cache of the data; a cache of the instructions of its own"
    assert run_called(Settings(statistics=False, pipeline={},
                               devices={"timer": {}, "halt": {}})) \
        == "a pipeline; halt, timer"


def test_what_was_said_is_sorted_by_the_file_it_was_said_about():
    by_file, loose = problems([
        diagnostic("Error", "main.s", 3, "nothing of the kind"),
        diagnostic("Warning", "lib.s", 7, "it might be meant"),
        diagnostic("Error", "main.s", 9, "nor that"),
    ])
    assert loose == ()
    assert by_file["main.s"] == (Problem(3, ERROR, "nothing of the kind"),
                                 Problem(9, ERROR, "nor that"))
    assert by_file["lib.s"] == (Problem(7, WARNING, "it might be meant"),)


def test_what_was_said_about_no_place_at_all():
    """It belongs to no line and cannot be marked in the margin of anything, so it
    comes back on its own for a window to say somewhere a person will see it."""
    by_file, loose = problems([diagnostic("Error", None, 0, "the whole thing is wrong")])
    assert by_file == {}
    assert loose == ("the whole thing is wrong",)


def test_nothing_was_said_at_all():
    assert problems(()) == ({}, ())


def test_what_the_margin_of_a_line_says():
    assert said([Problem(3, ERROR, "nothing of the kind"),
                 Problem(3, WARNING, "and this too")]) == (
        "error: nothing of the kind\nwarning: and this too")


# ------------------------------------------------- the views of the machine

from pyrars.session.control import Snapshot  # noqa: E402
from pyrars.session.debug import (  # noqa: E402
    FrameSeen, Item, Place, Stopped, Symbol, Value)
from pyrars.isa.program import TextEntry  # noqa: E402
from pyrars.ui.shown import (  # noqa: E402
    BREAK, HERE, control, data, floats, frames, labels, registers, standing, text)


def test_which_cell_goes_in_which_column():
    from pyrars.ui.shown import cell

    assert cell(("a", "b", "c"), 1) == "b"
    # a row may be shorter than the table is wide, and a column shows something
    # either way: a place with no source line, a frame with no name
    assert cell(("a",), 2) == ""
    assert cell((), 0) == ""


def test_the_registers_as_rows():
    assert registers([Value("t0", 5, 0x1234, 32), Value("zero", 0, 0, 32)]) == (
        ("t0", "x5", "0x00001234"), ("zero", "x0", "0x00000000"))


def test_the_registers_in_the_format_chosen():
    assert registers([Value("t0", 5, 0xFFFFFFFF, 32)], "dec")[0][2] == "-1"
    assert registers([Value("t0", 5, 0x41424344, 32)], "ascii")[0][2] == "  A  B  C  D"


def test_a_register_of_a_wider_machine_shows_every_digit():
    assert registers([Value("t0", 5, 1, 64)])[0][2] == "0x0000000000000001"


def test_the_floating_point_registers_show_their_bits_as_bits():
    """A float read as a signed number says nothing to anybody, so the bits are
    bits whatever format was chosen for the rest."""
    value = Value("ft1", 1, 0x3FF0000000000000, 64, "1.0", "f")
    assert floats([value], "dec") == (
        ("ft1", "f1", "0x3ff0000000000000", "1.0"),)


def test_the_control_registers_spell_out_what_they_hold():
    """Which is what the "flags" of another machine would be (the entry of M8)."""
    value = Value("fcsr", 3, 0x8, 32, "flags 0x08, rounding 0", "csr")
    assert control([value]) == (
        ("fcsr", "0x003", "0x00000008", "flags 0x08, rounding 0"),)


def entry(address: int, basic: str, source: str) -> TextEntry:
    return TextEntry(address, 0x13, basic, None, source)


def test_the_text_segment_as_rows():
    assert text([entry(0x400000, "addi x5,x0,3", "main:   li t0, 3")]) == (
        ("", "0x00400000", "0x00000013", "addi x5,x0,3", "main:   li t0, 3"),)


def test_the_text_segment_marks_where_the_machine_stands():
    rows = text([entry(0x400000, "a", "a"), entry(0x400004, "b", "b")],
                here=0x400004)
    assert [row[0] for row in rows] == ["", HERE]


def test_the_text_segment_marks_what_the_run_stops_before():
    rows = text([entry(0x400000, "a", "a"), entry(0x400004, "b", "b")],
                breaks={0x400000})
    assert [row[0] for row in rows] == [BREAK, ""]


def test_a_place_that_is_both_is_marked_as_both():
    rows = text([entry(0x400000, "a", "a")], here=0x400000, breaks={0x400000})
    assert rows[0][0] == BREAK + HERE


def test_the_data_segment_as_the_directives_wrote_it():
    items = [Item(0x10010000, ".word", 4, (3,)),
             Item(0x10010004, ".asciz", 3, (0x6968,), "hi")]
    assert data(items) == (
        ("0x10010000", ".word", "4", "0x00000003", ""),
        # three bytes are shown as three bytes, not padded out to a word
        ("0x10010004", ".asciz", "3", "0x006968", "hi"))


def test_the_data_segment_in_the_format_chosen():
    assert data([Item(0x10010000, ".word", 4, (65,))], "dec")[0][3] == "65"


def test_a_thing_of_several_words():
    assert data([Item(0x10010000, ".space", 8, (1, 2))])[0][3] == (
        "0x00000001 0x00000002")


def test_the_labels_say_how_far_they_reach():
    assert labels([Symbol("main", 0x400000, True), Symbol("loop", 0x400010, False)]) == (
        ("main", "0x00400000", "global"), ("loop", "0x00400010", "local"))


def place(address: int, symbol: str = "") -> Place:
    return Place(address, symbol=symbol)


def test_the_frames_of_the_calls_the_run_is_inside():
    assert frames([FrameSeen(1, place(0x400034, "keep"), place(0x400024), 0x7FFFEFFC)]) == (
        ("1", "0x00400034 <keep>", "0x00400024", "0x7fffeffc"),)


def test_a_frame_whose_stack_pointer_nobody_saw():
    assert frames([FrameSeen(1, place(0x400034), place(0x400024), None)])[0][3] == "?"


def test_the_line_that_says_where_the_run_is():
    shot = Snapshot("standing", Place(0x400010, basic="lw x28,0(x5)"), 7, 7, 7,
                    Stopped("breakpoint", Place(0x400010)))
    assert standing(shot) == (
        "standing  |  0x00400010  |  lw x28,0(x5)  |  7 carried out  |  "
        "7 to take back  |  breakpoint")


def test_the_line_before_anything_is_open():
    assert standing(Snapshot("nothing")) == "nothing  |  0 carried out"
