"""The console debugger: whole sessions driven by a script, read as transcripts.

RARS has no console debugger at all, so nothing here is held against it (D21); what
a session answers with is held against the program, whose addresses run from the
text base four bytes to an instruction and whose counts are worked out by hand.

The shape of every line is the one decided on 2026-10-14: the pieces separated by
" | ", the columns of a table padded so they stand under one another, and one line
after every movement saying where the machine stands.
"""

import io

import pytest

from pyrars.cli import main
from pyrars.console import BY_NAME, COMMANDS, Debugger, value_text
from pyrars.session.debug import Session

# The program of the session tests, so that its addresses are already derived:
# main 0x400000, loop 0x400010, the call 0x400024, keep 0x400034; `la` is two
# instructions, a turn of the loop is five, and the whole run is 31.
SUM = """\
.globl main
.data
table:  .word 1, 2, 3, 4
total:  .word 0
msg:    .asciz "hi"
.text
main:   la t0, table
        li t1, 4
        li t2, 0
loop:   lw t3, 0(t0)
        add t2, t2, t3
        addi t0, t0, 4
        addi t1, t1, -1
        bne t1, x0, loop
        jal ra, keep
        li a7, 93
        li a0, 0
        ecall
keep:   la t0, total
        sw t2, 0(t0)
        ret
"""
SETUP, TURN, WHOLE = 4, 5, 31

# A program that asks for a line and prints it back.
ASKS = """\
.globl main
.data
prompt: .asciz "name? "
buffer: .space 32
.text
main:   li a7, 4
        la a0, prompt
        ecall
        li a7, 8
        la a0, buffer
        li a1, 32
        ecall
        li a7, 4
        la a0, buffer
        ecall
        li a7, 93
        li a0, 0
        ecall
"""


# A program that reads a line and prints nothing at all, so that the only thing
# on its line of the terminal is the prompt that asked for the line.
READS = """\
.globl main
.data
buffer: .space 32
.text
main:   li a7, 8
        la a0, buffer
        li a1, 32
        ecall
        li a7, 93
        li a0, 0
        ecall
"""

# A program that writes a character to the display of the keyboard device and
# waits for the display to take it (the delay is five instructions by default).
SHOWS = """\
.globl main
.text
main:   li t0, 0xffff000c
        li t1, 65
        sw t1, 0(t0)
        nop
        nop
        nop
        nop
        nop
        nop
        li a7, 93
        li a0, 0
        ecall
"""


def session(tmp_path, *commands, source: str = SUM, given: str = "", flags=(),
            files=()):
    """A scripted session, as a transcript."""
    path = tmp_path / "p.s"
    path.write_text(source)
    asked = []
    for command in commands:
        asked += ["-e", command]
    out, errors = io.StringIO(), io.StringIO()
    code = main(["run", "--debug-mode", str(path), *flags, *files, *asked],
                out=out, errors=errors, reader=io.StringIO(given))
    return code, out.getvalue(), errors.getvalue()


def lines(text: str) -> list[str]:
    return text.splitlines()


def answer(text: str, after: str) -> list[str]:
    """The lines a command answered with: those after its prompt, up to the next."""
    found, taking = [], False
    for line in lines(text):
        if line.startswith("(pyrars) "):
            if taking:
                break
            taking = line == f"(pyrars) {after}"
            continue
        if taking:
            found.append(line)
    return found


def spoken(text: str, command: str) -> str:
    """The one line a command answered with."""
    said = answer(text, command)
    assert len(said) == 1, said
    return said[0]


def fields(line: str) -> list[str]:
    """The pieces of a line. The separator is " | " with its spaces, so a bare "|"
    inside a word of the help - `read|write|both` - is not one."""
    return [piece.strip() for piece in line.split(" | ")]


# ---------------------------------------------------------------- the transcript


def test_a_session_echoes_what_it_was_told(tmp_path):
    _, out, _ = session(tmp_path, "where", "quit")
    assert lines(out)[0] == "(pyrars) where"
    assert lines(out)[2] == "(pyrars) quit"


