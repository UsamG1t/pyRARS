"""The packages themselves: the version of Python, and the rule of the layers.

INV-L1 and INV-L2 of the architecture spec say which package may import which:

    L4  pyrars.ui          (GTK)            -> L3
    L3  pyrars.session     (facade)         -> L2, L1, L0
    L2  pyrars.devices, pyrars.analysis     -> L1, L0
    L1  pyrars.asm, pyrars.core             -> L0
    L0  pyrars.isa, pyrars.softfloat        -> stdlib only
    aux pyrars.cli, pyrars.console          -> L3 (headless)

`pyrars.core` MUST NOT import the assembler: it consumes the plain data of
`pyrars.isa.program`. Nothing except `pyrars.ui` may import GTK, so that
everything below it runs without a window system. The test reads the imports of
every module instead of trusting the reviewer.
"""

import ast
import sys
from pathlib import Path

SOURCE = Path(__file__).parents[2] / "src" / "pyrars"

# package -> the packages of pyrars it may import (itself included)
ALLOWED = {
    "isa": {"isa"},
    "softfloat": {"softfloat"},
    "asm": {"asm", "isa", "softfloat"},
    "core": {"core", "isa", "softfloat"},
    "devices": {"devices", "core", "asm", "isa", "softfloat"},
    "analysis": {"analysis", "core", "asm", "isa", "softfloat"},
    "session": {"session", "devices", "analysis", "core", "asm", "isa", "softfloat"},
    "ui": {"ui", "session", "devices", "analysis", "core", "asm", "isa", "softfloat"},
    "cli": {"cli", "console", "session", "devices", "analysis", "core", "asm", "isa",
            "softfloat"},
}


def test_python_version():
    assert sys.version_info >= (3, 14)


def test_packages_import():
    import pyrars
    import pyrars.asm
    import pyrars.core
    import pyrars.devices
    import pyrars.isa
    import pyrars.softfloat


def imports_of(path: Path) -> set[str]:
    """The modules a file imports, by their full names."""
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {name.name for name in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
    return found


def test_a_package_imports_only_what_its_layer_allows():
    for path in sorted(SOURCE.rglob("*.py")):
        inside = path.relative_to(SOURCE).parts
        package = inside[0] if len(inside) > 1 else "cli"  # cli.py, __main__.py
        allowed = ALLOWED[package]
        for name in imports_of(path):
            parts = name.split(".")
            if parts[0] != "pyrars":
                continue
            assert parts[1] in allowed, f"{path.name} of {package} imports {name}"


def test_nothing_but_the_interface_imports_gtk():
    for path in sorted(SOURCE.rglob("*.py")):
        if path.relative_to(SOURCE).parts[0] == "ui":
            continue
        assert "gi" not in {name.split(".")[0] for name in imports_of(path)}, path
