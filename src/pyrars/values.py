"""How a value of the machine is written down.

Both front ends write the same values the same way - the console debugger of
`pyrars.console` and the window of `pyrars.ui` - so the three shapes they are
written in live here, where either may have them and neither owns them. It is a
leaf: it imports nothing of ours at all.
"""

VALUE_FORMATS = ("hex", "dec", "ascii")


def value_text(value: int, bits: int, form: str) -> str:
    """One value of `bits` bits, as the chosen format writes it. A register of a
    64-bit machine therefore shows sixteen hexadecimal digits, where RARS prints
    the low eight of any register (DEV-47); a word of memory is four bytes in both
    widths."""
    if form == "hex":
        return f"0x{value:0{bits // 4}x}"
    if form == "dec":
        return str(value - (1 << bits) if value >> (bits - 1) else value)
    return ascii_text(value, bits // 8)


def ascii_text(value: int, width: int) -> str:
    """The bytes of a value as characters, the highest first, each in three columns
    and an unprintable one as a full stop - the way RARS writes them."""
    letters = []
    for index in reversed(range(width)):
        byte = (value >> (8 * index)) & 0xFF
        letters.append(f"{chr(byte) if 32 <= byte < 127 else '.':>3}")
    return "".join(letters)
