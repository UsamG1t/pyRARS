"""Command line: subcommands, flags, output and exit codes."""

import io

import pytest

from pyrars.cli import main

PROGRAM = """\
.globl main
.data
msg: .asciz "hi"
n:   .word 42
.text
main: li t0, 5
      lw t1, n
      mv a0, t1
      ret
"""


def run(*arguments, given=""):
    """(exit code, standard output, error output) of a command; `given` is what the
    standard input holds for a program that reads."""
    out, errors = io.StringIO(), io.StringIO()
    code = main(list(arguments), out=out, errors=errors, reader=io.StringIO(given))
    return code, out.getvalue(), errors.getvalue()


def source(tmp_path, text=PROGRAM, name="p.s"):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


# ------------------------------------------------------------------------ asm


def test_assembling_says_nothing_when_all_is_well(tmp_path):
    assert run("asm", source(tmp_path)) == (0, "", "")


def test_the_listing_shows_address_word_instruction_and_source(tmp_path):
    code, out, errors = run("asm", "--listing", source(tmp_path))
    rows = out.splitlines()
    assert (code, errors) == (0, "")
    assert rows[0].startswith("00400000  00500293  addi x5,x0,5")
    assert rows[0].endswith("main: li t0, 5")
    assert rows[-1].startswith("00400010  00008067  jalr x0,x1,0")  # "lw t1, n" takes two words


def test_the_listing_can_use_the_names_of_the_calling_convention(tmp_path):
    _, out, _ = run("asm", "-l", "-a", source(tmp_path))
    assert "addi t0,zero,5" in out and "jalr zero,ra,0" in out


def test_the_symbols_are_printed_with_their_addresses(tmp_path):
    _, out, _ = run("asm", "-s", source(tmp_path))
    assert out.splitlines() == ["00400000  main (global)", "10010000  msg", "10010004  n"]


def test_a_dump_of_the_text_segment(tmp_path):
    path = str(tmp_path / "out.hex")
    assert run("asm", "-d", f".text:hex:{path}", source(tmp_path))[0] == 0
    words = open(path).read().split()
    assert len(words) == 5 and words[0] == "00500293" and words[-1] == "00008067"


def test_a_dump_of_the_data_segment_in_bytes(tmp_path):
    path = str(tmp_path / "out.bin")
    assert run("asm", "--dump", f".data:bin:{path}", source(tmp_path))[0] == 0
    assert open(path, "rb").read() == b"hi\0\0" + (42).to_bytes(4, "little")


def test_a_dump_to_the_standard_output(tmp_path):
    _, out, _ = run("asm", "-d", ".data:text:-", source(tmp_path))
    assert out.splitlines() == ["10010000  00006968", "10010004  0000002a"]


def test_a_dump_request_that_is_wrong(tmp_path):
    code, _, errors = run("asm", "-d", ".text:hex", source(tmp_path))
    assert code == 1 and errors.startswith('".text:hex": expected SEGMENT:FORMAT:FILE')


def test_the_binary_format_needs_a_file(tmp_path):
    code, _, errors = run("asm", "-d", ".text:bin:-", source(tmp_path))
    assert code == 1 and "the format bin needs a file" in errors


# --------------------------------------------------------------- diagnostics


def test_errors_go_to_the_error_stream_and_fail(tmp_path):
    code, out, errors = run("asm", source(tmp_path, ".text\nli t0\n", "e.s"))
    assert code == 1 and out == ""
    assert errors.splitlines() == [
        f"Error in {tmp_path / 'e.s'} line 2 column 1: "
        '"li": Too few or incorrectly formatted operands. Expected: li rd, imm']


def test_a_warning_does_not_fail_unless_asked(tmp_path):
    path = source(tmp_path, ".data\n.byte 300\n", "w.s")
    code, _, errors = run("asm", path)
    assert code == 0 and errors.startswith("Warning in ")
    assert run("asm", "-w", path)[0] == 1


def test_a_message_of_a_macro_shows_the_call(tmp_path):
    path = source(tmp_path, ".macro m\nli t0\n.end_macro\n.text\nm\n", "m.s")
    code, _, errors = run("asm", path)
    assert code == 1 and f"Error in {path} line 5->2 column 1:" in errors


def test_a_file_that_cannot_be_read(tmp_path):
    code, _, errors = run("asm", str(tmp_path / "missing.s"))
    assert code == 1 and "Error reading file" in errors


# --------------------------------------------------------------------- disasm


