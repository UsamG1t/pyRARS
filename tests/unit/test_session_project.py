"""What a program is: the project file, read, written and moved.

RARS has nothing to compare this with: its own project is a window with files open
in it, remembered nowhere. So every expected value here is worked out from what a
project MEANS - the main file is assembled first, the paths are relative to the
folder the project file lies in, and what a project settles the command line may
not settle again.

A project says nothing about how to run a program; that is M8's (the architect's
decision of 2026-10-13, variant A), and a test here holds the line.
"""

import json

import pytest

from pyrars.asm.assembler import Options
from pyrars.isa.memory import CONFIGS
from pyrars.session import project as projects
from pyrars.session.project import SETTINGS, Project


def written(folder, name: str, held: dict) -> str:
    path = folder / name
    path.write_text(json.dumps(held))
    return str(path)


def files(folder) -> None:
    (folder / "main.s").write_text(".globl main\n.text\nmain: li a7, 93\n ecall\n")
    (folder / "lib.s").write_text(".globl helper\n.text\nhelper: ret\n")


# ------------------------------------------------------------------ the shape


def test_a_project_of_nothing_is_a_project():
    """A window opens with no files in it, and that is a project all the same."""
    empty = Project()
    assert (empty.files, empty.main, empty.paths) == ((), "", ())
    assert (empty.xlen, empty.mem_config, empty.pseudo) == (32, "Default", True)


def test_the_main_file_is_assembled_first():
    one = Project(files=("lib.s", "main.s"), main="main.s")
    assert one.ordered == ("main.s", "lib.s")
    assert one.files == ("lib.s", "main.s")  # and the project keeps its own order


def test_without_a_main_file_the_order_is_the_order():
    assert Project(files=("lib.s", "main.s")).ordered == ("lib.s", "main.s")


def test_the_files_are_found_beside_the_project(tmp_path):
    one = Project(files=("lib.s", "deeper/main.s"), main="deeper/main.s",
                  folder=str(tmp_path))
    assert one.paths == (f"{tmp_path}/deeper/main.s", f"{tmp_path}/lib.s")


def test_an_absolute_path_stays_where_it_is(tmp_path):
    one = Project(files=("/elsewhere/lib.s", "main.s"), folder=str(tmp_path))
    assert one.paths == ("/elsewhere/lib.s", f"{tmp_path}/main.s")


def test_a_project_with_no_folder_hands_its_files_over_as_they_are():
    assert Project(files=("main.s",)).paths == ("main.s",)


def test_what_a_project_settles_for_the_assembler():
    one = Project(files=("main.s",), xlen=64, mem_config="CompactDataAtZero",
                  pseudo=False)
    assert one.options() == Options(xlen=64, config=CONFIGS["CompactDataAtZero"],
                                   pseudo=False)


def test_what_a_project_leaves_to_the_person():
    """Whether a warning is an error and whether a run begins at `main` are choices
    of the moment, not of the program, so a project says nothing of them - as it
    says nothing of the devices, the models or anything else about a RUN."""
    settled = one_of_everything().options()
    assert settled.warnings_are_errors is False
    assert settled.start_at_main is False
    assert not set(SETTINGS) & {"devices", "settings", "breakpoints", "speed"}


def one_of_everything() -> Project:
    return Project(files=("lib.s", "main.s"), main="main.s", xlen=64,
                   mem_config="CompactTextAtZero", pseudo=False)


# ------------------------------------------------------------- what is refused


def test_a_machine_is_of_two_widths():
    with pytest.raises(ValueError, match="16: a machine is 32 or 64 bits wide"):
        Project(xlen=16)


def test_a_memory_configuration_nobody_has():
    with pytest.raises(ValueError, match="no memory configuration of that name"):
        Project(mem_config="Roomy")


def test_a_main_file_that_is_not_one_of_the_files():
    with pytest.raises(ValueError, match="the main file is not one of the files"):
        Project(files=("main.s",), main="other.s")


def test_a_file_held_twice():
    """Two of one file would be assembled twice, and every label of it would clash
    with itself."""
    with pytest.raises(ValueError, match='"main.s": a project holds a file once'):
        Project(files=("main.s", "lib.s", "main.s"))


# ----------------------------------------------------------- reading a project


def test_a_project_read_from_its_file(tmp_path):
    path = written(tmp_path, "thing.pyrars.json",
                   {"files": ["lib.s", "main.s"], "main": "main.s", "xlen": 64,
                    "mem_config": "CompactDataAtZero", "pseudo": False})
    one = projects.read(path)
    assert one.files == ("lib.s", "main.s")
    assert (one.main, one.xlen, one.mem_config, one.pseudo) == (
        "main.s", 64, "CompactDataAtZero", False)
    assert one.folder == str(tmp_path)
    assert one.paths == (f"{tmp_path}/main.s", f"{tmp_path}/lib.s")


