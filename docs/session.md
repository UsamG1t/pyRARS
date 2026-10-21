# pyRARS session

A program that misbehaves is not read, it is watched. A session is pyRARS watching one: it stops
where you ask, shows what the machine holds, steps forward — and backward — and says what it is
guessing about rather than pretending to know.

There is no window here. The session is the part underneath one, and it answers in data: a place, a
list of values, what a movement ended on. Two things are built on it. One is the console debugger of
this page, which turns that data into lines you can read over ssh. The other is the window, which
will show the same data its own way. Neither knows anything the other does not.

## Opening a session

```
python -m pyrars run --debug-mode file...
```

```
$ python -m pyrars run --debug-mode sum.s
(pyrars) where
0x00400000 <main> | auipc x5,0x0fc10 | main:   la t0, table | sum.s:7
```

Every line is made of pieces divided by ` | `, and inside a table the columns are padded so they
stand under one another. It reads by eye on a slow link, and a script can still cut it by `" | "`.

The prompt says whose turn it is to type. `(pyrars) ` asks for a command; `program> ` means the
program itself is asking for something, and the line goes to it. What the program writes is written
as it is, with nothing in front of it.

## Asking the debugger about itself

`?` prints every command: its group, its name, what it takes, what it is for. `? COMMAND` prints
that one in full — what else it may be called, and a word on every argument.

```
(pyrars) ? watch
watch [add RANGE [read|write|both] || del N|all || list] -- stop when the program touches a place in memory
Args:
add RANGE       | watch this range of memory
read|write|both | what to watch for, both by default
del N|all       | stop watching: the number a place was given when it was added; "all" for every one of them
list            | what is watched, which is what it does on its own
RANGE           | ADDRESS, or LOW..HIGH (LOW-HIGH as well); one address alone means the word it lies in, and either end may be a name of the program
```

The alternative forms of a command are divided by `||`; a bare `|` inside a word, as in
`read|write|both`, is a choice between those three and nothing more. Every command has its short
names: `s` is `step`, `c` is `continue`, `bt` is `frames`.

## A place

Wherever a command wants a place, it takes any of three things: an address (`0x400010` or
`4194320`), a name of the program (`main`, `loop`, `table`), or `file:line` (`sum.s:12`). A range of
memory is `LOW..HIGH`, and one address alone means the word it lies in.

## Stopping where you want

```
(pyrars) break add keep
1 | 0x0040003c <keep> | auipc x5,0x0fc10 | keep:   la t0, total | sum.s:20
(pyrars) continue
breakpoint 1 after 32 | 0x0040003c <keep> | auipc x5,0x0fc10 | keep:   la t0, total | sum.s:20
```

A breakpoint stops the machine *before* the instruction at that place, and never on the one a run
starts on, so a run always carries on from where it stopped. `break list` shows them, `break del N`
takes one off, `break del all` takes them all off. `--break ADDRESSES` on the command line puts
them in before the session begins.

`until PLACE` goes to a place without leaving a breakpoint behind.

## Watching a place in memory

```
(pyrars) watch add total write
1 | write | 0x10010018..0x1001001b | hits 0
(pyrars) continue
touched 1 | write | 0x10010018 | 4 bytes | 0x0000000e | by 0x00400044 <keep+8>
watchpoint 1 after 35 | 0x00400048 <keep+12> | jalr x0,x1,0 | ret | sum.s:22
```

The instruction that touched the place is named, so the question "who wrote this?" has an answer
rather than a guess. A watch is for reads, for writes or for both, and it may cover a range.

## Going forward and back

| Command | What it does |
|---|---|
| `step [N]` | N instructions, one at a time |
| `over [N]` | the same, but a call is passed over |
| `back [N]` | N steps back |
| `finish` | out of the call the run is inside |
| `continue` | on to a breakpoint, a watchpoint or the end |
| `until PLACE` | on to a place, exactly |
| `restart` | the program from the beginning |

Every movement answers with one line: what happened, and where the machine now stands.

