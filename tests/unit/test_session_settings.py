"""How a program is RUN: what is settled, what is built from it, and where it is kept.

There is nothing of RARS to compare here - its settings live in a Java preferences
store and its models are not ours - so every expected value is worked out from what
the module PROMISES: the defaults model nothing but the counting, what is offered
is read off the models themselves, and everything that cannot be built says so in
one sentence somebody can read.
"""

import json
from dataclasses import fields
from pathlib import Path

import pytest

from pyrars.analysis import predictors
from pyrars.analysis.cache import Settings as CacheSettings
from pyrars.analysis.pipeline import Settings as PipelineSettings
from pyrars.devices import DEVICES
from pyrars.session import settings as runs


# ------------------------------------------------------------ what is built


def test_a_run_nobody_has_settled_models_nothing_but_the_counting():
    """Counting a run costs one comparison a turn and is what the window's own
    line of numbers is made of; a cache, a pipeline and a device are each asked
    for."""
    built = runs.world(runs.Settings())
    assert built == {"statistics": True, "caches": None, "fetches": False,
                     "pipeline": None, "bus": None}


def test_a_cache_of_the_data():
    built = runs.world(runs.Settings(cache={"sets": 4, "ways": 2}))
    assert built["caches"].data.settings == CacheSettings(sets=4, ways=2)
    assert built["caches"].instructions is None
    assert built["fetches"] is False  # the addresses of the instructions miss it


def test_a_cache_for_everything():
    """One cache that the instructions reach as well: the same object, and only
    whoever asked knows which was meant."""
    built = runs.world(runs.Settings(cache={}, fetches=True))
    assert built["caches"].split is False
    assert built["fetches"] is True


def test_a_cache_of_the_instructions_beside_one_of_the_data():
    built = runs.world(runs.Settings(cache={"sets": 4},
                                     instructions={"sets": 2}))
    assert built["caches"].data.settings.sets == 4
    assert built["caches"].instructions.settings.sets == 2
    assert built["caches"].split and built["fetches"] is True


def test_a_cache_of_the_instructions_alone_leaves_the_data_one_as_it_comes():
    built = runs.world(runs.Settings(instructions={"sets": 2}))
    assert built["caches"].data.settings == CacheSettings()
    assert built["caches"].instructions.settings.sets == 2


def test_a_cache_for_everything_and_one_of_the_instructions_is_two_answers():
    with pytest.raises(ValueError, match="cannot both be asked for"):
        runs.world(runs.Settings(cache={}, fetches=True, instructions={}))


def test_a_cache_asked_for_what_a_cache_has_not_got():
    with pytest.raises(ValueError, match="the cache of the data: .*nonsense"):
        runs.world(runs.Settings(cache={"nonsense": 1}))
    with pytest.raises(ValueError, match="the cache of the instructions: "):
        runs.world(runs.Settings(instructions={"nonsense": 1}))


def test_a_cache_that_cannot_be_built_says_what_the_model_says():
    """The model's own words, because the model is what knows: a cache reads the
    number of its sets off the bits of an address."""
    with pytest.raises(ValueError, match="power of two"):
        runs.world(runs.Settings(cache={"sets": 3}))


def test_a_pipeline_and_the_guesser_it_comes_with():
    built = runs.world(runs.Settings(pipeline={"forwarding": False}))
    assert built["pipeline"].settings == PipelineSettings(forwarding=False)
    # without a word about it, a machine never expects a branch to be taken
    assert isinstance(built["pipeline"].predictor, predictors.Static)
    assert built["pipeline"].predictor.name == predictors.Static(False).name


def test_a_pipeline_that_guesses_with_a_table_of_history():
    built = runs.world(runs.Settings(pipeline={},
                                     guesser={"predictor": "table", "bits": 2}))
    guesser = built["pipeline"].predictor
    assert isinstance(guesser, predictors.History)
    assert (guesser.entries, guesser.bits) == (16, 2)  # the entries as they come