def test_a_project_that_says_only_what_it_must(tmp_path):
    path = written(tmp_path, "thing.pyrars.json", {"files": ["main.s"]})
    one = projects.read(path)
    assert (one.main, one.xlen, one.mem_config, one.pseudo) == ("", 32, "Default", True)


def test_a_setting_a_project_has_not_got(tmp_path):
    path = written(tmp_path, "thing.pyrars.json", {"files": [], "colour": "red"})
    with pytest.raises(ValueError, match='"colour" is no setting of a project; they '
                                         "are files, main, xlen, mem_config, pseudo"):
        projects.read(path)


def test_a_project_file_that_is_no_project(tmp_path):
    path = tmp_path / "thing.pyrars.json"
    path.write_text("[1, 2, 3]")
    with pytest.raises(ValueError, match="a project is a JSON object holding"):
        projects.read(str(path))


def test_a_project_file_that_is_not_even_json(tmp_path):
    path = tmp_path / "thing.pyrars.json"
    path.write_text("{files: [\n")
    with pytest.raises(ValueError, match="line 1"):
        projects.read(str(path))


def test_a_project_file_that_is_not_there(tmp_path):
    with pytest.raises(ValueError, match="No such file"):
        projects.read(str(tmp_path / "nothing.pyrars.json"))


@pytest.mark.parametrize("held, says", [
    ({"files": "main.s"}, "the files of a project are a list of names"),
    ({"files": [1, 2]}, "the files of a project are a list of names"),
    ({"main": 1}, '"main" of a project is a name'),
    ({"xlen": "32"}, '"xlen" of a project is a whole number'),
    ({"xlen": True}, '"xlen" of a project is a whole number'),
    ({"mem_config": 1}, '"mem_config" of a project is a name'),
    ({"pseudo": "yes"}, '"pseudo" of a project is true or false'),
    ({"pseudo": 1}, '"pseudo" of a project is true or false'),
])
def test_a_setting_of_the_wrong_kind(tmp_path, held, says):
    path = written(tmp_path, "thing.pyrars.json", held)
    with pytest.raises(ValueError, match=says):
        projects.read(path)


def test_what_a_project_says_wrongly_is_said_with_the_file_it_is_in(tmp_path):
    path = written(tmp_path, "thing.pyrars.json", {"xlen": 16})
    with pytest.raises(ValueError, match=r"thing\.pyrars\.json: 16: a machine is"):
        projects.read(path)


# ----------------------------------------------------------- writing a project


def test_a_project_written_and_read_back(tmp_path):
    files(tmp_path)
    one = projects.of([str(tmp_path / "lib.s"), str(tmp_path / "main.s")],
                      folder=str(tmp_path), main=str(tmp_path / "main.s"), xlen=64)
    assert one.files == ("lib.s", "main.s")  # put relative to the folder
    path = str(tmp_path / "thing.pyrars.json")
    one.save(path)
    assert projects.read(path) == one


def test_what_a_project_file_holds(tmp_path):
    one = Project(files=("lib.s", "main.s"), main="main.s", folder=str(tmp_path))
    held = json.loads(one.written())
    assert list(held) == list(SETTINGS)  # every setting, in one order
    assert held == {"files": ["lib.s", "main.s"], "main": "main.s", "xlen": 32,
                    "mem_config": "Default", "pseudo": True}
    assert one.written().endswith("\n")
    assert "folder" not in held  # where it lies is not a setting of it


def test_a_project_saved_somewhere_else_keeps_its_files(tmp_path):
    """The paths are put right for the new folder, so a project that is moved does
    not lose the files it is made of."""
    files(tmp_path)
    one = projects.of([str(tmp_path / "main.s")], folder=str(tmp_path))
    deeper = tmp_path / "deeper"
    deeper.mkdir()
    moved = one.save(str(deeper / "thing.pyrars.json"))
    assert moved.files == ("../main.s",)
    assert moved.paths == one.paths  # the same files, from the new place
    assert projects.read(str(deeper / "thing.pyrars.json")) == moved


def test_a_project_over_other_files(tmp_path):
    one = Project(xlen=64, folder=str(tmp_path))
    other = one.with_files([str(tmp_path / "a.s"), str(tmp_path / "b.s")],
                           main=str(tmp_path / "b.s"))
    assert other.files == ("a.s", "b.s")
    assert other.main == "b.s"
    assert other.xlen == 64  # and everything else is as it was
