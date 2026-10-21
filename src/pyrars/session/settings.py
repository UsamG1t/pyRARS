"""How a program is RUN, as against what the program IS.

A project (`session/project.py`) says what the program is: the files it is made
of, the width of the machine, the memory configuration. These are the other half -
what the machine is given BESIDES the program: which devices are attached, whether
the run is counted, whether a cache and a pipeline are modelled, and how each of
them is built. The two are kept apart because a project outlives any one run of it
(the architect's decision of 2026-10-13, variant A), and because a project is a
thing to be sent to somebody else while these are nobody's business but the
person's who set them.

So they are kept where a desktop keeps what belongs to a person:
`$XDG_CONFIG_HOME/pyrars/run.json`, or `~/.config/pyrars/run.json` where nothing
says otherwise. A file that is not there is not a fault: it means the defaults,
which are what somebody who has never opened the settings gets.

Nothing here IS a model. What is held here are the words to build one from, in the
shape a JSON file holds them - a name to a value - and `world()` is the one place
that builds the models out of them, so that a window and anything else that drives
a session ask for them in the same way and are told in the same words when what
was asked for cannot be built.

What a person is OFFERED is worked out from the models themselves (`options_of`),
not written down a second time: a cache that gains an option gains it here, and
the few that nobody would set in a window are named in `LEFT_OUT` with the reason.
"""

import inspect
import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path

from pyrars.analysis import predictors
from pyrars.analysis.cache import REPLACEMENTS, Caches
from pyrars.analysis.cache import Settings as CacheSettings
from pyrars.analysis.pipeline import Pipeline
from pyrars.analysis.pipeline import Settings as PipelineSettings
from pyrars.devices import DEVICES, DeviceBus, make
from pyrars.devices.bitmap import PLACES
from pyrars.devices.keyboard import TECHNIQUES
from pyrars.devices.timer import MODES

# What a settings file may hold, which is also the order it is written in.
KEPT = ("statistics", "cache", "fetches", "instructions", "pipeline", "guesser",
        "devices")

# What kind of value an option takes, which is all a window needs to know to ask
# for it: a number, a yes or no, one of a few words, or words of one's own.
WHOLE = "whole"
YES_OR_NO = "yes or no"
AMONG = "among"
TEXT = "text"

# The options a person is NOT offered, and why.
LEFT_OUT = {
    # How the ANALYSIS is kept, not how the cache is built: a seed for the
    # replacement by chance (a window has no use for a repeatable one), and how
    # much of the log and the time series to keep, which nothing on the screen
    # reads.
    "cache": ("seed", "log", "sample"),
    # How long each KIND of instruction holds the EX stage. It is a table in
    # itself, one row per kind of instruction, and not a setting beside the
    # others; a window that wanted it would want a table of its own for it.
    "pipeline": ("latency",),
    # An image of bytes. A window gives a disk a FILE, which is not a setting of
    # the device but a thing of the world outside it.
    "disk": ("image",),
}

# The words a string option may take, where it may take only a few. Anything not
# named here is text of one's own.
CHOICES = {
    "replacement": REPLACEMENTS,
    "predictor": ("never", "always", "table"),
    "technique": TECHNIQUES,
    "mode": MODES,
    "place": tuple(PLACES),
}

# How a branch is guessed at, where nobody says: never taken, which is what a
# machine without a table of history does.
GUESSER = {"predictor": "never", "entries": 16, "bits": 1, "taken": False}


