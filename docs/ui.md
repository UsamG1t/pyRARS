# pyRARS window

A window is one of the two faces of a session. It puts the program and the machine running it side
by side: the files on the left, where the run stands and the three files of registers on the right,
and the views of everything else below them. Nothing of the machine lives here — every number on
the screen comes from `pyrars.session` and the console debugger of [session.md](session.md) is told
the same things in the same words.

It is GTK 4 with libadwaita and GtkSourceView 5, through PyGObject, and it is the only part of
pyRARS that imports `gi`: everything underneath it runs on a machine with no window system at all.

## Opening it

```
python -m pyrars.ui [FILE...]
python -m pyrars.ui --project FILE
```

The window has its own way in and is not a subcommand of `pyrars`, because the command line must
run where there is no display and so may not import the window at all.

Files named on the line are files to work on, not a program in several pieces: a program made of
several files is a **project**, and saying so is what `--project` and the program window are for.

## The shape of it

```
┌────────────────────────────────────────────────────────────────────┐
│ open save │ Assemble Run To here Step Over Finish Back Cycle …     │  the actions
├───────────────────────────────────┬────────────────────────────────┤
│                                   │ 0x00400010 <loop> | 7 carried  │  where the run stands
│   main.s     lib.s                ├────────────────────────────────┤
│                                   │ Registers │ Floats │ Control   │
│   loop: add  t1, t1, t0           │ t0        │ 0x00000002         │
│         addi t0, t0, -1           │ t1        │ 0x00000005         │
├───────────────────────────────────┴────────────────────────────────┤
│ Text │ Data │ Labels │ Frames │ Console │ Messages │ Cache │ Disk  │
│ 0x00400010 | 002383b3 | add x7,x7,x5 | loop: add t1, t1, t0        │
└────────────────────────────────────────────────────────────────────┘
```