def test_a_line_is_made_of_pieces_divided_by_a_bar(tmp_path):
    _, out, _ = session(tmp_path, "where")
    assert fields(spoken(out, "where")) == [
        "0x00400000 <main>", "auipc x5,0x0fc10", "main:   la t0, table", "p.s:7"]


def test_the_columns_of_a_table_stand_under_one_another(tmp_path):
    _, out, _ = session(tmp_path, "step 4", "regs zero t1 sp")
    said = answer(out, "regs zero t1 sp")
    assert said == ["zero | x0 | 0x00000000",
                    "t1   | x6 | 0x00000004",
                    "sp   | x2 | 0x7fffeffc"]
    assert len({len(line.split("|")[0]) for line in said}) == 1  # one width


def test_a_row_says_nothing_where_it_has_nothing_to_say(tmp_path):
    """No row ends in a bar with nothing after it: the second word of a `la` has no
    line of the program to show, and the row simply stops."""
    _, out, _ = session(tmp_path, "list keep 3")
    for line in answer(out, "list keep 3"):
        assert not line.rstrip().endswith("|")
    assert any("addi x5,x5,-36" in line for line in answer(out, "list keep 3"))


def test_an_empty_line_repeats_the_last_command(tmp_path):
    _, out, _ = session(tmp_path, "step", "", "")
    assert lines(out).count("(pyrars) step") == 3
    assert spoken(out, "step").startswith("stepped 1")


def test_a_comment_is_no_command(tmp_path, tmp_path_factory):
    file = tmp_path / "script"
    file.write_text("# nothing but a comment\nstep 2  # and one after a command\n")
    _, out, errors = session(tmp_path, "quit", files=("--commands", str(file)))
    assert lines(out)[0] == "(pyrars) step 2"  # the comment left no line at all
    assert errors == ""


def test_the_commands_of_a_file_come_before_those_of_the_command_line(tmp_path):
    file = tmp_path / "script"
    file.write_text("step 2\n")
    _, out, _ = session(tmp_path, "step", files=("--commands", str(file)))
    assert [line for line in lines(out) if line.startswith("(pyrars) ")
            and line.strip() != "(pyrars)"] == ["(pyrars) step 2", "(pyrars) step"]


def test_an_answer_that_says_no_is_still_an_answer(tmp_path):
    """A command nobody has is answered on the output, with everything else; the
    error stream is for the failures of the tool itself."""
    _, out, errors = session(tmp_path, "nonsense")
    assert spoken(out, "nonsense") == 'error | no command "nonsense": try help'
    assert errors == ""


def test_the_session_ends_when_the_input_does(tmp_path):
    code, out, _ = session(tmp_path, "step")  # no quit: the input simply ends
    assert code == 0
    assert lines(out)[-1] == "(pyrars) "


# ----------------------------------------------------------------- the movement


def test_one_line_after_every_movement(tmp_path):
    """The decision of 2026-10-14: a movement always says where the machine
    stands, in one line."""
    _, out, _ = session(tmp_path, "step", "step 3", "back", "until loop", "where")
    for command in ("step", "step 3", "back", "until loop", "where"):
        assert len(answer(out, command)) == 1


def test_what_each_movement_says(tmp_path):
    _, out, _ = session(tmp_path, "step 4", "back 2", "until keep", "finish")
    assert spoken(out, "step 4").startswith(f"stepped {SETUP} | 0x00400010 <loop>")
    assert spoken(out, "back 2").startswith("stepped 2 | 0x00400008")
    assert spoken(out, "until keep").startswith("stepped")
    assert "0x00400034 <keep>" in spoken(out, "until keep")
    # the two halves of the `la`, the `sw` and the `ret`
    assert spoken(out, "finish").startswith("stepped 4 | 0x00400028 <loop+24>")


def test_over_a_call_and_its_guess(tmp_path):
    _, out, _ = session(tmp_path, "until 0x00400024", "over")
    assert spoken(out, "over").startswith("stepped 5 | 0x00400028")
    assert "GUESS" in BY_NAME["over"].about  # and the help says it is one