A step back puts the machine back where it was — the registers, the memory, the counters — and under
a debugger it takes the world outside back with it, so a program that read a line reads the same line
again. What a *person* changed with `set` or `poke` is not a step of the machine and is not undone;
but a step back still puts back what that step itself changed, because that is what taking a step
back means.

`restart` begins the program again, keeping the breakpoints and the watches and putting the devices
back where they began. It is a *fresh* run: the world outside is not put back with it, so a program
that asks for a line asks again rather than silently reading what it was given last time.

## Three commands that guess

`over`, `finish` and `frames` read the return address the way the calling convention says: a call is
`jal` or `jalr` that writes `ra`, a return is `jalr` that reads `ra` and writes nothing. A program
that keeps its return address somewhere else will send all three astray, and they say so in their
help. `until` is the exact one.

```
(pyrars) frames
1 | 0x0040003c <keep> | auipc x5,0x0fc10 | keep:   la t0, total | sum.s:20 | from 0x0040002c <loop+20> | sp 0x7fffeffc
```

## Looking at things

```
(pyrars) regs t2
t2 | x7 | 0x0000000e
(pyrars) data
0x10010000 | .word | 4 | 0x00000003
0x10010004 | .word | 4 | 0x00000001
0x10010008 | .word | 4 | 0x00000004
0x1001000c | .word | 4 | 0x00000001
0x10010010 | .word | 4 | 0x00000005
0x10010014 | .word | 4 | 0x00000005
0x10010018 | .word | 4 | 0x0000000e
(pyrars) mem table..0x10010013
0x10010000 | 0x00000003 | 0x00000001 | 0x00000004 | 0x00000001
0x10010010 | 0x00000005
```

| Command | What it shows |
|---|---|
| `where` | where the machine stands |
| `list [PLACE] [N]` | the instructions around a place, with the breakpoints marked |
| `source [N]` | the lines of the program around the run |
| `regs`, `fregs`, `csr` | the three files of registers; a floating point value is shown as a number as well, and a control register with its fields spelled out |
| `mem RANGE` | words of memory, four to a row |
| `data [RANGE]` | the data the program laid out, each item as its directive wrote it and as it stands now |
| `stack [N]` | words from where the stack pointer stands, with the frames marked |
| `symbols [PATTERN]` | the names of the program |
| `count` | instructions carried out, turns of the loop, steps that can still be taken back |

`format hex|dec|ascii` says how values are written; `-f` on the command line sets it for the session.

## The things around the machine

Anything attached to the run answers in one shape: `info` for what a thing **is**, `show` for what it
**holds**.

```
$ python -m pyrars run --debug-mode --cache sets=4 --stats --device keyboard sum.s
(pyrars) continue
exited 0 after 38 | 0x00400038 <loop+32> | ecall | ecall | sum.s:19
(pyrars) cache show
cache | set 0 | place 0 | 0x10010000..0x1001000f | clean
cache | set 1 | place 0 | 0x10010010..0x1001001f | dirty
(pyrars) stats
instructions       | 38
turns              | 38
traps              | 0
unknown            | 0
kind.alu           | 24
kind.load          | 6
kind.store         | 1
kind.branch        | 5
kind.jump          | 2
```

| Command | What it answers |
|---|---|
| `device list`, `device NAME` | what is attached, and what one of them holds |
| `cache info`, `cache show` | the settings and counters, or the blocks held |
| `pipeline info`, `pipeline show` | the settings and counters, or the diagram of cycles |
| `guesser info`, `guesser show` | how a branch is guessed at, or the table of history |
| `stats` | what the run was made of |

A model is asked for by the flags of the command line (`--cache`, `--pipeline`, `--stats`,
`--device`), as in [analysis.md](analysis.md) and [devices.md](devices.md). A command about one that
was never asked for says so in one shape: `error | no cache was asked for: run with --cache`.

A device says what it holds itself, so a device of your own shows itself without the session knowing
anything about it.

