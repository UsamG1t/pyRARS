"""What each word of the language DOES, in one line.

Everything else the reference shows is made of the tables that assemble a program:
the forms an instruction takes, what a pseudo-instruction turns into, which
register answers to which name. This is the one thing those tables do not hold -
what the instruction is FOR - so it is written here, in our own words, from the
ISA manual (D5) and not borrowed from anybody.

It is a table like any other table of this project, and like the others it is held
to the tables beside it: a test asks that every instruction, every
pseudo-instruction and every directive the assembler takes has a line here, and
that nothing here is a word nobody has. An instruction added without a word about
what it does will not pass.

What can be settled about a RUN is here too, for the same reason: what each model
and each device is FOR, and what each option of it does. What the options are is
read off the models themselves (`session/settings.py`); nothing of either is
written down twice.

The floating point instructions are made rather than written out: the family is
exactly regular - the same operation in single and in double precision, and a
conversion between every pair of formats - so writing all sixty of them by hand
would be sixty chances to make a mistake in one of them.
"""

from pyrars.asm import pseudo
from pyrars.asm.directives import DIRECTIVES
from pyrars.devices import DEVICES
from pyrars.isa.instructions import instructions
from pyrars.isa.registers import CSRS, X_NAMES
from pyrars.session.settings import options_of

WIDE = ("but on the low 32 bits only, with the sign of the result spread "
        "through the whole of rd")

OF_INSTRUCTIONS: dict[str, str] = {
    # what the machine counts with
    "add": "Adds rs1 and rs2 and puts the sum in rd",
    "addi": "Adds a number to rs1 and puts the sum in rd",
    "sub": "Takes rs2 away from rs1 and puts what is left in rd",
    "lui": "Puts a number in the upper twenty bits of rd, with zeroes below it",
    "auipc": "Adds a number in its upper twenty bits to the address of this "
             "instruction and puts the answer in rd",
    "and": "Keeps the bits that are set in both rs1 and rs2, into rd",
    "andi": "Keeps the bits of rs1 that are set in a number, into rd",
    "or": "Sets in rd every bit that is set in rs1 or in rs2",
    "ori": "Sets in rd every bit that is set in rs1 or in a number",
    "xor": "Sets in rd every bit that differs between rs1 and rs2",
    "xori": "Sets in rd every bit of rs1 that differs from a number",
    "sll": "Shifts rs1 left by what rs2 says, filling with zeroes, into rd",
    "slli": "Shifts rs1 left by a number of places, filling with zeroes, into rd",
    "srl": "Shifts rs1 right by what rs2 says, filling with zeroes, into rd",
    "srli": "Shifts rs1 right by a number of places, filling with zeroes, into rd",
    "sra": "Shifts rs1 right by what rs2 says, keeping its sign, into rd",
    "srai": "Shifts rs1 right by a number of places, keeping its sign, into rd",
    "slt": "Puts 1 in rd when rs1 is below rs2 as signed numbers, and 0 when it is not",
    "slti": "Puts 1 in rd when rs1 is below a number as signed numbers, and 0 when "
            "it is not",
    "sltu": "Puts 1 in rd when rs1 is below rs2 as unsigned numbers, and 0 when it "
            "is not",
    "sltiu": "Puts 1 in rd when rs1 is below a number as unsigned numbers, and 0 "
             "when it is not",
    "mul": "Multiplies rs1 by rs2 and puts the low half of the answer in rd",
    "mulh": "Multiplies rs1 by rs2 as signed numbers and puts the high half in rd",
    "mulhu": "Multiplies rs1 by rs2 as unsigned numbers and puts the high half in rd",
    "mulhsu": "Multiplies a signed rs1 by an unsigned rs2 and puts the high half in rd",
    "div": "Divides rs1 by rs2 as signed numbers and puts the quotient in rd",
    "divu": "Divides rs1 by rs2 as unsigned numbers and puts the quotient in rd",
    "rem": "Divides rs1 by rs2 as signed numbers and puts the remainder in rd",
    "remu": "Divides rs1 by rs2 as unsigned numbers and puts the remainder in rd",
    # where the program goes next
    "beq": "Goes to the label when rs1 and rs2 are equal",
    "bne": "Goes to the label when rs1 and rs2 differ",
    "blt": "Goes to the label when rs1 is below rs2 as signed numbers",
    "bge": "Goes to the label when rs1 is at or above rs2 as signed numbers",
    "bltu": "Goes to the label when rs1 is below rs2 as unsigned numbers",
    "bgeu": "Goes to the label when rs1 is at or above rs2 as unsigned numbers",
    "jal": "Goes to the label, leaving the address of the next instruction in rd",
    "jalr": "Goes to rs1 plus a number, leaving the address of the next instruction "
            "in rd",
    # what it reads and writes
    "lb": "Reads one byte from memory, spreads its sign, and puts it in rd",
    "lbu": "Reads one byte from memory and puts it in rd with zeroes above",
    "lh": "Reads two bytes from memory, spreads their sign, and puts them in rd",
    "lhu": "Reads two bytes from memory and puts them in rd with zeroes above",
    "lw": "Reads a word from memory and puts it in rd",
    "lwu": "Reads a word from memory and puts it in rd with zeroes above",
    "ld": "Reads eight bytes from memory and puts them in rd",
    "sb": "Writes the low byte of rs2 to memory",
    "sh": "Writes the low two bytes of rs2 to memory",
    "sw": "Writes the low word of rs2 to memory",
    "sd": "Writes the whole of rs2 to memory, eight bytes",
    # the registers the machine keeps about itself
    "csrrw": "Puts rs1 in a control register and the old value of it in rd",
    "csrrs": "Sets in a control register every bit that is set in rs1, and puts the "
             "old value in rd",
    "csrrc": "Clears in a control register every bit that is set in rs1, and puts "
             "the old value in rd",
    "csrrwi": "Puts a small number in a control register and the old value in rd",
    "csrrsi": "Sets in a control register the bits of a small number, and puts the "
              "old value in rd",
    "csrrci": "Clears in a control register the bits of a small number, and puts the "
              "old value in rd",
    # and what it says to the world outside
    "ecall": "Asks the system for something; a7 says what, and a0 onwards are what "
             "it is given",
    "ebreak": "Stops the program here and hands it to whoever is debugging it",
    "fence": "Waits for the reads and writes before it to be seen before those after "
             "it",
    "fence.i": "Makes what has been written to memory visible to the instructions "
               "read from it",
    "uret": "Goes back from a handler to where the interrupt or the trap happened",
    "wfi": "Stands still until an interrupt arrives",
}