def test_a_pipeline_that_always_expects_a_branch_to_be_taken():
    built = runs.world(runs.Settings(pipeline={}, guesser={"predictor": "always"}))
    assert built["pipeline"].predictor.name == predictors.Static(True).name


def test_a_guesser_nobody_has():
    with pytest.raises(ValueError, match="never, always or table"):
        runs.world(runs.Settings(pipeline={}, guesser={"predictor": "magic"}))


def test_a_guesser_asked_for_what_it_has_not_got():
    with pytest.raises(ValueError, match="the guesser: "):
        runs.world(runs.Settings(pipeline={},
                                 guesser={"predictor": "table", "nonsense": 1}))


def test_a_guesser_without_a_pipeline_is_nothing_at_all():
    """It is the pipeline that guesses; a table of history with no machine around
    it would count nothing."""
    assert runs.world(runs.Settings(guesser={"predictor": "table"}))["pipeline"] is None


def test_the_devices_attached_to_a_run():
    bus = runs.world(runs.Settings(devices={"timer": {}, "lab": {}}))["bus"]
    assert sorted(part.name for part in bus.parts) == ["lab", "timer"]


def test_a_device_built_with_what_was_asked_of_it():
    bus = runs.world(runs.Settings(devices={"timer": {"mode": "virtual"}}))["bus"]
    assert "virtual" in bus.parts[0].state()["clock"]


def test_a_device_nobody_has():
    with pytest.raises(ValueError, match='"wireless": no device of that name'):
        runs.world(runs.Settings(devices={"wireless": {}}))


def test_a_device_asked_for_what_it_has_not_got():
    with pytest.raises(ValueError, match="the timer: "):
        runs.world(runs.Settings(devices={"timer": {"nonsense": 1}}))


def test_what_a_device_is_never_asked_for_in_a_window_is_not_passed_on():
    """A disk is given a FILE by whoever has one, not an image of bytes: the
    setting is left out of what it is built with instead of failing."""
    bus = runs.world(runs.Settings(devices={"disk": {"image": "nonsense"}}))["bus"]
    assert bus.parts[0].name == "disk"
    assert len(bus.parts[0].image) == 16 * 512  # an image of its own, of bytes


# ----------------------------------------------------------- what is offered


def test_what_can_be_set_about_a_cache_is_what_a_cache_has():
    offered = runs.options_of("cache")
    assert [one.name for one in offered] == [
        "block_bytes", "sets", "ways", "replacement", "write_back", "write_allocate"]
    held = {one.name: one.default for one in fields(CacheSettings)}
    assert all(one.default == held[one.name] for one in offered)


def test_what_is_left_out_of_a_cache_is_still_part_of_one():
    """The named exceptions are named because they ARE options of the model and
    are not offered - a name that stopped being one would be a lie here."""
    held = {one.name for one in fields(CacheSettings)}
    assert set(runs.LEFT_OUT["cache"]) < held
    assert set(runs.LEFT_OUT["pipeline"]) < {one.name for one in
                                             fields(PipelineSettings)}


def test_what_can_be_set_about_a_pipeline():
    assert [one.name for one in runs.options_of("pipeline")] == [
        "forwarding", "one_port", "overlap", "penalty", "trap_penalty", "diagram"]


def test_what_can_be_set_about_a_device_is_what_it_is_built_with():
    assert [one.name for one in runs.options_of("timer")] == ["mode", "step"]
    assert [one.name for one in runs.options_of("halt")] == []  # it is a button
    assert "image" not in [one.name for one in runs.options_of("disk")]


def test_every_device_there_is_can_be_asked_about():
    """A device added to the registry is offered by the window the same day,
    because nothing of this is written down twice."""
    for name in DEVICES:
        assert all(one.name and one.kind for one in runs.options_of(name))


