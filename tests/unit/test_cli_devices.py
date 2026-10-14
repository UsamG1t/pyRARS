"""Devices from the command line: whole programs that talk to them.

This is what closes M5: the devices of `pyrars.devices` attached by `run --device`,
driven by programs of assembly, with what they show and what they keep compared
against what the programs did. Nothing of RARS can be compared here - its tools
live in its window and its command line cannot attach one.
"""

import io

import pytest

from pyrars.cli import main

KEYBOARD = """\
.text
# Take three keys and show each of them, then stop with the number taken.
main:   li t0, 0xffff0000
        li s1, 3
loop:   lw t1, 0(t0)            # the keyboard: is a key waiting?
        andi t1, t1, 1
        beqz t1, loop
        lw t2, 4(t0)            # take it
ready:  lw t3, 8(t0)            # the display: will it take a character?
        andi t3, t3, 1
        beqz t3, ready
        sw t2, 12(t0)           # show it
        addi s0, s0, 1
        blt s0, s1, loop
done:   lw t3, 8(t0)            # wait for the last character to appear
        andi t3, t3, 1
        beqz t3, done
        sw s0, 0x28(t0)         # the halt register: stop with what we took
"""

DISK = """\
.data
buf:    .space 16
.text
# Read block 1 of the disk into the buffer, print it, write it back to block 0.
main:   li t0, 0xffff0000
        li t1, 1
        sw t1, 0x40(t0)
        la t2, buf
        sw t2, 0x44(t0)
        li t3, 1
        sw t3, 0x48(t0)
        li t4, 1                # start, reading
        sw t4, 0x4c(t0)
wait:   lw t5, 0x4c(t0)
        andi t5, t5, 1
        bnez t5, wait
        la a0, buf
        li a7, 4
        ecall
        li t1, 0                # now the other way round, into block 0
        sw t1, 0x40(t0)
        li t4, 9                # start, writing
        sw t4, 0x4c(t0)
back:   lw t5, 0x4c(t0)
        andi t5, t5, 1
        bnez t5, back
        li a7, 93
        li a0, 0
        ecall
"""

DMA = """\
.data
from:   .word 1, 2, 3, 4
to:     .space 16
.text
# Have the controller copy four words, wait for it, then print the last of them.
main:   li t0, 0xffff0000
        la t1, from
        sw t1, 0x30(t0)
        la t2, to
        sw t2, 0x34(t0)
        li t3, 4
        sw t3, 0x38(t0)
        li t4, 1
        sw t4, 0x3c(t0)
wait:   lw t5, 0x3c(t0)
        andi t5, t5, 1
        bnez t5, wait
        la a0, to
        lw a0, 12(a0)
        li a7, 1
        ecall
        li a7, 93
        li a0, 0
        ecall
"""


# Every program here waits for a device, so every run is given a limit of steps: a
# device that answers nothing must end the run instead of spinning for ever. No test
# of this project may hang.
LIMIT = ("--steps", "2000")


def run(*arguments, given=""):
    out, errors = io.StringIO(), io.StringIO()
    code = main([*arguments, *LIMIT], out=out, errors=errors, reader=io.StringIO(given))
    return code, out.getvalue(), errors.getvalue()


def source(tmp_path, text, name="p.s"):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


# ---------------------------------------------------------------- the keyboard


def test_a_program_takes_keys_from_a_file_and_shows_them(tmp_path):
    keys = tmp_path / "keys.txt"
    keys.write_text("abc")
    code, out, errors = run("run", "--device", f"keyboard:keys={keys},delay=2",
                            "--device", "halt", source(tmp_path, KEYBOARD))
    assert (code, out) == (3, "abc")
    assert "Program terminated by calling exit" in errors


def test_the_keys_may_come_from_the_standard_input(tmp_path):
    code, out, _ = run("run", "--device", "keyboard:keys=-,delay=1",
                       "--device", "halt", source(tmp_path, KEYBOARD), given="xyz")
    assert (code, out) == (3, "xyz")