@dataclass(frozen=True, slots=True)
class Option:
    """One thing that can be set: its name, what kind of value it takes, what it
    is when nobody says, and the words it may be where it may be only a few."""

    name: str
    kind: str
    default: object
    among: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Settings:
    """What a run is given besides the program.

    Each model is either nothing at all - it is not wanted - or what was asked of
    it by name. Nothing is checked here: what checks it is the model itself, and
    `world()` is where it is built and where it says what is wrong.
    """

    statistics: bool = True  # counting a run costs one comparison a turn
    cache: dict | None = None  # the cache of the data, or the one cache
    fetches: bool = False  # whether the one cache sees the instructions as well
    instructions: dict | None = None  # a cache of the instructions beside it
    pipeline: dict | None = None
    guesser: dict | None = None  # how the pipeline guesses where a branch goes
    devices: dict = field(default_factory=dict)  # by name, each with what it was asked

    def written(self) -> str:
        """The settings as a settings file holds them."""
        held = {name: getattr(self, name) for name in KEPT}
        return json.dumps(held, indent=2) + "\n"


# ---------------------------------------------------------------- what is offered


def options_of(what: str) -> tuple[Option, ...]:
    """What can be set about a cache, a pipeline, a guesser or a device of a name.

    It is read off the model itself - the fields of its settings, or the arguments
    it is built with - so that nothing here has to be kept in step by hand.
    """
    if what == "cache":
        return _of_a_dataclass(CacheSettings, LEFT_OUT["cache"])
    if what == "pipeline":
        return _of_a_dataclass(PipelineSettings, LEFT_OUT["pipeline"])
    if what == "guesser":
        return tuple(_option(name, value) for name, value in GUESSER.items())
    if what in DEVICES:
        return _of_a_device(what)
    raise ValueError(f'"{what}": nothing of a run is called that')


def _of_a_dataclass(which, left_out: tuple[str, ...]) -> tuple[Option, ...]:
    return tuple(_option(one.name, one.default) for one in fields(which)
                 if one.name not in left_out)


def _of_a_device(name: str) -> tuple[Option, ...]:
    left_out = LEFT_OUT.get(name, ())
    taken = inspect.signature(DEVICES[name]).parameters
    # Only what has a default can be offered: a window has nothing to put in a row
    # for an argument whose value it cannot guess.
    return tuple(_option(one.name, one.default) for one in taken.values()
                 if one.name not in left_out
                 and one.default is not inspect.Parameter.empty)


def _option(name: str, default: object) -> Option:
    """One option, with the kind of value it takes worked out from what it is when
    nobody says. A `None` is a number nobody has chosen, which is what a cache
    means by a seed and a device by an image."""
    if isinstance(default, bool):  # before the number: a bool IS one in Python
        return Option(name, YES_OR_NO, default)
    if isinstance(default, int):
        return Option(name, WHOLE, default)
    if name in CHOICES:
        return Option(name, AMONG, default, tuple(CHOICES[name]))
    return Option(name, TEXT, "" if default is None else default)


# --------------------------------------------------------- what is built from them


def world(settings: Settings) -> dict:
    """What a session is built with, as its own keyword arguments.

    Raises ValueError with ONE sentence, for a window to show and a command line to
    print: everything that can be wrong here is something a person asked for and
    can be told about.
    """
    caches, fetches = _caches(settings)
    return {"statistics": settings.statistics, "caches": caches, "fetches": fetches,
            "pipeline": _pipeline(settings), "bus": _bus(settings)}


def _caches(settings: Settings):
    """The caches of the run, and whether the addresses of the instructions reach
    one. A cache FOR EVERYTHING and a cache of the data are the same object, and
    only whoever asked knows which was meant."""
    if settings.cache is None and settings.instructions is None:
        return None, False
    if settings.fetches and settings.instructions is not None:
        raise ValueError("a cache for everything and a cache of the instructions "
                         "cannot both be asked for")
    data = _built(CacheSettings, settings.cache or {}, "the cache of the data")
    if settings.instructions is None:
        return Caches(data=data), settings.fetches
    return (Caches(data=data,
                   instructions=_built(CacheSettings, settings.instructions,
                                       "the cache of the instructions")), True)


def _pipeline(settings: Settings) -> Pipeline | None:
    if settings.pipeline is None:
        return None
    return Pipeline(_built(PipelineSettings, settings.pipeline, "the pipeline"),
                    guesser(settings.guesser))