# The instructions of a 64-bit machine that work on the low half of a register:
# the same operation, and the sign of the 32-bit answer spread through rd.
for _wide, _narrow in (("addw", "add"), ("addiw", "addi"), ("subw", "sub"),
                       ("sllw", "sll"), ("slliw", "slli"), ("srlw", "srl"),
                       ("srliw", "srli"), ("sraw", "sra"), ("sraiw", "srai"),
                       ("mulw", "mul"), ("divw", "div"), ("divuw", "divu"),
                       ("remw", "rem"), ("remuw", "remu")):
    OF_INSTRUCTIONS[_wide] = f"{OF_INSTRUCTIONS[_narrow]}, {WIDE}"

# The floating point instructions, which are a family and are made as one.
FORMATS = {"s": "single precision", "d": "double precision"}
NUMBERS = {"w": "a 32-bit signed number", "wu": "a 32-bit unsigned number",
           "l": "a 64-bit signed number", "lu": "a 64-bit unsigned number",
           "s": "a single precision number", "d": "a double precision number"}
OPERATIONS = {
    "fadd": "Adds rs1 and rs2 and puts the sum in rd",
    "fsub": "Takes rs2 away from rs1 and puts what is left in rd",
    "fmul": "Multiplies rs1 by rs2 and puts the product in rd",
    "fdiv": "Divides rs1 by rs2 and puts the quotient in rd",
    "fsqrt": "Puts the square root of rs1 in rd",
    "fmin": "Puts the smaller of rs1 and rs2 in rd",
    "fmax": "Puts the larger of rs1 and rs2 in rd",
    "fmadd": "Multiplies rs1 by rs2, adds rs3, and puts the answer in rd, rounded "
             "once",
    "fmsub": "Multiplies rs1 by rs2, takes rs3 away, and puts the answer in rd, "
             "rounded once",
    "fnmadd": "Multiplies rs1 by rs2, adds rs3, and puts the answer in rd with its "
              "sign turned round",
    "fnmsub": "Multiplies rs1 by rs2, takes rs3 away, and puts the answer in rd with "
              "its sign turned round",
    "fsgnj": "Puts rs1 in rd with the sign of rs2",
    "fsgnjn": "Puts rs1 in rd with the sign of rs2 turned round",
    "fsgnjx": "Puts rs1 in rd with the two signs multiplied together",
    "feq": "Puts 1 in rd when rs1 and rs2 are equal, and 0 when they are not or "
           "either is not a number",
    "flt": "Puts 1 in rd when rs1 is below rs2, and 0 when it is not",
    "fle": "Puts 1 in rd when rs1 is at or below rs2, and 0 when it is not",
    "fclass": "Puts in rd a bit saying what rs1 is: a number, a zero, an infinity "
              "or not a number at all",
}
for _what, _said in OPERATIONS.items():
    for _letter, _format in FORMATS.items():
        OF_INSTRUCTIONS[f"{_what}.{_letter}"] = f"{_said}, in {_format}"