def test_a_program_that_waits_for_a_key_that_never_comes(tmp_path):
    code, out, errors = run("run", "--device", "keyboard", source(tmp_path, KEYBOARD))
    assert (code, out) == (0, "")
    assert "maximum step limit 2000 reached" in errors


# -------------------------------------------------------------------- the disk


def test_a_program_reads_and_writes_the_image_of_a_disk(tmp_path):
    image = tmp_path / "blocks.img"
    image.write_bytes(b"first block...!!" + b"second block..!!")
    code, out, _ = run("run", "--device", "disk:file=" + str(image)
                       + ",blocks=2,block_size=16,delay=2",
                       source(tmp_path, DISK))
    assert (code, out) == (0, "second block..!!")
    # and what was read went back to the first block, in the file itself
    assert image.read_bytes() == b"second block..!!" * 2


def test_a_disk_without_a_file_starts_empty(tmp_path):
    code, out, _ = run("run", "--device", "disk:blocks=2,block_size=16,delay=1",
                       source(tmp_path, DISK))
    assert (code, out) == (0, "")


def test_a_file_that_does_not_fit_the_disk(tmp_path):
    image = tmp_path / "blocks.img"
    image.write_bytes(b"too short")
    code, out, errors = run("run", "--device", "disk:file=" + str(image) + ",blocks=2",
                            source(tmp_path, DISK))
    assert (code, out) == (1, "")
    assert "an image of 9 bytes" in errors


# ------------------------------------------------------- the rest of the devices


def test_a_program_has_the_controller_copy_for_it(tmp_path):
    code, out, _ = run("run", "--device", "dma:speed=2", source(tmp_path, DMA))
    assert (code, out) == (0, "4")


def test_the_devices_of_a_window_can_be_attached_too(tmp_path):
    """The lab, the timer and the bitmap display answer a program here as well,
    though what they show belongs to a window."""
    text = """\
.text
main:   li t0, 0xffff0000
        li t1, 0x7f
        sb t1, 0x10(t0)         # the right display of the lab
        li t2, 1
        sb t2, 0x13(t0)         # and its counter
        lw t3, 0x18(t0)         # the time of the timer
        li a7, 93
        li a0, 0
        ecall
"""
    code, out, errors = run("run", "--device", "lab", "--device", "timer:mode=virtual",
                            "--device", "bitmap:width=8,height=8",
                            "-r", "t3", source(tmp_path, text))
    assert code == 0
    assert out == "t3\t0x00000006\n"  # six instructions had been carried out


# ------------------------------------------------------------------ what is said


def test_a_device_nobody_has(tmp_path):
    code, out, errors = run("run", "--device", "teapot", source(tmp_path, DMA))
    assert (code, out) == (1, "")
    assert '"teapot": no device of that name' in errors
    assert "keyboard" in errors  # and it says which there are


def test_an_option_a_device_has_not_got(tmp_path):
    code, _, errors = run("run", "--device", "keyboard:delya=2", source(tmp_path, DMA))
    assert code == 1
    assert "delya" in errors


def test_an_option_that_is_no_option(tmp_path):
    code, _, errors = run("run", "--device", "keyboard:delay", source(tmp_path, DMA))
    assert code == 1
    assert "an option is key=value" in errors


def test_an_option_that_makes_no_sense_to_the_device(tmp_path):
    code, _, errors = run("run", "--device", "keyboard:technique=sometimes",
                          source(tmp_path, DMA))
    assert code == 1
    assert "fixed or uniform or normal" in errors


def test_two_devices_cannot_answer_the_same_address(tmp_path):
    code, _, errors = run("run", "--device", "dma", "--device", "dma",
                          source(tmp_path, DMA))
    assert code == 1
    assert "answer the same addresses" in errors


def test_without_a_device_the_area_is_plain_memory(tmp_path):
    """A program that writes there and reads it back sees what it wrote."""
    text = """\
.text
main:   li t0, 0xffff0000
        li t1, 0x1234
        sw t1, 0x30(t0)
        lw t2, 0x30(t0)
        li a7, 93
        li a0, 0
        ecall
"""
    code, out, _ = run("run", "-r", "t2", source(tmp_path, text))
    assert (code, out) == (0, "t2\t0x00001234\n")
