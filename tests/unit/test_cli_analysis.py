"""The models that watch, asked for from the command line.

This is what closes M6: whole programs run through `pyrars.cli` with `--stats`,
`--cache`, `--pipeline` and `--callstack`, and every number of the output worked
out by hand from the program. Nothing of it can be compared with RARS - its tools
of statistics, of the cache and of the branch table all live in its window.
"""

import io

import pytest

from pyrars.cli import main

# Eight words summed in a loop, then a call that prints the sum.
SUM = """\
.globl main
.data
table:  .word 1, 2, 3, 4, 5, 6, 7, 8
.text
main:   la t0, table
        li t1, 8
        li t2, 0
loop:   lw t3, 0(t0)
        add t2, t2, t3
        addi t0, t0, 4
        addi t1, t1, -1
        bne t1, x0, loop
        jal ra, show
        li a7, 93
        li a0, 0
        ecall
show:   mv a0, t2
        li a7, 1
        ecall
        ret
"""


def run(*arguments, given=""):
    out, errors = io.StringIO(), io.StringIO()
    code = main([*arguments, "--steps", "2000"], out=out, errors=errors,
                reader=io.StringIO(given))
    return code, out.getvalue(), errors.getvalue()


def source(tmp_path, text=SUM, name="p.s"):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def said(out: str) -> dict[str, str]:
    """The lines of `name<tab>value` as what they say."""
    found = {}
    for line in out.splitlines():
        if "\t" in line:
            name, _, value = line.partition("\t")
            found.setdefault(name, value)
    return found


# ------------------------------------------------------------------ the counters


def test_what_a_program_was_made_of(tmp_path):
    code, out, _ = run("run", "--stats", source(tmp_path))
    told = said(out)
    # three to set up (la is two instructions), five to a turn of the loop times
    # eight, the call, two for the exit, and three in the subroutine
    assert told["instructions"] == "51"
    assert told["kind.load"] == "8"  # one load a turn
    assert told["kind.branch"] == "8"
    assert told["kind.jump"] == "2"  # the call and its return
    assert told["branches.taken"] == "7"  # the eighth turn falls out of the loop
    assert told["branches.not-taken"] == "1"
    assert told["category.memory"] == "8"
    assert out.startswith("36")  # and the program itself printed the sum


def test_nothing_is_counted_unless_it_is_asked_for(tmp_path):
    code, out, _ = run("run", source(tmp_path))
    assert out == "36"
    assert said(out) == {}


# -------------------------------------------------------------------- the cache


def test_a_cache_sees_the_accesses_of_the_data(tmp_path):
    """Two words to a block: the first word of a block misses and the next hits, so
    eight words are four misses and four hits."""
    code, out, _ = run("run", "--cache", "block_bytes=8,sets=4", source(tmp_path))
    told = said(out)
    assert (told["cache.accesses"], told["cache.hits"]) == ("8", "4")
    assert told["cache.rate"] == "0.5"


def test_a_larger_block_catches_more(tmp_path):
    code, out, _ = run("run", "--cache", "block_bytes=32,sets=4", source(tmp_path))
    told = said(out)
    assert (told["cache.misses"], told["cache.hits"]) == ("1", "7")


def test_a_cache_of_its_own_for_the_instructions(tmp_path):
    code, out, _ = run("run", "--cache", "instructions:sets=16",
                       "--cache", "data:sets=4", source(tmp_path))
    told = said(out)
    assert told["instructions.accesses"] == "51"  # every instruction was fetched
    assert told["data.accesses"] == "8"
    assert int(told["instructions.hits"]) > 40  # the loop fits in the cache


def test_one_cache_can_see_both(tmp_path):
    code, out, _ = run("run", "--cache", "unified:sets=16", source(tmp_path))
    told = said(out)
    assert told["cache.accesses"] == "59"  # 51 fetches and 8 loads
    assert "data.accesses" not in told


STORES = """\
.globl main
.data
room:   .space 64
.text
main:   la t0, room
        li t1, 4
fill:   sw t1, 0(t0)
        lw t2, 0(t0)
        addi t0, t0, 4
        addi t1, t1, -1
        bne t1, x0, fill
        li a7, 93
        li a0, 0
        ecall
"""