# A conversion always has a floating point number at one end of it or the other:
# turning a whole number into a whole number is not what this unit is for.
for _to, _to_said in NUMBERS.items():
    for _from, _from_said in NUMBERS.items():
        if _to != _from and (_to in FORMATS or _from in FORMATS):
            OF_INSTRUCTIONS[f"fcvt.{_to}.{_from}"] = (
                f"Turns {_from_said} in rs1 into {_to_said} in rd")
OF_INSTRUCTIONS.update({
    "flw": "Reads a single precision number from memory into rd",
    "fld": "Reads a double precision number from memory into rd",
    "fsw": "Writes the single precision number in rs2 to memory",
    "fsd": "Writes the double precision number in rs2 to memory",
    "fmv.x.w": "Copies the bits of a single precision register into an integer one",
    "fmv.w.x": "Copies the bits of an integer register into a single precision one",
    "fmv.x.d": "Copies the bits of a double precision register into an integer one",
    "fmv.d.x": "Copies the bits of an integer register into a double precision one",
})

OF_PSEUDO: dict[str, str] = {
    "li": "Puts a number in rd, however large it is",
    "la": "Puts the address of a label in rd",
    "lla": "Puts the address of a label in rd, counted from this instruction",
    "mv": "Copies one register into another",
    "nop": "Does nothing at all, and takes one instruction to do it",
    "not": "Turns every bit of rs round into rd",
    "neg": "Puts what is left of nothing when rs is taken from it in rd",
    "negw": "The same on the low 32 bits, with the sign spread through rd",
    "seqz": "Puts 1 in rd when rs is zero, and 0 when it is not",
    "snez": "Puts 1 in rd when rs is not zero, and 0 when it is",
    "sltz": "Puts 1 in rd when rs is below zero, and 0 when it is not",
    "sgtz": "Puts 1 in rd when rs is above zero, and 0 when it is not",
    "sgt": "Puts 1 in rd when the first register is above the second, as signed "
           "numbers",
    "sgtu": "Puts 1 in rd when the first register is above the second, as unsigned "
            "numbers",
    "sext.b": "Spreads the sign of the low byte of rs through rd",
    "sext.h": "Spreads the sign of the low two bytes of rs through rd",
    "sext.w": "Spreads the sign of the low word of rs through rd",
    "zext.b": "Keeps the low byte of rs and puts zeroes above it",
    "zext.h": "Keeps the low two bytes of rs and puts zeroes above it",
    "zext.w": "Keeps the low word of rs and puts zeroes above it",
    "beqz": "Goes to the label when rs is zero",
    "bnez": "Goes to the label when rs is not zero",
    "blez": "Goes to the label when rs is at or below zero",
    "bgez": "Goes to the label when rs is at or above zero",
    "bltz": "Goes to the label when rs is below zero",
    "bgtz": "Goes to the label when rs is above zero",
    "bgt": "Goes to the label when the first register is above the second, as signed "
           "numbers",
    "ble": "Goes to the label when the first register is at or below the second, as "
           "signed numbers",
    "bgtu": "Goes to the label when the first register is above the second, as "
            "unsigned numbers",
    "bleu": "Goes to the label when the first register is at or below the second, as "
            "unsigned numbers",
    "b": "Goes to the label, whatever happens",
    "j": "Goes to the label, whatever happens",
    "jr": "Goes to the address in a register",
    "jump": "Goes to a label anywhere in memory, using a register on the way",
    "call": "Calls a label anywhere in memory, leaving the way back in ra",
    "tail": "Goes to a label anywhere in memory without leaving a way back",
    "ret": "Goes back to where the call came from, which ra holds",
    "jal": "Calls a label, leaving the way back in ra unless another register is "
           "named",
    "jalr": "Calls the address in a register, leaving the way back in ra",
    "pause": "Tells the machine that the program is waiting, and nothing more",
    "fence": "Waits for the reads and writes before it to be seen before those after "
             "it",
    "csrr": "Reads a control register into rd",
    "csrw": "Writes rs into a control register",
    "csrs": "Sets in a control register every bit that is set in rs",
    "csrc": "Clears in a control register every bit that is set in rs",
    "csrwi": "Writes a small number into a control register",
    "csrsi": "Sets in a control register the bits of a small number",
    "csrci": "Clears in a control register the bits of a small number",
    "frcsr": "Reads the whole floating point control register into rd",
    "fscsr": "Writes the whole floating point control register",
    "frsr": "Reads the whole floating point control register into rd",
    "fssr": "Writes the whole floating point control register",
    "frrm": "Reads the rounding mode into rd",
    "fsrm": "Writes the rounding mode",
    "frflags": "Reads the flags the floating point unit has raised into rd",
    "fsflags": "Writes the flags of the floating point unit",
    "rdcycle": "Reads the count of cycles into rd",
    "rdcycleh": "Reads the high half of the count of cycles into rd",
    "rdtime": "Reads the clock into rd",
    "rdtimeh": "Reads the high half of the clock into rd",
    "rdinstret": "Reads the count of instructions carried out into rd",
    "rdinstreth": "Reads the high half of the count of instructions into rd",
    "fmv.s": "Copies one single precision register into another",
    "fmv.d": "Copies one double precision register into another",
    "fneg.s": "Copies a single precision register with its sign turned round",
    "fneg.d": "Copies a double precision register with its sign turned round",
    "fabs.s": "Copies a single precision register without its sign",
    "fabs.d": "Copies a double precision register without its sign",
    "fge.s": "Puts 1 in rd when the first is at or above the second, in single "
             "precision",
    "fge.d": "Puts 1 in rd when the first is at or above the second, in double "
             "precision",
    "fgt.s": "Puts 1 in rd when the first is above the second, in single precision",
    "fgt.d": "Puts 1 in rd when the first is above the second, in double precision",
}
# The loads and stores that take a LABEL rather than an offset and a register: the
# assembler works out where the label is and reads or writes there.
for _name, _said in (("lb", "one byte"), ("lbu", "one byte, with zeroes above"),
                     ("lh", "two bytes"), ("lhu", "two bytes, with zeroes above"),
                     ("lw", "a word"), ("lwu", "a word, with zeroes above"),
                     ("ld", "eight bytes"), ("flw", "a single precision number"),
                     ("fld", "a double precision number")):
    OF_PSEUDO[_name] = f"Reads {_said} from a label into rd"
