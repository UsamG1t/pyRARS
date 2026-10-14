"""A project from the command line: `run --project`.

What a project settles - the files, the main file, the width of the machine, the
memory configuration, the pseudo-instructions - cannot be settled again on the
line, and the refusal is the test: a flag that quietly loses to a file, or wins
over it, would be worse. Everything else about a run is given on the line as ever,
and a session opens on a project just the same (stage 37).
"""

import io
import json

import pytest

from pyrars.cli import main

LIB = """\
.globl double
.text
double: add a0, a0, a0
        ret
"""
MAIN = """\
.globl main
.text
main:   li a0, 21
        jal ra, double
        li a7, 93
        ecall
"""


def project(tmp_path, held: dict, name: str = "thing.pyrars.json") -> str:
    (tmp_path / "main.s").write_text(MAIN)
    (tmp_path / "lib.s").write_text(LIB)
    path = tmp_path / name
    path.write_text(json.dumps(held))
    return str(path)


def run(*arguments, given=""):
    out, errors = io.StringIO(), io.StringIO()
    code = main([*arguments, "--steps", "2000"], out=out, errors=errors,
                reader=io.StringIO(given))
    return code, out.getvalue(), errors.getvalue()


def test_a_run_of_a_project(tmp_path):
    path = project(tmp_path, {"files": ["lib.s", "main.s"], "main": "main.s"})
    code, out, errors = run("run", "--project", path, "-c")
    # the report of a run keeps the blank line RARS puts before it
    assert errors == "\nProgram terminated by calling exit\n"
    assert code == 42  # the program doubles 21 and exits with it
    assert "instructions\t5" in out


def test_the_main_file_of_a_project_goes_first(tmp_path):
    """The main file is assembled first, so the program begins at the text base
    whatever order the project holds its files in."""
    path = project(tmp_path, {"files": ["lib.s", "main.s"], "main": "main.s"})
    code, out, _ = run("run", "--project", path, "-r", "a0")
    assert code == 42
    _, told, _ = run("run", "--project",
                     project(tmp_path, {"files": ["lib.s", "main.s"]},
                             name="other.pyrars.json"), "-c")
    # without a main file the order is the order, so `double` lies at the base and
    # the run begins there: it doubles nothing and comes back to a cliff
    assert "instructions\t2" in told


def test_a_session_opens_on_a_project(tmp_path):
    path = project(tmp_path, {"files": ["lib.s", "main.s"], "main": "main.s"})
    code, out, _ = run("run", "--project", path, "--debug-mode",
                       "-e", "until double", "-e", "regs a0", "-e", "quit")
    assert "0x00400010 <double> | add x10,x10,x10 | double: add a0, a0, a0 | lib.s:3" in out
    assert "a0 | x10 | 0x00000015" in out  # twenty-one, not yet doubled


def test_what_a_project_settles_cannot_be_given_again(tmp_path):
    path = project(tmp_path, {"files": ["main.s"]})
    for flags, said in (
        ((str(tmp_path / "main.s"),), "the files"),
        (("-x", "64"), "-x"),
        (("-m", "CompactDataAtZero"), "-m"),
        (("--no-pseudo",), "--no-pseudo"),
    ):
        code, _, errors = run("run", "--project", path, *flags)
        assert code == 1
        assert errors == ("--project settles what the program is, so "
                          f"{said} cannot be given as well\n")


def test_everything_that_is_refused_is_named_at_once(tmp_path):
    path = project(tmp_path, {"files": ["main.s"]})
    code, _, errors = run("run", "--project", path, "-x", "64", "--no-pseudo",
                          str(tmp_path / "main.s"))
    assert code == 1
    assert "the files, -x and --no-pseudo cannot be given as well" in errors


def test_what_a_project_does_not_settle_is_given_as_ever(tmp_path):
    path = project(tmp_path, {"files": ["lib.s", "main.s"], "main": "main.s"})
    code, out, errors = run("run", "--project", path, "--stats",
                            "--break", "0x00400010")
    assert "Program stopped at a breakpoint 0x00400010" in errors
    assert "instructions\t2" in out  # `li a0, 21` and the call, then it stopped


def test_a_run_of_nothing_at_all(tmp_path):
    code, _, errors = run("run")
    assert code == 1
    assert errors == "name the files of the program, or --project FILE\n"


def test_a_project_that_names_no_files(tmp_path):
    path = project(tmp_path, {"files": []})
    code, _, errors = run("run", "--project", path)
    assert code == 1
    assert errors.endswith("the project names no files\n")


def test_what_a_project_says_wrongly_is_said_by_the_tool_itself(tmp_path):
    """A project that cannot be read is a failure of the tool, not an answer to a
    command, so it goes to the error stream and the run does not begin."""
    path = project(tmp_path, {"files": ["main.s"], "xlen": 16})
    code, out, errors = run("run", "--project", path)
    assert code == 1
    assert out == ""
    assert errors.endswith("16: a machine is 32 or 64 bits wide\n")


def test_a_project_that_forbids_the_pseudo_instructions(tmp_path):
    path = project(tmp_path, {"files": ["lib.s", "main.s"], "main": "main.s",
                              "pseudo": False})
    code, out, errors = run("run", "--project", path)
    assert code == 1
    assert "Extended (pseudo) instruction or format not permitted" in errors
    assert out == ""  # nothing ran at all


def test_a_project_of_a_wider_machine(tmp_path):
    path = project(tmp_path, {"files": ["lib.s", "main.s"], "main": "main.s",
                              "xlen": 64})
    code, out, _ = run("run", "--project", path, "-r", "a0")
    assert code == 42
    assert "a0\t0x000000000000002a" in out  # sixteen digits: the machine is 64 bits