def guesser(asked: dict | None):
    """How the machine of the model guesses where a branch goes."""
    wanted = {**GUESSER, **(asked or {})}
    which = wanted.pop("predictor")
    if which in ("never", "always"):
        return predictors.Static(which == "always")
    if which != "table":
        raise ValueError(f'"{which}": a branch is guessed at by never, always or '
                         "table")
    try:
        return predictors.History(**wanted)
    except TypeError as problem:
        raise ValueError(f"the guesser: {problem}") from None


def _bus(settings: Settings) -> DeviceBus | None:
    """The devices attached to the run. A device is built with what was asked of it
    and nothing else: what it needs of the world outside - the keys somebody types,
    the file a disk holds - is given to it afterwards by whoever has one."""
    if not settings.devices:
        return None
    bus = DeviceBus()
    for name, asked in settings.devices.items():
        if name not in DEVICES:
            raise ValueError(f'"{name}": no device of that name (known: '
                             f'{", ".join(sorted(DEVICES))})')
        left_out = LEFT_OUT.get(name, ())
        try:
            bus.add(make(name, **{option: value for option, value in asked.items()
                                  if option not in left_out}))
        except TypeError as problem:
            raise ValueError(f"the {name}: {problem}") from None
    return bus


def _built(which, asked: dict, called: str):
    """The settings of a model from what was asked of it, with the name of the
    model put in front of whatever it says is wrong."""
    try:
        return which(**asked)
    except (TypeError, ValueError) as problem:
        raise ValueError(f"{called}: {problem}") from None


# -------------------------------------------------------------- where they are kept


def path() -> str:
    """The file the settings of a run are kept in."""
    folder = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return str(Path(folder) / "pyrars" / "run.json")


def read(where: str = "") -> Settings:
    """The settings as they were last kept. A file that is not there means the
    defaults; one that cannot be understood raises ValueError, because a person who
    wrote it by hand wants to know."""
    file = Path(where or path())
    if not file.exists():
        return Settings()
    try:
        held = json.loads(file.read_text())
    except OSError as problem:
        raise ValueError(f"{file}: {problem.strerror or problem}") from None
    except json.JSONDecodeError as problem:
        raise ValueError(f"{file}: {problem.msg}, line {problem.lineno}") from None
    if not isinstance(held, dict):
        raise ValueError(f"{file}: the settings of a run are a JSON object holding "
                         f"{', '.join(KEPT)}")
    for name in held:
        if name not in KEPT:
            raise ValueError(f'{file}: "{name}" is no setting of a run; they are '
                             f'{", ".join(KEPT)}')
    try:
        return Settings(**_checked(held))
    except (TypeError, ValueError) as problem:
        raise ValueError(f"{file}: {problem}") from None


def _checked(held: dict) -> dict:
    """What a settings file holds, said to be of the right shape. A person who
    wrote one by hand is told what the setting IS rather than left to find out
    from a model later on."""
    for name in ("statistics", "fetches"):
        if name in held and not isinstance(held[name], bool):
            raise ValueError(f'"{name}" of a run is true or false')
    for name in ("cache", "instructions", "pipeline", "guesser"):
        if held.get(name) is not None and not isinstance(held[name], dict):
            raise ValueError(f'"{name}" of a run is what was asked of it by name, '
                             "or null where it is not wanted")
    devices = held.get("devices", {})
    if not isinstance(devices, dict) or any(not isinstance(one, dict)
                                            for one in devices.values()):
        raise ValueError('"devices" of a run is every device by name, each with '
                         "what was asked of it")
    return held


def save(settings: Settings, where: str = "") -> str:
    """Write the settings, and answer with the file they are in. The folder is made
    where it is not there yet: a desktop does not promise one."""
    file = Path(where or path())
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(settings.written())
    return str(file)