def test_a_run_to_the_end_and_what_follows_it(tmp_path):
    code, out, _ = session(tmp_path, "continue", "step")
    assert spoken(out, "continue").startswith(f"exited 0 after {WHOLE}")
    assert answer(out, "step") == [
        "ended | 0x00400034 <keep> | auipc x5,0x0fc10 | keep:   la t0, total | p.s:19",
        "the run is over: restart it, or take a step back"]
    assert code == 0


def test_a_step_back_reaches_over_the_end_of_a_run(tmp_path):
    _, out, _ = session(tmp_path, "continue", "back", "step")
    assert spoken(out, "back").startswith("stepped 1 | 0x00400030")  # on the `ecall`
    # the run goes on again, and carrying the `ecall` out ends it a second time
    assert spoken(out, "step").startswith("exited 0 after 0")


def test_the_tool_ends_with_what_the_program_ended_with(tmp_path):
    source = SUM.replace("li a0, 0", "li a0, 7")
    code, out, _ = session(tmp_path, "continue", source=source)
    assert spoken(out, "continue").startswith("exited 7")
    assert code == 7


def test_a_restart_says_so_and_begins_again(tmp_path):
    _, out, _ = session(tmp_path, "step 4", "restart", "count")
    assert spoken(out, "restart") == (
        "restarted | 0x00400000 <main> | auipc x5,0x0fc10 | "
        "main:   la t0, table | p.s:7")
    assert answer(out, "count")[0] == "instructions | 0"


def test_a_movement_runs_no_further_than_the_steps_it_was_allowed(tmp_path):
    """`--steps` limits one movement of a session, so that a program without an
    end cannot catch a script for ever."""
    _, out, _ = session(tmp_path, "continue", "continue", flags=("--steps", "3"))
    assert spoken(out, "continue").startswith("limit after 3")


# ------------------------------------------------------------------- the places


def test_breakpoints_from_the_session(tmp_path):
    _, out, _ = session(tmp_path, "break add keep", "break list", "continue",
                        "break del 1", "break list")
    assert spoken(out, "break add keep").startswith("1 | 0x00400034 <keep>")
    assert spoken(out, "break list").startswith("1 | 0x00400034 <keep>")
    assert spoken(out, "continue").startswith(
        f"breakpoint 1 after {SETUP + 4 * TURN + 1}")
    assert spoken(out, "break del 1").startswith("gone | 1 | 0x00400034")
    assert lines(out)[-2] == "no breakpoints"  # the second asking, after the taking off


def test_a_breakpoint_from_the_command_line(tmp_path):
    _, out, _ = session(tmp_path, "break list", "continue",
                        flags=("--break", "0x00400010"))
    assert spoken(out, "break list").startswith("1 | 0x00400010 <loop>")
    assert spoken(out, "continue").startswith(f"breakpoint 1 after {SETUP}")


def test_the_word_after_a_two_level_command(tmp_path):
    _, out, _ = session(tmp_path, "break sideways")
    assert spoken(out, "break sideways") == (
        'error | "sideways": the word after it is add, del, list')


def test_a_watch_and_what_touched_it(tmp_path):
    _, out, _ = session(tmp_path, "watch add total write", "watch list", "continue",
                        "watch list")
    assert spoken(out, "watch add total write") == (
        "1 | write | 0x10010010..0x10010013 | hits 0")
    assert answer(out, "continue") == [
        "touched 1 | write | 0x10010010 | 4 bytes | 0x0000000a | by 0x0040003c <keep+8>",
        "watchpoint 1 after 28 | 0x00400040 <keep+12> | jalr x0,x1,0 | ret | p.s:21"]
    assert lines(out)[-2] == "1 | write | 0x10010010..0x10010013 | hits 1"


def test_a_watch_over_a_range(tmp_path):
    _, out, _ = session(tmp_path, "watch add table..0x1001000f read", "continue")
    assert "touched 1 | read | 0x10010000 | 4 bytes | 0x00000001" in answer(
        out, "continue")[0]