def test_disassembling_a_dump(tmp_path):
    words = tmp_path / "words.hex"
    words.write_text("00500293\n00008067\n")
    code, out, errors = run("disasm", str(words))
    assert (code, errors) == (0, "")
    assert out.splitlines() == ["00400000  00500293  addi x5,x0,5",
                                "00400004  00008067  jalr x0,x1,0"]


def test_disassembling_with_pseudo_instructions_and_names(tmp_path):
    words = tmp_path / "words.hex"
    words.write_text("00500293\n00008067\n")
    _, out, _ = run("disasm", "-p", "-a", str(words))
    assert out.splitlines() == ["00400000  00500293  li t0,5", "00400004  00008067  ret"]


def test_disassembling_bytes_from_a_chosen_address(tmp_path):
    words = tmp_path / "words.bin"
    words.write_bytes((0x00500293).to_bytes(4, "little"))
    _, out, _ = run("disasm", "-f", "bin", "-b", "0x1000", str(words))
    assert out.splitlines() == ["00001000  00500293  addi x5,x0,5"]


def test_a_word_that_is_no_instruction_keeps_its_column_empty(tmp_path):
    words = tmp_path / "words.hex"
    words.write_text("0000007f\n")
    _, out, _ = run("disasm", str(words))
    assert out.splitlines() == ["00400000  0000007f"]


def test_a_dump_that_cannot_be_read(tmp_path):
    code, _, errors = run("disasm", str(tmp_path / "none.hex"))
    assert code == 1 and "none.hex" in errors


# ------------------------------------------------------------------- options


def test_the_width_of_the_registers(tmp_path):
    path = source(tmp_path, ".text\naddiw t0, t0, 1\n", "w64.s")
    assert run("asm", path)[0] == 1  # addiw belongs to RV64
    assert run("asm", "-x", "64", path)[0] == 0


def test_another_memory_configuration(tmp_path):
    _, out, _ = run("asm", "-m", "CompactTextAtZero", "-s", source(tmp_path))
    assert out.splitlines()[0] == "00000000  main (global)"


def test_pseudo_instructions_can_be_forbidden(tmp_path):
    code, _, errors = run("asm", "--no-pseudo", source(tmp_path))
    assert code == 1 and "Extended (pseudo) instruction" in errors


def test_no_command_is_an_error():
    with pytest.raises(SystemExit):
        main([])


# ------------------------------------------------------------------------ run

EXIT = """\
.text
main:   li t0, -5
        li t1, 0x41424344
        la t2, n
        sw t1, 0(t2)
        li a7, 93
        li a0, 7
        ecall
"""
DATA_PART = ".data\nn:    .word 0\n"
HELLO = """\
.data
msg:    .asciz "hi there\\n"
.text
main:   la a0, msg
        li a7, 4
        ecall
        li a7, 10
        ecall
"""


def test_a_program_that_exits_gives_its_own_code(tmp_path):
    code, out, errors = run("run", source(tmp_path, DATA_PART + EXIT))
    assert code == 7
    assert errors == "\nProgram terminated by calling exit\n"
    assert out == ""


def test_what_a_program_writes_goes_to_the_standard_output(tmp_path):
    code, out, errors = run("run", source(tmp_path, HELLO))
    assert (code, out) == (0, "hi there\n")
    assert "Program terminated by calling exit" in errors


def test_a_program_reads_the_standard_input(tmp_path):
    source_text = """\
.text
main:   li a7, 5
        ecall
        add a1, a0, a0
        li a7, 1
        mv a0, a1
        ecall
        li a7, 10
        ecall
"""
    assert run("run", source(tmp_path, source_text), given="21\n")[1] == "42"


def test_the_registers_and_memory_a_run_was_asked_for(tmp_path):
    code, out, _ = run("run", "-r", "t0,t1", "--memory", "0x10010000-0x10010000",
                       "-c", source(tmp_path, DATA_PART + EXIT))
    assert code == 7
    assert out == ("instructions\t8\n"
                   "t0\t0xfffffffb\n"
                   "t1\t0x41424344\n"
                   "Mem[0x10010000]\t0x41424344\n")


def test_a_range_of_memory_starts_at_the_word_it_lies_in(tmp_path):
    code, out, _ = run("run", "--memory", "0x10010002-0x10010005",
                       source(tmp_path, DATA_PART + EXIT))
    assert out == "Mem[0x10010000]\t0x41424344\t0x00000000\n"