for _name, _said in (("sb", "the low byte"), ("sh", "the low two bytes"),
                     ("sw", "the low word"), ("sd", "the whole"),
                     ("fsw", "the single precision number"),
                     ("fsd", "the double precision number")):
    OF_PSEUDO[_name] = f"Writes {_said} of a register to a label"

OF_DIRECTIVES: dict[str, str] = {
    ".text": "What follows is instructions",
    ".data": "What follows is data the program can read and write",
    ".rodata": "What follows is data the program only reads",
    ".bss": "What follows is room for data that begins as nothing",
    ".section": "What follows belongs to the section named",
    ".globl": "This name can be seen from the other files of the program",
    ".global": "This name can be seen from the other files of the program",
    ".local": "This name is this file's own",
    ".extern": "This name is somewhere else, and this is how much room it takes",
    ".comm": "Room for a name that every file of the program shares",
    ".common": "Room for a name that every file of the program shares",
    ".byte": "Puts single bytes here",
    ".half": "Puts two-byte numbers here",
    ".short": "Puts two-byte numbers here",
    ".2byte": "Puts two-byte numbers here",
    ".word": "Puts four-byte numbers here",
    ".long": "Puts four-byte numbers here",
    ".4byte": "Puts four-byte numbers here",
    ".dword": "Puts eight-byte numbers here",
    ".quad": "Puts eight-byte numbers here",
    ".8byte": "Puts eight-byte numbers here",
    ".float": "Puts single precision numbers here",
    ".double": "Puts double precision numbers here",
    ".ascii": "Puts the characters of a string here",
    ".asciz": "Puts the characters of a string here, and a zero after them",
    ".string": "Puts the characters of a string here, and a zero after them",
    ".space": "Leaves this many bytes empty",
    ".zero": "Leaves this many bytes empty",
    ".align": "Moves on until the address divides by two to this power",
    ".p2align": "Moves on until the address divides by two to this power",
    ".balign": "Moves on until the address divides by this number",
    ".equ": "Gives a name to a number",
    ".eqv": "Gives a name to a piece of text, which is put in wherever the name is "
            "written",
    ".macro": "Begins a piece of program that can be written out wherever it is "
              "called",
    ".end_macro": "Ends a macro",
    ".endm": "Ends a macro",
    ".include": "Reads another file in here, as if it had been written here",
    ".insn": "Puts an instruction here by its bits, or by its parts",
    ".option": "Says how the assembler is to read what follows",
    ".sleb128": "Puts a signed number here in as few bytes as it needs",
    ".uleb128": "Puts an unsigned number here in as few bytes as it needs",
}