# -------------------------------------------------------------------- the views


def test_the_listing_marks_the_machine_and_the_breakpoints(tmp_path):
    _, out, _ = session(tmp_path, "break add loop", "list loop 3")
    said = answer(out, "list loop 3")
    assert fields(said[1])[:3] == ["", "1", "0x00400010 <loop>"]
    _, out, _ = session(tmp_path, "list")
    assert fields(answer(out, "list")[0])[0] == "->"


def test_the_lines_of_the_program(tmp_path):
    _, out, _ = session(tmp_path, "until loop", "source 3")
    assert answer(out, "source 3") == [
        "   | 9  |         li t2, 0",
        "-> | 10 | loop:   lw t3, 0(t0)",
        "   | 11 |         add t2, t2, t3"]


def test_the_registers_of_every_file(tmp_path):
    _, out, _ = session(tmp_path, "regs t2", "fregs f1", "csr fcsr")
    assert spoken(out, "regs t2") == "t2 | x7 | 0x00000000"
    assert spoken(out, "fregs f1") == "ft1 | f1 | 0x0000000000000000 | 0.0"
    assert spoken(out, "csr fcsr") == "fcsr | 0x003 | 0x00000000 | flags 0x00, rounding 0"


def test_a_name_no_register_has(tmp_path):
    _, out, _ = session(tmp_path, "regs t9")
    assert spoken(out, "regs t9") == 'error | "t9": no register of that name'


def test_the_words_of_memory_and_the_data(tmp_path):
    _, out, _ = session(tmp_path, "continue", "mem table..0x1001000f", "data")
    assert spoken(out, "mem table..0x1001000f") == (
        "0x10010000 | 0x00000001 | 0x00000002 | 0x00000003 | 0x00000004")
    said = answer(out, "data")
    assert said[4] == "0x10010010 | .word  | 4 | 0x0000000a"
    assert said[5] == '0x10010014 | .asciz | 3 | 0x006968   | "hi"'


def test_one_place_is_one_word(tmp_path):
    _, out, _ = session(tmp_path, "mem total")
    assert spoken(out, "mem total") == "0x10010010 | 0x00000000"


def test_the_stack_and_the_frames(tmp_path):
    _, out, _ = session(tmp_path, "break add keep", "continue", "stack 2", "frames")
    assert answer(out, "stack 2")[0].endswith("| frame 1 keep")
    assert spoken(out, "frames").startswith("1 | 0x00400034 <keep>")
    assert "from 0x00400024 <loop+20>" in spoken(out, "frames")
    assert "GUESS" in BY_NAME["frames"].about


def test_the_names_of_the_program(tmp_path):
    _, out, _ = session(tmp_path, "symbols ma")
    assert answer(out, "symbols ma") == ["main | 0x00400000 | global"]


def test_where_the_run_is_in_time(tmp_path):
    _, out, _ = session(tmp_path, "step 3", "count")
    assert answer(out, "count") == ["instructions | 3", "turns        | 0",
                                    "back         | 3"]


def test_the_format_of_a_value(tmp_path):
    _, out, _ = session(tmp_path, "step 4", "format", "format dec", "regs t1",
                        "format sideways")
    assert spoken(out, "format") == "format | hex"
    assert spoken(out, "format dec") == "format | dec"
    assert spoken(out, "regs t1") == "t1 | x6 | 4"
    assert spoken(out, "format sideways") == (
        'error | "sideways": values are written as hex, dec, ascii')


def test_the_help_of_every_command(tmp_path):
    _, out, _ = session(tmp_path, "help", "help sideways")
    said = answer(out, "help")
    assert len(said) == len(COMMANDS) + 1  # every command, and the line about "?"
    assert said[0].startswith("movement | step")
    assert said[-1] == (
        '"? COMMAND" says what that one is given, argument by argument, '
        "and what else it may be called")
    assert spoken(out, "help sideways") == 'error | no command "sideways": try help'


