# pyRARS analysis

Four models that watch a run and say something about it: what it was made of, how a cache would have
fared, how long a pipeline would have taken, and which call the run is inside. None of them can
change anything — a run watched and a run unwatched do exactly the same thing — and none of them
costs anything unless it is asked for.

They answer questions a program cannot answer about itself. How many of these instructions are
loads? Would a larger block help? Where did the cycles go — waiting for values, or for wrong guesses
about branches? Is this recursion as deep as I think?

## Asking for them

```
python -m pyrars run --stats --cache sets=16 --pipeline forwarding=no --callstack file...
```

Every model prints what it has to say when the run is over, one `name<tab>value` to a line, so the
output can be read by eye or by a script.

| Flag | What it does |
|---|---|
| `--stats` | counts the instructions by kind, and the branches that went |
| `--cache [SIDE:]OPTIONS` | watches the accesses of the data segment with a cache |
| `--pipeline [OPTIONS]` | times the run on a pipeline of five stages |
| `--callstack` | follows the calls, as far as the convention lets anyone tell |

## What a run was made of

```
$ python -m pyrars run --stats sum.s
instructions	51
turns	51
kind.alu	32
kind.load	8
kind.branch	8
kind.jump	2
kind.system	1
category.alu	32
category.jump	2
category.branch	8
category.memory	8
category.other	1
branches.taken	7
branches.not-taken	1
```

`instructions` counts what was carried out, and `turns` the turns of the machine's loop — they
differ when an instruction could not be carried out and its trap took a turn of its own. The kinds
are the thirteen an instruction can be (`alu`, `multiply`, `divide`, `load`, `store`, `branch`,
`jump`, `csr`, `system`, `fence`, `float`, `float_load`, `float_store`); the five categories gather
them as a reader of coarse statistics expects, with multiplication and division among the
arithmetic and only the integer loads and stores as memory.

## The cache

```
$ python -m pyrars run --cache block_bytes=32,sets=4,ways=2 sum.s
cache.accesses	8
cache.hits	6
cache.misses	2
cache.rate	0.75
cache.writebacks	0
cache.through	0
```

| Option | |
|---|---|
| `block_bytes` | bytes a block holds; a power of two, 16 by default |
| `sets` | sets of blocks; a power of two, 8 by default |
| `ways` | blocks to a set: 1 (the default) is a direct cache, and one set is a fully associative one |
| `replacement` | `lru` (the default), `fifo` or `random` |
| `seed` | for `random`, so that a run can be repeated |
| `write_back` | `yes` (the default): memory hears when a block is thrown out, not at every write |
| `write_allocate` | `yes` (the default): a write that misses brings its block in |
| `log` | how many accesses are kept for a viewer; 10000 by default |
| `sample` | take a point of a time series every so many accesses; none by default |

A cache of its own for the instructions comes of naming a side:

```
python -m pyrars run --cache data:sets=8 --cache instructions:sets=16 sum.s
```

and `--cache unified:sets=16` is one cache that sees the instructions and the data together. A cache
watches the data segment only: the registers of a device are not the kind of thing a cache may keep.

The numbers mean what they say: `rate` is hits of accesses, `writebacks` the blocks memory had to be
told about because they were thrown out dirty, and `through` the writes that went to memory at once.
Nothing here times anything — a cache model counts hits, and what a hit is worth in cycles is
another question.

## The pipeline

```
$ python -m pyrars run --pipeline predictor=table,bits=2 sum.s
pipeline.cycles	72
pipeline.instructions	51
pipeline.cpi	1.4118
pipeline.lost	14
pipeline.lost.branch	6
pipeline.lost.load	8
pipeline.branches	8
pipeline.wrong	3
pipeline.guesser	a table of 16 entries of 2 bits
```

The machine of the model fetches, decodes, computes, reaches memory and writes back, one stage to a
cycle, in order. So one instruction takes five cycles and a stream of them one cycle apiece — and
`lost` says where the rest of the cycles went:

