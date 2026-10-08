# pyRARS devices

A device is something a program talks to by reading and writing addresses of its own: a keyboard, a
display, a timer, a disk. pyRARS has seven of them, and each is a model — state and events, with no
window of its own — so the same device serves a program run from the command line, a test and the
graphical interface.

The devices live in the area of the devices of the memory configuration (`0xffff0000` and up in
`Default`). Their registers are ordinary memory cells, so a dump or a memory view shows what they
hold; the device adds the behaviour: a read that takes a key, a write that starts a transfer. An
address of that area nobody answers for is plain memory.

Four of the devices follow [RARS](https://github.com/TheThirdOne/rars), whose dialect this project
follows; three are of pyRARS.

## Attaching a device

```
python -m pyrars run --device NAME[:OPTION=VALUE,...] file...
```

The flag may be repeated. Without it the whole area of the devices is plain memory.

| Name | What it is | Options |
|---|---|---|
| `keyboard` | a keyboard and a text display | `delay`, `technique`, `rows`, `columns`, `show_after_delay`, `queue`, `keys` |
| `lab` | two seven-segment displays, sixteen keys, a counter | — |
| `timer` | a clock and a time to be told of | `mode`, `step` |
| `bitmap` | a piece of memory seen as a picture | `place`, `width`, `height`, `unit_width`, `unit_height` |
| `dma` | copying while the program runs on | `speed` |
| `disk` | storage, a block at a time | `blocks`, `block_size`, `delay`, `file` |
| `halt` | one register that ends the run | — |

A value is written as a number (`10`, `0x20`), a yes or no (`yes`, `no`) or a text (`uniform`).
Two options belong to the command line rather than to the device, because a device never touches a
file: `keyboard:keys=FILE` is the text to type (`-` is the standard input), and `disk:file=FILE` is
the image the disk holds, read before the run and written back after it.

```
python -m pyrars run --device keyboard:keys=input.txt,delay=2 --device halt game.s
python -m pyrars run --device disk:file=blocks.img,blocks=64 --device dma:speed=4 copy.s
```

## Where they live

| Addresses (from the base of the area) | Device |
|---|---|
| `+0x00` … `+0x0f` | the keyboard and the display |
| `+0x10` … `+0x14` | the digital lab |
| `+0x18` … `+0x27` | the timer |
| `+0x28` | the halt register |
| `+0x30` … `+0x3f` | the controller of direct access |
| `+0x40` … `+0x57` | the disk |

The bitmap display has no registers: it watches a range of memory.

The area is 64 KiB in `Default` but only 256 bytes in the two compact configurations, so every
device of pyRARS fits in the first 256 bytes and works in all three.

## Asking to be told

A device can ask for attention instead of being polled. The machine has three slots — one for an
external event, one for a timer event, one for the trap of an instruction — and an event that
arrives while its slot is full is dropped. A handler reads which device it was in `utval`:

| Device | Slot | `utval` |
|---|---|---|
| a key of the keyboard | external | `0x40` |
| the display is ready | external | `0x80` |
| a key of the lab | external | `0x200` |
| the counter of the lab | timer | `0x100` |
| the timer | timer | `0x10` |
| the controller of direct access | external | `0x400` |
| the disk | external | `0x800` |

A handler is entered only while `ustatus` has its bit `0x1` and `uie` the bit of that kind of event;
see [the machine](core.md) for how a handler is entered and left.

## The keyboard and the display

| Address | Register | |
|---|---|---|
| `+0x00` | `RcvCtrl` | bit 0: a key is waiting. bit 1: ask to be told of a key |
| `+0x04` | `RcvData` | the key, in the low eight bits; reading it frees the keyboard |
| `+0x08` | `TxCtrl` | bit 0: the display will take a character. bit 1: ask to be told |
| `+0x0c` | `TxData` | the character to show, in the low eight bits |

```asm
        li t0, 0xffff0000
wait:   lw t1, 0(t0)            # has a key arrived?
        andi t1, t1, 1
        beqz t1, wait
        lw a0, 4(t0)            # take it — and free the keyboard for the next one
ready:  lw t2, 8(t0)            # will the display take a character?
        andi t2, t2, 1
        beqz t2, ready
        sw a0, 12(t0)           # show it
```

The display takes a few instructions over every character (`delay`, five by default), as a serial
line would: `technique` makes that length `fixed`, drawn evenly (`uniform`) or drawn from a normal
distribution (`normal`), and `show_after_delay=no` shows the character at once and still takes the
time. A character written while the display is busy is lost.

The keyboard holds `queue` keys at once (one by default); with a longer one the rest wait their turn
and each asks to be told as it comes up.

Two characters mean something of their own: **12** clears the display, and **7** switches it to the
mode where a character goes where it is told — the column in the bits 20…31 of the word written, the
row in the bits 8…19, both cut to the size of the display (`rows` by `columns`, 25 by 80 by default).

## The digital lab

| Address | Register | |
|---|---|---|
| `+0x10` | the right display | bit 0 the segment a … bit 6 g, bit 7 the dot |
| `+0x11` | the left display | the same bits |
| `+0x12` | the keyboard | bits 0…3: which row to look at. bits 4…7: ask to be told of a key |
| `+0x13` | the counter | anything but zero starts it, zero stops it |
| `+0x14` | the key | the device writes it: the bit of the row and the bit of the column |

The registers are bytes. A key is told of only when the program asks for **exactly** the row it is
in, so a program walks the rows:

```asm
        li t0, 0xffff0000
        li t1, 1                # the first row
scan:   sb t1, 0x12(t0)
        lb t2, 0x14(t0)
        bnez t2, found
        slli t1, t1, 1          # the next row
        andi t1, t1, 0xf
        bnez t1, scan
```

The counter asks for a timer event every thirty-first notice, a notice being every instruction
carried out and every access of the four registers `+0x10`…`+0x13`.

## The timer

| Address | Register | |
|---|---|---|
| `+0x18` | `time` | milliseconds since the run began, 64 bits: the low word, then the high |
| `+0x20` | `timecmp` | the time to be told of, 64 bits |

Writing `timecmp` arms the timer; when the time reaches it, the timer asks for a timer event once.
Each half of `timecmp` replaces its own half, and a 64-bit machine may write the whole of it with
one `sd`.

`mode=virtual` counts the time in instructions instead of asking the clock — `step` milliseconds for
every instruction carried out — so a run with a timer in it gives the same thing every time, which is
what a test wants.

## The bitmap display

One word of memory is one unit of the picture, row by row, and the colour of a unit is the low 24
bits of the word: red, green, blue.

| Option | |
|---|---|
| `place` | `data`, `global`, `static` (the default), `heap`, `devices`, or an address of a word |
| `width`, `height` | the size of the picture in pixels (512 by 256 by default) |
| `unit_width`, `unit_height` | how many pixels a unit is (one by one by default) |

```asm
.data
screen: .space 256              # 8 by 8 units
.text
        la t0, screen
        li t1, 0x00ff8000       # orange
        sw t1, 0(t0)            # the unit at the top left
        sw t1, 36(t0)           # and the tenth one
```

The picture is read from memory when the device is attached, so data a program starts with is part
of it.

## The controller of direct access to memory

| Address | Register | |
|---|---|---|
| `+0x30` | from | the address the words are read from |
| `+0x34` | to | the address they are written to |
| `+0x38` | words | how many words to copy |
| `+0x3c` | control | bit 0 start, and 1 while it is copying. bit 1 ask to be told. bit 2 refused |

```asm
        li t0, 0xffff0000
        la t1, source
        sw t1, 0x30(t0)
        la t2, target
        sw t2, 0x34(t0)
        li t3, 64
        sw t3, 0x38(t0)
        li t4, 1                # start
        sw t4, 0x3c(t0)
busy:   lw t5, 0x3c(t0)         # ... or do something else and wait for the interrupt
        andi t5, t5, 1
        bnez t5, busy
```

It copies `speed` words for every instruction carried out, one word at a time from the lower address
up. An address the program may not touch, or one that is not a word, sets the bit of the refusal and
stops the copying; the interrupt, if it was asked for, comes anyway, because the program has to hear
that the copying ended.

## The disk

| Address | Register | |
|---|---|---|
| `+0x40` | block | which block to work on |
| `+0x44` | buffer | where in memory the bytes come from or go to |
| `+0x48` | count | how many blocks |
| `+0x4c` | control | bit 0 start/working. bit 1 ask to be told. bit 2 refused. bit 3 the way: 1 writes to the disk |
| `+0x50` | blocks | how many blocks the disk holds (it only answers) |
| `+0x54` | size | how many bytes a block holds (it only answers) |

```asm
        li t0, 0xffff0000
        lw s0, 0x50(t0)         # how large is this disk?
        lw s1, 0x54(t0)
        li t1, 3
        sw t1, 0x40(t0)         # block 3
        la t2, buffer
        sw t2, 0x44(t0)
        li t3, 1
        sw t3, 0x48(t0)
        li t4, 1                # start, reading
        sw t4, 0x4c(t0)
```

A block is carried over whole every `delay` instructions (ten by default), so reading two blocks
takes twice as long. A block past the end of the disk, a run of blocks that would go past it, or a
buffer the program may not touch sets the bit of the refusal.

With `file=` the image is read from that file before the run and written back after it, so what a
program stores outlives it.

## The halt register

Writing a word to `+0x28` ends the run with that word as the exit code — the same as calling the
service 93, for a program that has no services to call.

```asm
        li t0, 0xffff0000
        li t1, 0
        sw t1, 0x28(t0)         # done, and all was well
```

## Stepping back

A step back of the debugger restores the machine, not the devices: what a device put in memory goes
back with everything else, but the device itself remembers what it did. A program being stepped
backwards over a transfer therefore sees its memory as it was, while the disk or the controller
stands where it stood.

## See also

- [the machine](core.md) — how a program is run, how a handler is entered, and what the command line
  can print
- [the assembler](asm.md) — the language the programs above are written in