def test_a_question_mark_is_the_same_command(tmp_path):
    _, out, _ = session(tmp_path, "?", "help")
    assert answer(out, "?") == answer(out, "help")


def test_the_help_of_one_command_is_a_synopsis_and_then_its_arguments(tmp_path):
    """The first line is the command itself - what it is called, what it takes and
    what it is for - and only what follows `Args:` is a table, so that nothing of
    the heading can be taken for an argument (user decision 2026-10-14)."""
    _, out, _ = session(tmp_path, "? over")
    assert answer(out, "? over") == [
        "over, o, next, n [N] -- like step, but a call is passed over - "
        "a GUESS from the convention",
        "Args:",
        "N | how many, 1 by default"]


def test_the_help_of_a_two_level_command_explains_every_word_of_it(tmp_path):
    _, out, _ = session(tmp_path, "? watch")
    said = answer(out, "? watch")
    assert said[0] == (
        "watch [add RANGE [read|write|both] || del N|all || list] -- "
        "stop when the program touches a place in memory")
    assert said[1] == "Args:"
    assert [fields(line)[0] for line in said[2:]] == [
        "add RANGE", "read|write|both", "del N|all", "list", "RANGE"]
    about = {fields(line)[0]: fields(line)[1] for line in said[2:]}
    assert about["read|write|both"] == "what to watch for, both by default"
    assert about["RANGE"].startswith("ADDRESS, or LOW..HIGH")


def test_the_help_says_what_a_command_given_nothing_does(tmp_path):
    _, out, _ = session(tmp_path, "? format")
    said = answer(out, "? format")
    assert said[0] == "format [hex|dec|ascii] -- how values are written"
    about = {fields(line)[0]: fields(line)[1] for line in said[2:]}
    assert about["nothing"] == "the format it is now, when none is given"
    assert about["ascii"].startswith("as the characters of its bytes")


def test_a_command_that_takes_nothing_is_one_line(tmp_path):
    _, out, _ = session(tmp_path, "? where")
    assert answer(out, "? where") == ["where, w -- where the machine stands"]


def test_the_heading_of_a_help_is_never_a_row_of_a_table():
    """What divides the pieces of a table is " | " with its spaces. No synopsis may
    hold one, or the heading would read as an argument of itself: the forms of a
    command are divided by "||" and the choices inside one slot by a bare "|".
    """
    from pyrars.console import _synopsis

    for command in COMMANDS:
        line = _synopsis(command)
        assert " | " not in line, line
        assert " -- " in line, line
        assert line.startswith(command.name), line


def test_every_argument_of_every_command_is_explained():
    """Self-validating, like the tables of `pyrars.isa`: a command is written in two
    places - what it takes and what each of those means - and a new argument must
    not be able to arrive in one without the other.
    """
    for command in COMMANDS:
        explained = " ".join(name for name, _ in command.arguments)
        for word in command.takes.replace("|", " ").replace("[", " ").split():
            word = word.strip("].").removesuffix("...")
            if word.isupper() and word.isalpha():
                assert word in explained, f"{command.name} says nothing of {word}"
        for name, about in command.arguments:
            assert about, f"{command.name} explains {name} with nothing"


# ------------------------------------------- the things around the machine


def test_what_was_never_asked_for_says_so_the_same_way(tmp_path):
    _, out, _ = session(tmp_path, "cache info", "pipeline show", "guesser info",
                        "stats", "device list")
    assert spoken(out, "cache info") == "error | no cache was asked for: run with --cache"
    assert spoken(out, "pipeline show") == (
        "error | no pipeline was asked for: run with --pipeline")
    assert spoken(out, "guesser info") == (
        "error | no guesser was asked for: run with --pipeline")
    assert spoken(out, "stats") == (
        "error | no statistics were asked for: run with --stats")
    assert spoken(out, "device list") == (
        "error | no device is attached: run with --device")