| Cause | |
|---|---|
| `data` | a value that was still being computed |
| `load` | a value that was still being read from memory |
| `busy` | a stage still holding an instruction with a longer EX |
| `port` | memory reached by one instruction while another would have been fetched |
| `branch` | what was fetched behind a branch and thrown away |
| `trap` | an instruction that could not be carried out |

| Option | |
|---|---|
| `forwarding` | `yes` (the default): a result may be used before it is written back |
| `one_port` | `no` (the default): the fetch and the reach into memory have a port each |
| `penalty` | cycles thrown away by a wrong guess; 2 by default |
| `trap_penalty` | and by an instruction that could not be carried out; 2 by default |
| `predictor` | `never` (the default), `always`, or `table` |
| `entries`, `bits`, `taken` | for a table: 16 entries of 1 bit, expecting nothing to be taken |
| `diagram` | keep and print this many instructions of the diagram; none by default |
| a kind of instruction | the cycles its EX takes, e.g. `divide=10,multiply=3` |

The options of a model always hold an `=`, so `--pipeline` may be given on its own - a file name
after it is a file, not a description of a machine.

With `diagram=N` the first N instructions are printed with the cycle each of their stages began in:

```
pipeline.row	0x00400010	lw	4 5 6 7 8
pipeline.row	0x00400014	add	5 6 8 9 10
```

The `add` above decoded in cycle 6 but could not compute until 8: it wanted the value the `lw` was
still reading.

This is a model of time, not a machine. It times a run that has already happened, so it never
changes what a program computes, and it knows nothing of caches: every fetch and every access takes
its one cycle here.

## The calls

```
$ python -m pyrars run --callstack sum.s
callstack.calls	1
callstack.returns	1
callstack.deepest	1
callstack.depth	0
callstack.unmatched	0
callstack.confused	0
callstack.beyond	0
```

**These numbers are a guess.** A RISC-V machine has no notion of a call: `jal` and `jalr` write an
address into a register and go, and a return is a jump to an address in a register. What makes one a
call and another a return is the convention programs keep — the address is left in `ra`, and `ret`
jumps to what `ra` holds — so the model reads a program that keeps that convention and misreads one
that does not.

It says where it lost its way rather than pretending:

| | |
|---|---|
| `calls`, `returns` | how many of each it recognised |
| `deepest`, `depth` | the deepest it went, and where it stands at the end |
| `confused` | returns that landed anywhere but where the call expected — a program that did not keep `ra` |
| `unmatched` | returns with nothing to return from, which is also what a run begun inside a call looks like |
| `beyond` | calls deeper than the model follows, so that a recursion without an end costs nothing |

Where the run is still inside a call, the frames are printed with the name of what was called and
the address of the call:

```
callstack.frame	factorial	0x00400044	0x7fffefd0
```

— what was called, the address of the call, and where the stack pointer stood when it was made.

## Using them from code

```python
from pyrars.analysis.cache import Cache, Settings
from pyrars.analysis.pipeline import Pipeline
from pyrars.analysis.predictors import History
from pyrars.analysis.stats import Statistics
from pyrars.core.simulator import Simulator

statistics, pipeline = Statistics(), Pipeline(predictor=History(bits=2))

def watch(turn):
    statistics.saw(turn)
    pipeline.saw(turn)

simulator.run(watch=watch)
print(statistics.kinds(), pipeline.cpi)
```

Every model takes the record of a turn (`Stepped`: the address, the word, the instruction, where the
machine went, whether it was carried out) and nothing else, except the cache, which takes addresses
of accesses, and the stack of calls, which takes the stack pointer alongside the turn. A cache is
fed from a subscription of the memory:

```python
from pyrars.core.memory import Access
machine.memory.subscribe(Access.READ, lambda access: cache.read(access.address))
```

## See also

- [the machine](core.md) — the run these models watch
- [the devices](devices.md) — what a program can talk to while they watch
- [the assembler](asm.md) — the language of the programs