One window, with the source and the state of the machine in it at the same time — not the two modes
of [RARS](https://github.com/TheThirdOne/rars), whose Edit and Execute cannot be seen together.
Both dividers are moved by hand and the lower views scroll sideways, because there are more pages
than there is ever room for.

## What the window can be told to do

| Key | Action | What it does |
|---|---|---|
| `F3` | Assemble | assemble the files and stand at the first instruction |
| `F5` | Run | carry on to a breakpoint, a watchpoint or the end |
| `F4` | To here | carry on to the line the cursor is on, and no further |
| `F7` | Step | one instruction |
| `F6` | Over | one instruction, passing over a call |
| `Shift+F6` | Finish | out of the call the run is inside |
| `F8` | Back | the last step back |
| `Shift+F7` | Cycle | the model of the pipeline on by one cycle |
| `F9` | Pause | let the machine stand where it is |
| `F11` | Stop | end the run where it is |
| `F12` | Restart | the program from the beginning |

The keys are RARS's where the action is RARS's, so a person who comes from it keeps their fingers;
the actions it has not got took the free keys beside them. The names are the session's own —
there is no Run-and-Debug pair, because a session always keeps a journal and always stands still
once a program is assembled, so there is nothing to choose between before a run begins.

Which of them are possible is a rule rather than a widget, and the same rule in both front ends: a
run that is going can be paused and cannot be stepped, a run that stands still can be stepped and
cannot be paused, `Back` needs something in the journal, and `Cycle` needs a pipeline to be
modelled — it is not on the screen at all while nobody asked for one. A program waiting for a line
can only be stopped. The window refuses what is not possible itself rather than letting the
controller refuse it, which matters for `Stop`: it ends the run it is given to, and a machine
standing still is in no run to end.

`Over`, `Finish` and the Frames view read the return address the way the calling convention says,
so a program that keeps `ra` somewhere else will send all three astray. `To here` is the exact one.

## What is done to the files

| Key | Action |
|---|---|
| `Ctrl+N` | a file that is not on the disk yet |
| `Ctrl+O` | open a file |
| `Ctrl+S`, `Ctrl+Shift+S` | write this file, or write it somewhere else |
| `Ctrl+W` | close this file |
| `Ctrl+F` | find and replace in this file |
| `Ctrl+Z`, `Ctrl+Shift+Z` | undo, redo |
| `Ctrl+B` | a breakpoint on the line the cursor is on |
| `Ctrl+P` | the program… — what the program **is** |
| `Ctrl+,` | the run… — what the machine is **given** besides it |
| `F1` | what can be written… — every word the assembler takes |

These depend on what is open and what has been changed, not on what the machine is doing: a file
may be read and written while a program runs. The program window and the run window may be opened
with nothing open at all, because a project names files nobody has opened and the settings of a run
belong to the person rather than to any one program.

## The editor

A tab for every file. What it colours is made from the tables of the assembler itself — the
mnemonics of `pyrars.isa` and the pseudo-instructions, the directives, the registers and the
control registers — so the editor cannot know a word the assembler does not. The wider machine is
coloured whatever the program will be assembled for: an editor is not told, and a program of RV64
is not a program of mistakes.

The margin holds four marks: what the assembler called an **error**, what it called a **warning**,
a **breakpoint** — the red dot, which is put in and taken out by clicking — and the **arrow** at
the line the machine stands on. The arrow follows the machine while a run is stepped and the
editor scrolls to it; it stops scrolling while a run is going, because a window that jumped about
thirty times a second could not be read.

The pointer resting on a word says what that word is: the forms an instruction takes, what a
pseudo-instruction is written out as, which register answers to which name. `F1` is the same thing
for looking something up when there is nothing to point at, and what is offered while a line is
being typed comes from the same tables, together with the names the program itself gives things.

Files are written to the disk before a program is assembled, because an assembler reads files from
the disk and what is on the screen has to be there first.

## How fast the run goes

A machine left to itself cannot be watched: a loop of Python still carries out a hundred thousand
instructions a second. So a run may be held back — *as fast as it can*, or 30, 10, 5, 2 or 1
instructions a second. The choice is read again every turn of the loop, so a run already under way
slows down or speeds up as soon as it is made.

A slowed run is a run somebody is watching, and the window keeps every view up to date while it
goes; see **What a window costs** below.

## How values are written

One choice for all of them — `hex`, `dec` or `ascii` — because somebody reading a register in
hexadecimal is reading memory in hexadecimal too. The numbers a device or a model holds are
written as what they are: a yes or no as a yes or no, an address as an address, a count in decimal.

## The views

Beside the program, over the three files of registers, one line says what the run is doing: where
it stands, the instruction there, and how many instructions have been carried out.

| Page | What it holds |
|---|---|
| Registers, Floats, Control | `x0`–`x31` by name and by number, `f0`–`f31` as bits and as the number those bits are, and the control registers with what each of them holds spelled out field by field |
| Text | the program as it was assembled: the breakpoints, the address, the word, the basic instruction and the line it came from |
| Data | what the program laid out and what the run has written since |
| Labels | every name the program gives something, where it is, and how far it reaches |
| Frames | the calls the run is inside, as far as the calling convention lets anyone tell |
| Console | what the program writes, and where a line it asks for is typed |
| Messages | what the window has to say: what the assembler said, a question that failed, a setting that could not be read |

The Console comes forward by itself when the program asks for something, and a line may be typed
into it before the program asks: it is kept until the program wants it. Nothing written there can
be taken back — a window is a terminal, and a step back does not unprint what has been seen.

### The pages that come and go

A page about something nobody asked to watch says nothing and takes the room of a page that would.
So the **Cache**, the **Pipeline**, the **Counted** page and one page for **every device** are
there only while the run is set up to fill them, and they are at the end of the notebook, after the
pages that are always there, so that nothing a person is reading moves about when a setting
changes.

The models are given to the machine when a program is assembled, so a page that is there and empty
says which model it is waiting for and that assembling again is what fills it.

### Pictures beside tables

A table says what happened; a picture says what is happening. The cache, the pipeline and the
counting each have one, beside their table — the grid of the cache with every block in it, the
diagram of the pipeline cycle by cycle with the cycle being looked at marked, the kinds of
instruction a run was made of as bars. `Shift+F7` walks the pipeline a cycle at a time, which is a
smaller thing than an instruction and no step of the machine at all.

The room the lower views have is wide and shallow, while a picture and a table of names and values
are both narrow and long; so they stand side by side rather than one above the other.

## The devices

Every device gets a page: its picture, if there is one to draw, and the table of what it holds
beside it. The bitmap display shows its units, the keyboard and display the text it is showing,
the digital lab its segments and its keys, the disk its blocks, the controller how far it has got.
A timer is a time and a time it was asked for, and a drawing of a number tells nobody anything the
number does not, so a timer is its table alone — and so is a device of somebody else's making, the
day it is attached, with nothing added to the window for it.

Some of them can be talked to, and under the picture of those there is a line of whatever that
takes:

| Device | What can be done to it |
|---|---|
| the keyboard and display | a line typed at it; a file poured into it |
| the digital lab | a key pressed, by clicking it |
| the disk | a file put on it; its image written to a file |
| the timer | the clock started and stopped |

A line typed at the keyboard reaches the device **at once**, every letter of it, room or no room —
and a keyboard of one key loses what the program did not read in time, which the panel counts and
says. That is the point of the device: the asking is not continuous and letters can be lost, and a
line that could not be lost would teach the opposite. A **file** poured in goes the other way: the
device takes a letter whenever it has room, so a prepared input is read whole, exactly as
`--device keyboard:keys=FILE` does on the command line.

The image of a disk is written **when it is asked for** and at no other moment. The command line
writes it back at the end of a run because the person named the file in the command, which is the
asking; a window that wrote to somebody's disk unasked would be taking that on itself.

Nothing but the thread of the run ever touches a device. A panel knows what can be done to it and
nothing of how that reaches the machine.

## What the program is

`Ctrl+P`. The files it is made of, which of them is the main one, the width of the machine, the
memory configuration, and whether pseudo-instructions are allowed. It is a project, and it can be
written beside the program and opened again, as in [session.md](session.md):

```json
{
  "files": ["lib.s", "main.s"],
  "main": "main.s",
  "xlen": 32,
  "mem_config": "Default",
  "pseudo": true
}
```

A project settles nothing about a run — no devices, no models, no breakpoints — because those are
choices of the moment and a project outlives any one run of it.

## How it is run

`Ctrl+,`. The other half: which devices are attached and how each is built, whether the run is
counted, whether a cache and a pipeline are modelled, and how a branch is guessed at. What can be
set is read off the models and the devices themselves, so a model that gains an option gains a row
here the same day.

These belong to the person rather than to the program, so they are kept where a desktop keeps such
things — `$XDG_CONFIG_HOME/pyrars/run.json`, or `~/.config/pyrars/run.json`:

```json
{
  "statistics": true,
  "cache": {"sets": 4, "block_bytes": 16, "replacement": "lru"},
  "fetches": false,
  "instructions": null,
  "pipeline": {"forwarding": true},
  "guesser": {"predictor": "table", "entries": 16, "bits": 2},
  "devices": {"keyboard": {"delay": 2}, "halt": {}}
}
```

**Only the window reads that file.** `pyrars run` never does, because it must behave the same way
on every machine or a script is not a script; the command line is told what to attach in the
command itself (`--device`, `--cache`, `--pipeline`, `--stats`). A file that cannot be understood
is said in the Messages and the defaults are used, because a window must open whatever is in it.

A change here reaches the machine the next time a program is assembled, which the window says,
because a change that waits for an Assemble looks like a change that did nothing.

## What a window costs

While the machine is running, everything the window does is paid for out of the run — the two share
one interpreter — and the prices are not alike:

- a **picture** is one call into GTK and a redraw, so it keeps up whatever the run is doing;
- a **table** is a call for every row, and such a call costs a hundred times its price while a
  thread of Python runs flat out: the text segment took two seconds to put up during a run against
  a few milliseconds when the machine stood still.

So the pictures follow a run at any speed, and the tables are put up again when the machine stands
still and while a run is **held back to a speed** — a slowed run sleeps between its instructions,
the calls are cheap again, and watching the numbers change is the whole point of slowing it. They
wait while a run goes as fast as it can, where nothing of them could be read anyway.

Three more rules follow from the same arithmetic:

- The window cannot ask the session anything while a movement is going — a question would wait in
  the queue behind it, and a movement nobody stops never ends. So the questions travel **with the
  snapshots**, and they are the questions of the page that is **open** and of nothing else: one
  page, thirty times a second.
- The thread of the run says nothing more until the window has dealt with the last snapshot.
  Everything a snapshot costs is paid in the window, and a machine at its own speed can say far
  more than any window can answer for.
- The registers are asked for every snapshot only while a speed is set. They are always on the
  screen, but at the speed of the machine they change tens of thousands of times a second and
  nobody is reading them.

## How it is built, and a front end of your own

The window is in two halves. Everything that turns the data of a session into what is shown — the
rows of a table, the pictures as plain numbers, what a word of the language means, which actions
are possible — lives in modules that import no `gi` at all and are tested like every other module
of the project. The widgets themselves stay thin, and their tests carry the marker `ui`, which
skips where there is no GTK and no display.

| Module | What it is |
|---|---|
| `ui/actions.py` | what a window can be told to do, and when |
| `ui/shown.py` | the rows of every table |
| `ui/drawing.py` | the pictures, as parts with places and colours |
| `ui/help.py`, `ui/meanings.py` | what a word of the language means, and what a setting means |
| `ui/highlighting.py`, `ui/completions.py` | the language definition and what is offered while typing |
| `ui/window.py`, `ui/editor.py`, `ui/devices.py`, `ui/canvas.py` | the widgets |

A front end of your own needs none of this: it needs `pyrars.session`, which answers in data and
knows nothing of any window. [session.md](session.md) says how, and this window is one example of
it — a `RunController` whose events arrive from the thread of the run and are handed to the main
loop with `GLib.idle_add` before a widget is touched.

## See also

- [the session](session.md) — the debugging underneath the window, and the console front end over
  the same data
- [the devices](devices.md) — what each device is, and what a program writes to talk to it
- [the models](analysis.md) — the cache, the pipeline, the guesser and the counting
- [the assembler](asm.md) — the language the editor colours