def test_the_caches_of_a_session(tmp_path):
    _, out, _ = session(tmp_path, "continue", "cache info", "cache show",
                        flags=("--cache", "sets=4"))
    said = answer(out, "cache info")
    assert "cache | sets           | 4" in said
    assert "cache | accesses       | 5" in said  # four words read and one written
    assert answer(out, "cache show") == [
        "cache | set 0 | place 0 | 0x10010000..0x1001000f | clean",
        "cache | set 1 | place 0 | 0x10010010..0x1001001f | dirty"]


def test_a_cache_for_everything_hears_the_instructions_too(tmp_path):
    """A cache for everything is the same object as a cache of the data alone, so
    the session is TOLD which was meant and does not guess."""
    _, out, _ = session(tmp_path, "continue", "cache info",
                        flags=("--cache", "unified:sets=4"))
    said = answer(out, "cache info")
    assert "cache | accesses       | 36" in said  # 31 instructions and five accesses


def test_the_pipeline_and_its_guesser(tmp_path):
    _, out, _ = session(tmp_path, "continue", "pipeline info", "pipeline show",
                        "guesser info", "guesser show",
                        flags=("--pipeline", "predictor=table,entries=4,bits=2"))
    assert "instructions | 31" in answer(out, "pipeline info")
    assert answer(out, "pipeline show")[0] == "0x00400000 | auipc | 0 1 2 3 4"
    assert "guesser  | a table of 4 entries of 2 bits" in answer(out, "guesser info")
    assert answer(out, "guesser show")[0] == "0 | 2 | taken     | right 1 | wrong 3"


def test_a_guesser_without_a_table(tmp_path):
    _, out, _ = session(tmp_path, "guesser show", flags=("--pipeline",))
    assert spoken(out, "guesser show") == (
        "error | no table of history was asked for: run with "
        "--pipeline predictor=table")


def test_a_device_shows_itself(tmp_path):
    _, out, _ = session(tmp_path, "device list", "device keyboard", "device nothing",
                        flags=("--device", "keyboard"))
    assert spoken(out, "device list") == "keyboard | 0xffff0000 | 16 bytes"
    said = answer(out, "device keyboard")
    # nothing shown yet, and it says so; the name is padded to the widest of them,
    # which is "characters lost"
    assert said[0] == "shown           | -"
    assert "mode            | scrolling" in said
    # and both the things it can lose, which is what the device is there to show
    assert "keys lost       | 0" in said
    assert "characters lost | 0" in said
    assert spoken(out, "device nothing") == (
        'error | "nothing": no device of that name is attached')


def test_what_a_run_was_made_of(tmp_path):
    _, out, _ = session(tmp_path, "continue", "stats", flags=("--stats",))
    said = answer(out, "stats")
    assert "instructions       | 31" in said
    assert "kind.load          | 4" in said


# ------------------------------------------------------------------ the changes


def test_a_value_put_in_a_register_or_in_memory(tmp_path):
    _, out, _ = session(tmp_path, "set t0 0x1234", "set fcsr 8", "set ft1 1",
                        "poke total 0x41424344", "mem total", "poke total 0x55 1")
    assert spoken(out, "set t0 0x1234") == "t0 | x5 | 0x00001234"
    assert spoken(out, "set fcsr 8") == "fcsr | 0x003 | 0x00000008 | flags 0x08, rounding 0"
    assert spoken(out, "set ft1 1").endswith("| 5.0E-324")
    assert spoken(out, "poke total 0x41424344") == "0x10010010 | 0x41424344"
    assert spoken(out, "mem total") == "0x10010010 | 0x41424344"
    assert spoken(out, "poke total 0x55 1") == "0x10010010 | 0x55"


def test_what_a_person_put_there_is_not_taken_back(tmp_path):
    _, out, _ = session(tmp_path, "step 4", "set s1 0x99", "back 2", "regs s1")
    assert spoken(out, "regs s1") == "s1 | x9 | 0x00000099"


def test_a_value_a_register_cannot_take(tmp_path):
    _, out, _ = session(tmp_path, "set", "set t0", "poke total")
    assert spoken(out, "set") == "error | set needs a register and a value"
    assert spoken(out, "set t0") == "error | set needs a register and a value"
    assert spoken(out, "poke total") == "error | poke needs an address and a value"