# What the convention asks of each register, which is what a program of somebody
# else's will take for granted.
OF_REGISTERS: dict[int, str] = {
    0: "Always zero; writing to it changes nothing",
    1: "Where a call leaves the way back",
    2: "The stack pointer",
    3: "The global pointer",
    4: "The thread pointer",
    8: "Kept across a call; also the frame pointer",
}
for _number in range(5, 8):
    OF_REGISTERS[_number] = "A scratch register; a call may change it"
for _number in range(28, 32):
    OF_REGISTERS[_number] = "A scratch register; a call may change it"
for _number in range(9, 10):
    OF_REGISTERS[_number] = "Kept across a call"
for _number in range(18, 28):
    OF_REGISTERS[_number] = "Kept across a call"
for _number in range(10, 12):
    OF_REGISTERS[_number] = "An argument to a call, and where it leaves its answer"
for _number in range(12, 18):
    OF_REGISTERS[_number] = "An argument to a call; a call may change it"


# The floating point registers have a convention of their own, the same shape as
# the one the integer registers keep.
OF_FLOATS: dict[int, str] = {}
for _number in range(0, 8):
    OF_FLOATS[_number] = "A scratch register; a call may change it"
for _number in range(8, 10):
    OF_FLOATS[_number] = "Kept across a call"
for _number in range(10, 12):
    OF_FLOATS[_number] = "An argument to a call, and where it leaves its answer"
for _number in range(12, 18):
    OF_FLOATS[_number] = "An argument to a call; a call may change it"
for _number in range(18, 28):
    OF_FLOATS[_number] = "Kept across a call"
for _number in range(28, 32):
    OF_FLOATS[_number] = "A scratch register; a call may change it"

