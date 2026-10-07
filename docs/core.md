# pyRARS machine

The engine of pyRARS: a RISC-V machine written in pure Python. It takes an assembled program and
runs it — memory, registers, control and status registers, the instructions of RV32 and RV64, traps
and interrupts, the services a program asks for with `ecall`, a journal that makes a step
undoable, and the loop that puts all of it together.

Nothing here draws a window and nothing here assembles: the machine consumes an
`AssembledProgram` (`pyrars.isa.program`) and talks to the world outside through one small
protocol, so the same engine serves the command line, the tests and the user interface.

Supported instructions: RV32I and RV64I with M, F, D, Zicsr, Zifencei, `ecall`, `ebreak`, `wfi` and
`uret` — the set of [RARS](https://github.com/TheThirdOne/rars), whose dialect this project
follows. There are no compressed (C) and no atomic (A) instructions.

Entry points: the command line `python -m pyrars run`, and `pyrars.core.simulator.Simulator` for
use from other code.

## Command line

```
python -m pyrars run [options] file...        assemble and run a program
```

What the program itself writes, and every value the run was asked to print, go to the standard
output; the report that says why the run ended goes to the error stream. A program reads the
standard input. The exit code is the code the program exited with, `1` when a trap stopped it or
the program did not assemble, and `0` otherwise.

| Short | Long | Meaning |
|---|---|---|
| `-x` | `--xlen {32,64}` | width of the registers; default `32` |
| `-m` | `--mem-config NAME` | memory configuration: `Default`, `CompactDataAtZero`, `CompactTextAtZero` |
| | `--self-modifying` | let the program read and write its own text segment |
| | `--steps N` | stop after N turns of the loop; by default a run has no limit |
| `-r` | `--registers NAMES` | print these registers at the end, e.g. `a0,t1,f2,fcsr` |
| | `--memory LOW-HIGH` | print this range of memory at the end; may be repeated |
| `-c` | `--instruction-count` | print how many instructions were carried out |
| `-f` | `--format {hex,dec,ascii}` | how printed values look; default `hex` |
| | `--break ADDRESSES` | stop before the instruction at any of these addresses |
| | `--args ARG...` | arguments of the program itself; comes last of all |
| `-w` | `--warnings-are-errors` | a warning of the assembler makes the program fail |
| | `--no-pseudo` | forbid pseudo-instructions |
| | `--start-at-main` | the entry point is the label `main` when the program defines one |

A register may be named by number (`x5`, `f12`), by the name of the calling convention (`t0`,
`fa0`, `fp`) or, for a control register, by its own name (`fcsr`, `uepc`, `instret`). A name nobody
has is refused before the program runs, not after it.

```
$ python -m pyrars run -c -r t0,t1 --memory 0x10010000-0x10010004 hello.s
hi there
instructions	12
t0	0xfffffffb
t1	0x41424344
Mem[0x10010000]	0x41424344	0x00000000

Program terminated by calling exit
```

### Why a run ended

| Line (error stream) | Meaning | Exit code |
|---|---|---|
| `Program terminated by calling exit` | the program asked to stop (service 10 or 93) | the code it gave |
| `Program terminated by dropping off the bottom.` | it ran past the last word of its text | `0` |
| `Program terminated when maximum step limit N reached.` | `--steps N` | `0` |
| `Error in f.s line 7: Runtime exception at 0x00400010: <message>` and `Simulation terminated due to errors.` | a trap with nowhere to go | `1` |
| `Program stopped waiting for an interrupt that cannot come` | `wfi` and no device that could answer | `0` |
| `Program stopped at a breakpoint 0x00400010` | `--break` | `0` |

Everything a run was asked to print is printed once, at the end, whatever ended it: the values of a
run that stopped at a breakpoint are the values at that breakpoint.

Every message of the machine has one shape — a capital letter, no full stop, and the thing it is
about last, after a space:

```
Load address not aligned to word boundary 0x00000001
Cannot write directly to text segment 0x00400000
Address out of range 0x90000000
Cannot fetch an instruction from 0x90000000
Undefined instruction 0x11223344
Invalid rounding mode 5 in frm
Cannot write to the read-only control register cycle
No such control register 0x123
Invalid integer input (syscall 5)
Invalid or unimplemented syscall service 777
Interrupt handler was not supplied, but interrupt enable was high
```

## The parts

```
pyrars.core
├── options     what is fixed for one run
├── memory      bytes, the rules of access, the bus of the devices
├── regs        x0..x31, f0..f31, the program counter
├── csr         the seventeen control and status registers
├── executor    one instruction of I, M, Zicsr and the fences
├── floats      one instruction of F and D, through pyrars.softfloat
├── traps       what waits, and what the machine does with it
├── syscalls    the forty-one services of `ecall`
├── systemio    the protocol to the world outside, and a console
├── history     the journal that makes a step undoable
└── simulator   the loop: one turn, and a run
```

`pyrars.core` imports only `pyrars.isa` and `pyrars.softfloat`. It never imports the assembler, the
devices or the user interface.

## Running a program from code

```python
from pyrars.asm.assembler import Options as AsmOptions, assemble
from pyrars.core.machine import Machine
from pyrars.core.options import Options
from pyrars.core.simulator import Simulator, Stop, StopReason

program = assemble(["hello.s"], AsmOptions())
machine = Machine(Options())                 # the world defaults to the console
simulator = Simulator(machine)
simulator.load(program, arguments=("one", "two"))

stop = simulator.run(max_steps=100_000, breakpoints=frozenset({0x00400010}))
print(stop.reason, simulator.count, machine.x.read(10))
```

`Options` is what a run cannot change: `xlen` (32 or 64), `config` (a `MemoryConfig`),
`self_modifying`, `history_depth` and `debug`. The width and the configuration are a contract with
the assembler, because the addresses of a program are built into its machine code: a program
assembled for another width or another configuration is refused rather than run wrongly.

`Machine` holds the state: `memory`, `x`, `f`, `csr`, `pending`, `io`, `heap`, `generators` and
`history`. `Machine.load(program, arguments)` puts the program in memory, sets the program counter
and lays the arguments out on the stack.

### One turn at a time

`Simulator.step()` carries out one turn of the loop and returns either `Stepped` — the address, the
word, the decoded instruction, where the machine went, the event it took and the cause of a trap —
or `Stop`, which says why the machine stopped. `Simulator.run()` repeats that until something ends
the run. `back_step()` undoes the last turn, `pause()` and `stop()` end a run from another thread,
and `count` is how many instructions have been carried out.

A turn is: take whatever event is waiting, fetch the instruction the program counter points at,
carry it out, count it. The order matters, because it is the state a handler sees. A step limit
counts turns, not instructions: a turn that only enters a handler carries out nothing.

Nothing a program does reaches the caller as a Python exception. A refused access, an illegal
instruction, a call of the environment — each becomes a trap that waits in its slot and is taken
before the next turn; everything that ends a run comes back as a `Stop`.

## Memory

A sparse store of 4 KiB pages: a program that touches three places costs three pages. The address
space is 32 bits wide in both widths of the machine, so the address `2**32 + x` is the address `x`.

| Area | `Default` | What a program may do |
|---|---|---|
| text | `0x00400000`–`0x0ffffffc` | fetch; read and write only with `self_modifying` |
| data | `0x10000000`–`0x7fffffff` | read, write |
| devices | `0xffff0000`–`0xffffffff` | read, write; the bus of `pyrars.devices` when one is attached |
| anything else | | refused: `Address out of range 0x…` |

The whole of an area is reachable, not a window of it.

Inside the data segment the assembler and the machine know these places: `0x10000000` extern,
`0x10008000` the global pointer, `0x10010000` the data of a program, `0x10040000` the top of the
heap that `sbrk` hands out, `0x7fffeffc` the initial stack pointer, `0x7ffffffc` the base of the
stack. The two compact configurations put the same areas in 32 KiB.

Every access must be aligned to its own width: a word at a multiple of four, a doubleword at a
multiple of eight. A misaligned or refused access raises a trap with the cause the ISA manual gives
it.

`read`, `write`, `read_bytes`, `write_bytes` and `fetch` are what a program does; `peek` and `poke`
are what a tool does, with no rules and no notice. `subscribe(kind, callback, low, high)` watches
accesses in a range — for the cache model, the devices and the views of the interface. With no
subscriber an access allocates nothing.

## Registers

`x0`..`x31` and the program counter, kept unsigned at the width of the machine; `x0` keeps its zero,
and `sp` and `gp` start at the addresses of the configuration.

`f0`..`f31` are 64 bits wide whatever the machine is. A single precision value lives there
NaN-boxed, as chapter D of the ISA manual requires: the upper 32 bits are all ones. Reading a single
from a register that holds something else gives the canonical NaN — that is what every instruction
taking a single sees — while `fmv.x.w` and `fsw` take the low 32 bits as they lie.

The seventeen control and status registers come in four kinds: plain (`uie`, `uip`, `utvec`,
`uscratch`, `uepc`, `ucause`, `utval`), masked (`ustatus` keeps `0x11`, `fcsr` keeps `0xff`), a
window into another register (`fflags` and `frm` are fields of `fcsr`; `cycleh`, `timeh`, `instreth`
are the upper halves of the counters) and read-only (the three counters and their halves). `cycle`
and `instret` count one per instruction; `time` is read from a clock that a test can replace, so a
run can be made repeatable.

## Traps and interrupts

Causes are those of the ISA manual: 0 misaligned instruction address, 1 instruction access fault, 2
illegal instruction, 3 breakpoint, 4/6 misaligned load/store, 5/7 load/store access fault, 8
environment call; interrupts are `0x80000000` software, `0x80000004` timer, `0x80000008` external.

Three slots hold what waits — one external event, one timer event, one trap of an instruction — and
while a slot is full a new event of its kind is dropped. Before every instruction the machine looks
at them in this order: external, software (whose bit the program sets in `uip` itself), timer, then
the trap of the instruction before.

Taking any of them writes `ucause`, `uepc` (the address of the faulting instruction itself) and
`utval`, and enters the handler at `utvec` only while `ustatus.UIE` is set and there is something to
run there; otherwise the machine stops and the report says what happened. Inside a handler `UIE` is
clear and `UPIE` holds what it was, which `uret` puts back. The vectored mode of `utvec` applies to
interrupts only. A breakpoint (`ebreak`) never reaches a handler.

## Services

Forty-one services by number in `a7`. Seven of them — 17, 57, 62, 63, 64, 93 and 1024 — are the
numbers of the system itself and keep its conventions: the flags of `open` (0 read, 1 write, 2 read
and write, 9 append), the three places `lseek` counts from, the descriptors 0, 1 and 2 of the
streams, and a negative error number when something fails, so a program can tell a missing file
(`-2`) from a descriptor nobody opened (`-9`).

| | |
|---|---|
| print | 1 PrintInt · 2 PrintFloat · 3 PrintDouble · 4 PrintString · 11 PrintChar · 34 PrintIntHex · 35 PrintIntBinary · 36 PrintIntUnsigned |
| read | 5 ReadInt · 6 ReadFloat · 7 ReadDouble · 8 ReadString · 12 ReadChar |
| files | 1024 Open · 63 Read · 64 Write · 57 Close · 62 LSeek |
| the machine | 9 Sbrk · 10 Exit · 93 Exit2 · 17 GetCWD · 30 Time · 32 Sleep |
| random | 40 RandSeed · 41 RandInt · 42 RandIntRange · 43 RandFloat · 44 RandDouble |
| dialogs | 50 ConfirmDialog · 51–54 InputDialog{Int,Float,Double,String} · 55–56, 58–60 MessageDialog… |
| sound | 31 MidiOut · 33 MidiOutSync (answered, nothing is played) |

Every service works with values as wide as the machine, because the convention speaks of registers:
in RV64 `PrintIntHex` writes sixteen digits, `ReadInt` reads a wide number, `Time` gives the whole
count of milliseconds in `a0` and leaves `a1` at zero.

The random services draw from seedable streams, so a program that seeds its stream (service 40) is
repeatable. The services of MIDI are answered and play nothing.

A program's arguments lie at the top of the stack: the texts first, then a table of the count, the
pointers and a zero, whose last word lies at the stack pointer the program would have started with;
`a0` takes the count and `a1` the table.

### The world outside

```python
class SystemIO(Protocol):
    def write(self, fd: int, data: bytes) -> int: ...
    def read(self, fd: int, count: int) -> bytes: ...
    def read_line(self) -> str: ...
    def open(self, path: str, flags: int) -> int: ...     # raises OSError on failure
    def close(self, fd: int) -> None: ...
    def lseek(self, fd: int, offset: int, whence: int) -> int: ...
    def sleep(self, milliseconds: int) -> None: ...
    def cwd(self) -> str: ...
    def dialog(self, kind: Dialog, message: str, payload: object) -> object: ...
    def mark(self) -> object: ...                         # where the world stands
    def rewind(self, mark: object) -> None: ...           # back there, under a debugger
```

`ConsoleIO` is the world as a text session: two streams out, one in, and real files. A dialog
becomes the console — a message is printed, a question is printed and its answer read. The user
interface will give the same protocol real windows, and a test gives a world that only writes down
what it was asked for, which is why a program that sleeps five seconds costs a test nothing.

## Taking a step back

`History` keeps, for every turn, the value each place held **before** it changed; taking the turn
back is a plain write, and nothing is worked out again. Each turn also keeps what changes anyway:
the program counter, `cycle` and `instret`, the top of the heap, the waiting slots and the mark of
the world.

What goes back: the integer and floating point registers, the program counter, the control
registers with their counters, the memory (down to the mark that says a word of the text holds an
instruction), the top of the heap of `sbrk` and the state of the random streams. Under
`Options.debug` the world goes back too: what was read is handed out again and the open files
return to where they stood, so a step back and a step forward give the same thing. What has really
left — bytes written into a file, a line printed on a terminal — stays.

`Options.history_depth` is how many turns can be taken back; zero, the default, keeps no journal at
all, and then a write to a register or to memory writes nothing down. A debugging session asks for a
depth of its own — 2000 turns is a sensible one.

## Tests

`tests/unit/test_core_*.py` check every part on its own, with values derived by hand from the ISA
manual, IEEE 754-2019 and the conventions of the system. `tests/devel/test_*_vs_rars.py` run the
same programs through RARS and compare: registers, memory, output, instruction count, the exit code
and the report. The differential tests need `java` and `tests/devel/rars1_6.jar`, and skip
themselves when either is missing.

```
python -m pytest tests/unit          # no Java needed
python -m pytest tests               # everything, RARS included
```

## See also

- [the assembler of pyRARS](asm.md), which produces the programs this machine runs
- the RISC-V ISA manuals — <https://docs.riscv.org/reference/isa/>
- RARS, the assembler and simulator this dialect follows — <https://github.com/TheThirdOne/rars>