def test_a_place_nobody_has(tmp_path):
    _, out, _ = session(tmp_path, "until elsewhere", "break add p.s:3")
    assert spoken(out, "until elsewhere") == (
        'error | "elsewhere": no such place in the program')
    assert spoken(out, "break add p.s:3") == (
        'error | "p.s:3": no instruction of the program is there')


# ------------------------------------------------- one terminal for two of them


def test_the_program_says_whose_turn_it_is_to_type(tmp_path):
    code, out, _ = session(tmp_path, "continue", source=ASKS, given="Ann\n")
    assert "name? program> hello" not in out  # the program prints no greeting here
    assert "name? program> " in out  # its own prompt, then ours
    assert "Ann" in out  # and what it read, printed back


def test_a_program_that_wrote_no_newline_keeps_its_own_line(tmp_path):
    _, out, _ = session(tmp_path, "continue", "where", source=ASKS, given="Ann\n")
    said = [line for line in lines(out) if line.startswith("exited")]
    assert len(said) == 1  # the summary is on a line of its own, not glued to "Ann"


def test_a_step_back_does_not_take_the_transcript_back(tmp_path):
    """The terminal is shared with the debugger, and what has been printed has been
    seen: a step back must not cut the debugger's own lines off the stream, however
    cuttable the stream looks (DEV-53)."""
    _, out, _ = session(tmp_path, "continue", "back 3", "where", source=ASKS,
                        given="Ann\n")
    assert "(pyrars) continue" in out  # everything said before the step back stands
    assert "(pyrars) back 3" in out
    assert len(answer(out, "where")) == 1


def test_a_program_of_its_own_streams(tmp_path):
    speaking = tmp_path / "said"
    listening = tmp_path / "heard"
    listening.write_text("Bob\n")
    _, out, _ = session(tmp_path, "continue", source=ASKS,
                        files=("--program-output", str(speaking),
                               "--program-input", str(listening)))
    assert "Bob" in speaking.read_text()
    assert "Bob" not in out  # the terminal of the debugger stays its own
    assert "program> " not in out


def test_a_name_is_never_taken_from_another_segment(tmp_path):
    """The nearest name at or below an address is the one it falls under, but only
    inside its own segment: the labels of a program divide its text and its data
    between them, and a label of the text says nothing about a place in the data.
    """
    _, out, _ = session(tmp_path, "break add 0x10000000", "break list")
    # nothing of the program lies at or below this place in the data segment, and
    # nothing is there to disassemble either, so the row says the address and stops
    assert spoken(out, "break add 0x10000000") == "1 | 0x10000000"
    assert "<keep" not in spoken(out, "break list")
    # while a place inside the text does fall under the name before it
    _, out, _ = session(tmp_path, "break add 0x00400038", "break list")
    assert spoken(out, "break list").startswith("1 | 0x00400038 <keep+4>")


def test_the_prompt_of_the_program_keeps_the_debugger_off_its_line(tmp_path):
    """A program that printed nothing before it asked for a line leaves the
    terminal standing after `program> `, and what the debugger says next begins a
    line of its own."""
    _, out, _ = session(tmp_path, "continue", source=READS, given="Ann\n")
    assert "program> " in out
    for line in lines(out):
        assert not (line.startswith("program> ") and "exited" in line)
    assert any(line.startswith("exited 0 after") for line in lines(out))


def test_a_restart_asks_the_person_again(tmp_path):
    """A restart is a FRESH run (user decision 2026-10-21): the world outside is
    not put back with it, so a program that asks for a line asks again.

    It was the other way at first - a restart put back what had been read, by the
    same reasoning as a step back - and watching it, a program that silently did
    not ask was of no use to anybody. A step back is unchanged.
    """
    _, out, _ = session(tmp_path, "continue", "restart", "continue", source=ASKS,
                        given="Ann\nBob\n")
    assert out.count("program> ") == 2  # asked once for each run
    assert "Ann" in out and "Bob" in out  # and given a different line each time