# What the machine keeps in each of the registers it keeps about itself.
OF_CONTROL: dict[str, str] = {
    "fcsr": "The whole floating point control register: the flags and the rounding "
            "mode together",
    "fflags": "The flags the floating point unit has raised",
    "frm": "How the floating point unit rounds",
    "cycle": "How many cycles the machine has taken",
    "cycleh": "The high half of the count of cycles",
    "time": "The clock, counted in the same steps for every program",
    "timeh": "The high half of the clock",
    "instret": "How many instructions have been carried out",
    "instreth": "The high half of the count of instructions",
    "ustatus": "Whether interrupts are allowed, and whether they were before the "
               "last one",
    "uie": "Which interrupts the program is willing to hear",
    "uip": "Which interrupts are waiting to be heard",
    "utvec": "Where the machine goes when an interrupt or a trap happens",
    "uscratch": "A register of the program's own, for a handler to keep something in",
    "uepc": "Where the program was when the interrupt or the trap happened",
    "ucause": "What the interrupt or the trap was",
    "utval": "What the trap was about: an address, or the instruction itself",
}


# What can be settled about a RUN: what each model and each device IS, and what
# each option of it does. `session/settings.py` says what the options ARE - it
# reads them off the models themselves - and this says what they MEAN; a test holds
# the two together, so an option added to a model is owed a line here the same day.
OF_SETTINGS: dict[str, str] = {
    "statistics": "Whether the run is counted: the instructions by kind, the "
                  "traps, and how many branches went and how many did not",
    "cache": "A model of a cache between the machine and the memory. It changes "
             "nothing a program sees: it counts what would have been a hit and "
             "what a miss, and shows what the cache would be holding",
    "cache.block_bytes": "How many bytes one block holds, which is how much of "
                         "memory comes in on a miss",
    "cache.sets": "How many sets of blocks the cache is divided into; the address "
                  "of a word says which set it belongs in",
    "cache.ways": "How many blocks one set holds: one way is a direct cache, and "
                  "one set of many ways is a fully associative one",
    "cache.replacement": "Which block of a full set makes room: the one longest "
                         "unused, the one longest in, or one by chance",
    "cache.write_back": "Whether a block written to waits in the cache and goes to "
                        "memory when it is thrown out, instead of going at once",
    "cache.write_allocate": "Whether a write that misses brings its block into the "
                            "cache first, instead of going straight to memory",
    "fetches": "Whether the addresses of the INSTRUCTIONS reach that one cache as "
               "well as the data - which is what a machine with one cache for "
               "everything does. RARS never shows its cache a fetch",
    "instructions": "A cache of its own for the instructions, beside the one of "
                    "the data, which is what a machine with two of them has",
    "pipeline": "A model of the time a run would have taken on a machine of five "
                "stages. It changes nothing a program sees: it counts the cycles, "
                "what was waited for and what was guessed wrongly",
    "pipeline.forwarding": "Whether a result may be used by the instruction behind "
                           "it before it has been written back, instead of waiting",
    "pipeline.one_port": "Whether fetching an instruction and reaching into memory "
                         "share one way to it, so that one of the two must wait",
    "pipeline.penalty": "How many cycles are thrown away when a branch was guessed "
                        "wrongly",
    "pipeline.trap_penalty": "How many cycles are thrown away by an instruction "
                             "that could not be carried out",
    "pipeline.diagram": "How many instructions to keep the diagram of - the cycle "
                        "each of the five stages began in. None keeps none",
    "guesser": "How the machine of the model guesses which way a branch goes "
               "before it can know",
    "guesser.predictor": "Never expect a branch to be taken, always expect it, or "
                         "keep a table of what each branch did last time",
    "guesser.entries": "How many entries that table holds; a branch falls into one "
                       "of them by its address",
    "guesser.bits": "How many bits one counter of the table holds: one bit "
                    "remembers the last time, two need two surprises to change "
                    "their mind",
    "guesser.taken": "Whether every counter of the table begins by expecting a "
                     "branch to be taken",
    "keyboard": "The keyboard and display of RARS: four registers of MMIO through "
                "which a program reads the keys typed and shows characters one at "
                "a time",
    "keyboard.delay": "How many instructions the display takes over one character "
                      "before it will take another",
    "keyboard.technique": "How that delay is counted: exactly, evenly by chance up "
                          "to it, or around it by chance",
    "keyboard.rows": "How many rows of characters the display holds",
    "keyboard.columns": "How many characters a row of the display holds",
    "keyboard.show_after_delay": "Whether a character appears when its delay is "
                                 "over, as in RARS, rather than the moment it is "
                                 "written",
    "keyboard.queue": "How many keys typed the keyboard holds at once. One is what "
                      "RARS keeps, and a key is lost if the program did not read "
                      "the one before it",
    "lab": "The digital lab of RARS: two seven-segment displays, a keyboard of "
           "sixteen keys that stay down, and a counter that asks for attention "
           "again and again",
    "timer": "A clock a program can read, and a time at which it asks to be told",
    "timer.mode": "Whether the clock follows the wall or counts in instructions "
                  "carried out - which makes a run repeatable",
    "timer.step": "How many milliseconds one instruction is worth, where the clock "
                  "counts in instructions",
    "bitmap": "A piece of memory seen as a picture: one word is one unit of it, "
              "and the low 24 bits of that word are its red, green and blue",
    "bitmap.place": "Where in memory the picture lies: the base of the data "
                    "segment, the global pointer, the data of the program, the "
                    "heap, or the area of the devices",
    "bitmap.width": "How wide the whole picture is, in pixels",
    "bitmap.height": "How tall the whole picture is, in pixels",
    "bitmap.unit_width": "How wide one unit of the picture is, in pixels; the "
                         "picture holds as many units across as it has room for",
    "bitmap.unit_height": "How tall one unit of the picture is, in pixels",
    "disk": "Storage a program talks to a block at a time: it says which block, "
            "where in memory and how many, and then waits for the work or asks to "
            "be told when it ends",
    "disk.blocks": "How many blocks the disk holds",
    "disk.block_size": "How many bytes one block of it holds",
    "disk.delay": "How many instructions carrying one block over takes",
    "dma": "A controller that copies memory while the program runs on, and says "
           "when it has finished",
    "dma.speed": "How many words it copies for every instruction the machine "
                 "carries out",
    "halt": "A register a program writes to to say that it is finished and how it "
            "went, without asking anything of the environment",
}