def test_a_cache_sees_what_a_program_writes(tmp_path):
    """Four turns, each a store and a load of the same word: eight accesses, of
    which the four stores miss the first time and the loads hit."""
    code, out, _ = run("run", "--cache", "block_bytes=4,sets=8", source(tmp_path, STORES))
    told = said(out)
    assert told["cache.accesses"] == "8"
    assert told["cache.hits"] == "4"
    assert told["cache.writebacks"] == "0"  # nothing was thrown out


def test_a_cache_does_not_watch_the_devices(tmp_path):
    """The registers of a device are not the kind of thing a cache may keep, so a
    program talking to one adds nothing to its accesses."""
    text = """\
.globl main
.data
room:   .space 8
.text
main:   la t0, room
        sw t0, 0(t0)            # one access of the data
        li t1, 0xffff0000
        lw t2, 8(t1)            # a read of a device, which is no access of it
        li t3, 65
        sw t3, 12(t1)           # and a write of one, which is none either
        sb t2, 0x28(t1)         # the halt register: stop
"""
    code, out, _ = run("run", "--device", "keyboard", "--device", "halt",
                       "--cache", "sets=8", source(tmp_path, text))
    told = said(out)
    assert told["cache.accesses"] == "1"


def test_a_cache_asked_for_twice(tmp_path):
    code, _, errors = run("run", "--cache", "sets=4", "--cache", "sets=8",
                          source(tmp_path))
    assert code == 1 and "asked for twice" in errors


def test_a_cache_for_everything_and_one_side_at_once(tmp_path):
    code, _, errors = run("run", "--cache", "unified:sets=4",
                          "--cache", "data:sets=8", source(tmp_path))
    assert code == 1 and "cannot be asked for together" in errors


def test_a_cache_that_is_no_cache(tmp_path):
    code, _, errors = run("run", "--cache", "sets=6", source(tmp_path))
    assert code == 1 and "power of two" in errors


def test_an_option_a_cache_has_not_got(tmp_path):
    code, _, errors = run("run", "--cache", "blocks=6", source(tmp_path))
    assert code == 1 and "blocks" in errors


# ----------------------------------------------------------------- the pipeline


def test_the_time_a_pipeline_would_have_taken(tmp_path):
    code, out, _ = run("run", "--pipeline", source(tmp_path))
    told = said(out)
    assert told["pipeline.instructions"] == "51"
    assert int(told["pipeline.cycles"]) == 84
    assert told["pipeline.lost.load"] == "8"  # the sum uses what the load just read
    assert told["pipeline.lost.branch"] == "14"  # seven wrong guesses of two cycles
    assert told["pipeline.guesser"] == "never taken"


def test_a_table_of_history_guesses_a_loop_better(tmp_path):
    code, out, _ = run("run", "--pipeline", "predictor=table", source(tmp_path))
    told = said(out)
    assert told["pipeline.wrong"] == "2"  # the first turn and the last
    assert int(told["pipeline.cycles"]) < 84


def test_the_machine_of_the_model_can_be_described(tmp_path):
    code, out, _ = run("run", "--pipeline", "forwarding=no,one_port=yes,penalty=4",
                       source(tmp_path))
    told = said(out)
    assert told["pipeline.lost.branch"] == "28"  # four cycles a wrong guess
    assert int(told["pipeline.lost.data"]) > 0  # nothing is forwarded
    assert int(told["pipeline.cycles"]) > 84  # all of it costs more than the default
    # This loop never loses a fetch to the one port: its branches hold the fetches
    # up anyway, so no fetch ever falls in the cycle a load reaches memory.
    assert "pipeline.lost.port" not in told


def test_a_kind_of_instruction_can_be_given_its_own_length(tmp_path):
    """A division of ten cycles holds the stage behind it, and the instructions
    that follow wait on the STAGE where they want nothing of its result."""
    text = """\
.text
main:   li t0, 100
        li t1, 7
        div t2, t0, t1
        addi t4, x0, 1
        addi t5, x0, 2
        li a7, 93
        li a0, 0
        ecall
"""
    code, out, _ = run("run", "--pipeline", "divide=10", source(tmp_path, text))
    told = said(out)
    assert told["pipeline.lost.busy"] == "9"  # nine cycles more than a short EX
    assert "pipeline.lost.data" not in told


def test_what_waits_for_a_long_result_waits_for_the_value(tmp_path):
    """Where a long instruction both holds the stage and withholds its value, the
    wait is blamed on the value: the two causes are one event."""
    text = """\
.text
main:   li t0, 100
        li t1, 7
        div t2, t0, t1
        add t3, t2, t2
        li a7, 93
        li a0, 0
        ecall
"""
    code, out, _ = run("run", "--pipeline", "divide=10", source(tmp_path, text))
    told = said(out)
    assert told["pipeline.lost.data"] == "9"
    assert "pipeline.lost.busy" not in told