def test_a_restart_puts_a_device_back_where_it_began(tmp_path):
    _, out, _ = session(tmp_path, "continue", "device keyboard", "restart",
                        source=SHOWS, flags=("--device", "keyboard"))
    assert answer(out, "device keyboard")[0] == "shown           | A"
    _, out, _ = session(tmp_path, "continue", "restart", "device keyboard",
                        source=SHOWS, flags=("--device", "keyboard"))
    assert answer(out, "device keyboard")[0] == "shown           | -"


def test_the_format_of_the_command_line_is_the_format_of_the_session(tmp_path):
    _, out, _ = session(tmp_path, "step 4", "regs t1", "format",
                        flags=("--format", "dec"))
    assert spoken(out, "regs t1") == "t1 | x6 | 4"
    assert spoken(out, "format") == "format | dec"


# -------------------------------------------------------------------- the flags


def test_the_flags_of_a_plain_run_and_those_of_a_session_do_not_mix(tmp_path):
    path = tmp_path / "p.s"
    path.write_text(SUM)
    out, errors = io.StringIO(), io.StringIO()
    code = main(["run", "--debug-mode", "-c", str(path)], out=out, errors=errors,
                reader=io.StringIO())
    assert code == 1
    assert "a session prints what its own commands ask for" in errors.getvalue()

    out, errors = io.StringIO(), io.StringIO()
    code = main(["run", "-e", "step", str(path)], out=out, errors=errors,
                reader=io.StringIO())
    assert code == 1
    assert "belong to a session: give --debug-mode as well" in errors.getvalue()


# ------------------------------------------------------------- the completions


def completing(tmp_path, line: str, word: str) -> list[str]:
    from pyrars.asm.assembler import Options, assemble

    path = tmp_path / "p.s"
    path.write_text(SUM)
    program = assemble([str(path)], Options())
    debugger = Debugger(Session(program), io.StringIO(), io.StringIO(),
                        io.StringIO())
    return debugger.completions(line, word)


def test_a_command_completes(tmp_path):
    assert completing(tmp_path, "", "") == sorted(BY_NAME)
    assert completing(tmp_path, "fr", "fr") == ["frames", "fregs"]


def test_the_verb_of_a_two_level_command_completes(tmp_path):
    assert completing(tmp_path, "break ", "") == ["add", "del", "list"]
    assert completing(tmp_path, "cache ", "") == ["info", "show"]


def test_a_name_of_the_program_completes_where_a_place_goes(tmp_path):
    assert completing(tmp_path, "until t", "t") == ["table", "total"]
    assert completing(tmp_path, "break add t", "t") == ["table", "total"]
    # but not in the place of the verb, where no name of a program belongs
    assert completing(tmp_path, "break t", "t") == []


def test_a_register_completes_where_a_register_goes(tmp_path):
    assert completing(tmp_path, "regs t", "t")[:3] == ["t0", "t1", "t2"]
    assert completing(tmp_path, "fregs ft1", "ft1") == ["ft1", "ft10", "ft11"]
    assert completing(tmp_path, "csr fc", "fc") == ["fcsr"]


def test_what_is_watched_for_completes(tmp_path):
    assert completing(tmp_path, "watch add total ", "") == [
        "both", "keep", "loop", "main", "msg", "read", "table", "total", "write"]


def test_nothing_completes_after_a_command_nobody_has(tmp_path):
    assert completing(tmp_path, "sideways ", "") == []


# ------------------------------------------------------- the shapes of a value


@pytest.mark.parametrize("value, bits, form, expected", [
    (0x1234, 32, "hex", "0x00001234"),
    (0xFFFFFFFF, 32, "dec", "-1"),
    (7, 32, "dec", "7"),
    (0x41424344, 32, "ascii", "  A  B  C  D"),
    (0x00010203, 32, "ascii", "  .  .  .  ."),
])
def test_how_a_value_is_written(value, bits, form, expected):
    assert value_text(value, bits, form) == expected