def test_a_device_that_cannot_be_built_without_being_told_something():
    """Only what has a default can be offered: a window has nothing to put in a
    row for an argument whose value it cannot guess, and a device that needs one
    is a device the command line builds and a window does not."""
    import pytest as pytest_

    def odd(needed, delay: int = 5):
        raise AssertionError("never built here")

    with pytest_.MonkeyPatch.context() as patching:
        patching.setitem(DEVICES, "odd", odd)
        assert [one.name for one in runs.options_of("odd")] == ["delay"]


def test_what_kind_of_value_each_option_takes():
    """A yes or no comes before a number, because in Python a bool IS one."""
    kinds = {one.name: one for one in runs.options_of("cache")}
    assert kinds["sets"].kind == runs.WHOLE
    assert kinds["write_back"].kind == runs.YES_OR_NO
    assert kinds["replacement"].kind == runs.AMONG
    assert kinds["replacement"].among == ("lru", "fifo", "random")
    assert all(one.among for one in runs.options_of("cache")
               if one.kind == runs.AMONG)


def test_a_choice_a_device_offers_is_the_devices_own():
    assert {one.name: one.among for one in runs.options_of("timer")}["mode"] \
        == ("wall", "virtual")
    assert {one.name: one.among for one in runs.options_of("bitmap")}["place"] \
        == ("data", "global", "static", "heap", "devices")


def test_nothing_of_a_run_is_called_that():
    with pytest.raises(ValueError, match='"gearbox": nothing of a run is called'):
        runs.options_of("gearbox")


# ------------------------------------------------------------ where they are kept


def test_the_settings_are_kept_where_a_desktop_keeps_what_is_a_persons_own(monkeypatch,
                                                                          tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert runs.path() == str(tmp_path / "pyrars" / "run.json")
    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert runs.path().endswith("/.config/pyrars/run.json")


def test_what_is_kept_is_read_back(tmp_path):
    kept = runs.Settings(statistics=False, cache={"sets": 4}, fetches=True,
                         pipeline={"penalty": 3},
                         guesser={"predictor": "table"},
                         devices={"timer": {"mode": "virtual"}})
    where = runs.save(kept, str(tmp_path / "deeper" / "run.json"))
    assert runs.read(where) == kept
    assert json.loads(Path(where).read_text())["cache"] == {"sets": 4}


def test_a_file_that_is_not_there_means_the_defaults(tmp_path):
    """Somebody who has never opened the settings has settings all the same."""
    assert runs.read(str(tmp_path / "nothing.json")) == runs.Settings()


def test_a_settings_file_that_is_not_an_object(tmp_path):
    file = tmp_path / "run.json"
    file.write_text("[1, 2]")
    with pytest.raises(ValueError, match="a JSON object holding statistics"):
        runs.read(str(file))


def test_a_settings_file_that_cannot_be_read_at_all(tmp_path):
    file = tmp_path / "run.json"
    file.write_text("{oh dear")
    with pytest.raises(ValueError, match="line 1"):
        runs.read(str(file))


def test_a_setting_of_a_run_that_is_no_setting_of_a_run(tmp_path):
    file = tmp_path / "run.json"
    file.write_text('{"speed": 5}')
    with pytest.raises(ValueError, match='"speed" is no setting of a run'):
        runs.read(str(file))


def test_a_setting_of_the_wrong_shape_says_what_the_setting_is(tmp_path):
    """A person who wrote the file by hand is told what it should have been, and
    not left to meet the model later."""
    file = tmp_path / "run.json"
    file.write_text('{"statistics": "yes"}')
    with pytest.raises(ValueError, match='"statistics" of a run is true or false'):
        runs.read(str(file))
    file.write_text('{"cache": 8}')
    with pytest.raises(ValueError, match='"cache" of a run is what was asked of it'):
        runs.read(str(file))
    file.write_text('{"devices": {"timer": true}}')
    with pytest.raises(ValueError, match='"devices" of a run is every device'):
        runs.read(str(file))
