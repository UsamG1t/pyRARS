import sys


def test_python_version():
    assert sys.version_info >= (3, 14)


def test_packages_import():
    import pyrars
    import pyrars.asm
    import pyrars.isa