def of_a_setting(name: str) -> str:
    """What one thing of a run means, by its own name or `thing.option`."""
    return OF_SETTINGS.get(name, "")


def of_an_instruction(mnemonic: str) -> str:
    return OF_INSTRUCTIONS.get(mnemonic, "")


def of_a_pseudo(mnemonic: str) -> str:
    return OF_PSEUDO.get(mnemonic, "")


def of_a_directive(name: str) -> str:
    return OF_DIRECTIVES.get(name, "")


def of_a_register(number: int) -> str:
    return OF_REGISTERS.get(number, "")


def of_a_float(number: int) -> str:
    return OF_FLOATS.get(number, "")


def of_a_control(name: str) -> str:
    return OF_CONTROL.get(name, "")


def missing() -> dict[str, tuple[str, ...]]:
    """What the assembler takes and this table says nothing about.

    The test of this module asks for it to be empty. It is a method rather than a
    test of its own so that anybody can ask it - the day somebody adds an
    instruction, this says what is owed.
    """
    return {
        "instructions": tuple(one.mnemonic for one in instructions(64)
                              if not of_an_instruction(one.mnemonic)),
        "pseudo-instructions": tuple(sorted(
            one for one in pseudo.mnemonics(64) if not of_a_pseudo(one))),
        "directives": tuple(sorted(one for one in DIRECTIVES
                                   if not of_a_directive(one))),
        "registers": tuple(f"x{number}" for number in range(len(X_NAMES))
                           if not of_a_register(number)),
        "floating point registers": tuple(
            f"f{number}" for number in range(32) if not of_a_float(number)),
        "control registers": tuple(sorted(one for one in CSRS
                                          if not of_a_control(one))),
        "settings of a run": _settings_without_a_word(),
    }


def _settings_without_a_word() -> tuple[str, ...]:
    """What can be settled about a run and has no word about it here.

    What CAN be settled is `session/settings.py`, which reads it off the models
    and the devices themselves - so a model that gains an option, or a device
    added to the registry, is owed a line here at once.
    """
    owed = [name for name in ("statistics", "fetches", "instructions")
            if not of_a_setting(name)]
    for what in ("cache", "pipeline", "guesser", *DEVICES):
        if not of_a_setting(what):
            owed.append(what)
        owed += [f"{what}.{one.name}" for one in options_of(what)
                 if not of_a_setting(f"{what}.{one.name}")]
    return tuple(owed)