def test_the_diagram_is_drawn_only_where_it_was_asked_for(tmp_path):
    code, out, _ = run("run", "--pipeline", source(tmp_path))
    assert "pipeline.row" not in out

    code, out, _ = run("run", "--pipeline", "diagram=3", source(tmp_path))
    rows = [line for line in out.splitlines() if line.startswith("pipeline.row")]
    assert len(rows) == 3
    assert rows[0].split("\t")[1:] == ["0x00400000", "auipc", "0 1 2 3 4"]


def test_the_table_of_a_guesser_is_built_as_it_was_asked(tmp_path):
    code, out, _ = run("run", "--pipeline", "predictor=table,entries=4,bits=2",
                       source(tmp_path))
    told = said(out)
    assert told["pipeline.guesser"] == "a table of 4 entries of 2 bits"
    assert told["pipeline.wrong"] == "3"  # two bits learn more slowly than one


def test_a_guesser_nobody_knows(tmp_path):
    code, _, errors = run("run", "--pipeline", "predictor=hunch", source(tmp_path))
    assert code == 1 and "never, always or table" in errors


def test_an_option_a_pipeline_has_not_got(tmp_path):
    code, _, errors = run("run", "--pipeline", "forwardng=no", source(tmp_path))
    assert code == 1 and "forwardng" in errors


# -------------------------------------------------------------------- the calls


def test_which_calls_a_run_made(tmp_path):
    code, out, _ = run("run", "--callstack", source(tmp_path))
    told = said(out)
    assert (told["callstack.calls"], told["callstack.returns"]) == ("1", "1")
    assert (told["callstack.deepest"], told["callstack.depth"]) == ("1", "0")
    assert (told["callstack.confused"], told["callstack.unmatched"]) == ("0", "0")


def test_the_frames_of_a_run_that_stopped_inside_a_call(tmp_path):
    """Where a run is cut short inside a call, the frame says what was called - by
    name, where the program gave it one."""
    code, out, _ = run("run", "--callstack", "--break", "0x00400034",
                       source(tmp_path))
    frames = [line for line in out.splitlines() if line.startswith("callstack.frame")]
    assert len(frames) == 1
    name, called_from, sp = frames[0].split("\t")[1:]
    assert name == "show"
    assert called_from == "0x00400024"  # the `jal` of the call
    assert sp == "0x7fffeffc"  # where the stack stood when it was made


def test_a_program_that_does_not_keep_the_convention_is_read_wrongly(tmp_path):
    """And the model says so: two calls, and the outer return lands where the inner
    call left `ra`."""
    text = """\
.globl main
.text
main:   jal ra, outer
        li a7, 93
        li a0, 0
        ecall
outer:  jal ra, inner
        ret
inner:  ret
"""
    code, out, _ = run("run", "--callstack", source(tmp_path, text))
    told = said(out)
    assert told["callstack.calls"] == "2"
    assert told["callstack.confused"] == "1"


# ----------------------------------------------------------- all of them at once


def test_every_model_at_once(tmp_path):
    code, out, errors = run("run", "--stats", "--cache", "sets=4", "--pipeline",
                            "--callstack", "-c", source(tmp_path))
    told = said(out)
    assert code == 0
    assert told["instructions"] == "51"  # the count of the command line itself
    assert told["kind.load"] == "8"
    assert told["cache.accesses"] == "8"
    assert told["pipeline.cpi"].startswith("1.6")
    assert told["callstack.calls"] == "1"
    assert "Program terminated by calling exit" in errors


def test_watching_changes_nothing_of_the_run(tmp_path):
    """INV-P, through the whole command line: the program prints the same thing and
    ends the same way, watched or not."""
    plain = run("run", "-r", "t2", source(tmp_path))
    watched = run("run", "--stats", "--cache", "sets=4", "--pipeline", "--callstack",
                  "-r", "t2", source(tmp_path))
    assert plain[0] == watched[0]
    assert plain[1].startswith("36") and watched[1].startswith("36")
    assert "t2\t0x00000024" in plain[1] and "t2\t0x00000024" in watched[1]
    assert plain[2] == watched[2]