## Changing something

```
(pyrars) set t2 0
t2 | x7 | 0x00000000
(pyrars) poke total 0x2a
0x10010018 | 0x0000002a
```

`set NAME VALUE` works for any register of any file — `t0`, `x5`, `ft1`, `fcsr`. `poke ADDRESS VALUE
[SIZE]` writes 1, 2, 4 or 8 bytes. Neither is a step of the machine, so neither is undone by a step
back.

## A session from a script

A session takes its commands from a file, from the command line, or from both — the file first.

```
$ cat look.txt
# where does the sum go wrong?
break add keep
continue
regs t2             # the sum, at the end of the loop
$ python -m pyrars run --debug-mode sum.s --commands look.txt -e "data" -e "quit"
```

Everything after `#` is a comment. An empty line repeats the last command, which is how you walk
through a program without typing `step` again every time. A scripted session prints each command
after the prompt, so the whole thing reads as a transcript — which is exactly what makes it worth
keeping in a repository beside the program.

Two flags take the program's own streams out of the shared terminal, for a session that is driven by
a script and read by a machine:

| Flag | What it does |
|---|---|
| `--commands FILE` | obey these commands before the prompt |
| `-e COMMAND` | obey this command before the prompt; may be repeated |
| `--program-input FILE` | the program reads from here instead of the terminal |
| `--program-output FILE` | the program writes here instead of the terminal |
| `--steps N` | no single movement runs longer than N turns |

`--steps` is worth setting for any scripted session: it is what keeps a program without an end from
holding the script for ever. Ctrl-C does the same by hand — it asks the machine to stop where it is,
and the session goes on at its prompt.

## A project

A project is what a program **is**: the files it is made of, which of them is its main file, the
width of the machine, the memory configuration, and whether pseudo-instructions are allowed. It is
JSON beside the program, by convention `<name>.pyrars.json`:

```json
{
  "files": ["lib.s", "main.s"],
  "main": "main.s",
  "xlen": 32,
  "mem_config": "Default",
  "pseudo": true
}
```

```
python -m pyrars run --project thing.pyrars.json --debug-mode
```

The main file is assembled first, so the program begins at the base of the text whatever order the
files are listed in. The paths are relative to the folder the project file lies in, so a project
moves with its files.

A project says nothing about **how** to run the program — no devices, no models, no breakpoints —
because those are choices of the moment and a project outlives any one run. What a project does
settle cannot be given on the command line as well: the files, `-x`, `-m` and `--no-pseudo` are
refused together with `--project`, rather than one of them quietly winning.

## For a front end of your own

`pyrars.session.debug` holds a session. Every command is a method, and every one of them answers in
data — never in text:

```python
from pyrars.session.debug import Session

session = Session(program)
session.add_break(session.address_of("keep"))
stopped = session.carry_on()          # Stopped(reason="breakpoint", place=..., steps=32)
for value in session.registers(("t2",)):
    print(value.name, value.value)    # t2 14
```

`pyrars.session.control` adds the one thing a window needs on top: a thread of its own, so that the
loop of a program never holds the window still.

```python
from pyrars.session.control import RunController

control = RunController(tell=self.on_event)   # called from the thread of the run
control.load(project)
control.carry_on()
```

Everything comes back through that one callback — a `Snapshot` of where the run is, an `Answer` to
something asked, a `Failed` for something that could not be answered — and a window wraps it in
`GLib.idle_add` so that it touches its widgets from its own thread only. Nothing but that thread
touches the machine.

A movement is a method (`step`, `carry_on`, ...), because it takes time. Everything else is a
question, asked with a function over the session:

```python
control.ask("registers", lambda session: session.registers())
```

Three things do not wait their turn, because the thread is busy inside a movement exactly when they
are wanted: `pause` lets the machine stand where it is, `stop` ends the run, and `answer` hands the
program the line it is waiting for. A program driven this way has no standard input: it asks — the
callback is told — and the thread waits until somebody answers.