def test_the_formats_of_a_printed_value(tmp_path):
    path = source(tmp_path, DATA_PART + EXIT)
    assert run("run", "-r", "t0", "-f", "dec", path)[1] == "t0\t-5\n"
    assert run("run", "-r", "t1", "-f", "ascii", path)[1] == "t1\t  A  B  C  D\n"
    assert run("run", "-r", "t0", "-f", "ascii", path)[1] == "t0\t  .  .  .  .\n"


def test_a_register_of_a_64_bit_machine_shows_every_digit(tmp_path):
    """RARS prints the low eight digits of any register; ours prints the register
    (DEV-47)."""
    text = ".text\nmain:   li t0, 1\n        slli t0, t0, 40\n        li a7, 10\n        ecall\n"
    assert run("run", "-x", "64", "-r", "t0", source(tmp_path, text))[1] == \
        "t0\t0x0000010000000000\n"


def test_the_float_and_control_registers_can_be_printed(tmp_path):
    text = """\
.text
main:   li t0, 0x3f800000
        fmv.w.x f1, t0
        fmv.w.x f3, x0
        fdiv.s f2, f1, f3
        li a7, 10
        ecall
"""
    code, out, _ = run("run", "-r", "f1,fa0,fflags", source(tmp_path, text))
    assert out == ("f1\t0xffffffff3f800000\n"
                   "fa0\t0x0000000000000000\n"  # an ABI name does as well
                   "fflags\t0x00000008\n")


def test_a_program_that_runs_off_its_text(tmp_path):
    code, _, errors = run("run", source(tmp_path, ".text\nmain:   li t0, 1\n"))
    assert (code, errors) == (0, "\nProgram terminated by dropping off the bottom.\n")


def test_a_program_that_is_stopped_by_a_trap(tmp_path):
    path = source(tmp_path, ".text\nmain:   li t0, 1\n        lw t1, 1(x0)\n")
    code, out, errors = run("run", "-r", "t0", path)
    assert code == 1
    assert errors == (f"\nError in {path} line 3: Runtime exception at 0x00400004: "
                      "Load address not aligned to word boundary 0x00000001\n"
                      "\nSimulation terminated due to errors.\n")
    assert out == "t0\t0x00000001\n"  # what it was asked for is still printed


def test_the_step_limit(tmp_path):
    code, out, errors = run("run", "--steps", "2", "-r", "t0", "-c",
                            source(tmp_path, DATA_PART + EXIT))
    assert (code, errors) == (0, "\nProgram terminated when maximum step limit 2 reached.\n")
    assert out == "instructions\t2\nt0\t0xfffffffb\n"


def test_a_breakpoint_of_the_command_line(tmp_path):
    code, out, errors = run("run", "--break", "0x00400008", "-c",
                            source(tmp_path, DATA_PART + EXIT))
    assert (code, errors) == (0, "\nProgram stopped at a breakpoint 0x00400008\n")
    assert out == "instructions\t2\n"


def test_a_program_reads_its_own_arguments(tmp_path):
    text = """\
.text
main:   li a7, 1
        ecall
        li a7, 10
        ecall
"""
    assert run("run", source(tmp_path, text), "--args", "one", "two")[1] == "2"


def test_a_name_nobody_has_is_refused_before_the_run(tmp_path):
    code, out, errors = run("run", "-r", "t0,x99", source(tmp_path, HELLO))
    assert (code, out) == (1, "")  # the program did not run at all
    assert errors == '"x99": no register of that name\n'


def test_a_range_of_memory_that_makes_no_sense(tmp_path):
    path = source(tmp_path, HELLO)
    assert run("run", "--memory", "0x10010000", path)[0] == 1
    assert run("run", "--memory", "0x10010010-0x10010000", path)[2] == \
        '"0x10010010-0x10010000": the first address must be the lower one\n'


def test_a_program_that_does_not_assemble_is_not_run(tmp_path):
    code, out, errors = run("run", source(tmp_path, ".text\nmain:   nonsense t0\n"))
    assert (code, out) == (1, "")
    assert "is not a recognized operator" in errors


def test_the_self_modifying_option_reaches_the_machine(tmp_path):
    text = """\
.text
main:   la t0, main
        lw t1, 0(t0)
        li a7, 10
        ecall
"""
    path = source(tmp_path, text)
    assert run("run", path)[0] == 1  # the text segment is closed
    assert run("run", "--self-modifying", path)[0] == 0
