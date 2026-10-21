"""What the pictures of the window are made of.

A picture is DATA here - boxes and words at places - so all of it is tested like
any other table of the project, and the widget that paints it has nothing in it to
get wrong. What is asked of each picture is what somebody READS off it: which cell
of a cache holds which block, that the stages of the pipeline lie one cycle apart,
which segments of a display are lit.
"""

from pyrars.session.debug import (
    CacheLine, CacheSeen, Setting, StageSeen, StatisticsSeen)
from pyrars.ui.drawing import (
    BLOCK, COLOURS, CYCLE, SEGMENT, SET, STAGES, STEP, WHERE, bars_picture,
    blocks_picture, cache_picture, copying_picture, lab_picture, pipeline_picture)


def cache(side="cache", sets=4, ways=1, accesses=0, hits=0, misses=0, rate=0.0):
    return CacheSeen(side, False,
                     (Setting("block_bytes", 16), Setting("sets", sets),
                      Setting("ways", ways)), accesses, hits, misses, rate, 0, 0)


def boxes(picture, fill: str = ""):
    return [part for part in picture.parts
            if part.width and part.height and (not fill or part.fill == fill)]


def words(picture) -> list[str]:
    return [part.text for part in picture.parts if part.text]


# ------------------------------------------------------------------ the cache


def test_a_cache_is_a_grid_of_its_sets_and_its_ways():
    drawn = cache_picture([cache(sets=4, ways=2)])
    assert len(boxes(drawn)) == 8  # a cell to every block it can hold
    assert len(boxes(drawn, "empty")) == 8  # and it is holding none of them
    assert "set 3" in words(drawn) and "way 1" in words(drawn)
    assert drawn.width >= SET + 2 * BLOCK[0]
    assert drawn.height >= 4 * BLOCK[1]


def test_a_block_a_cache_holds_is_in_its_own_cell():
    """The place of a block in its set is where it sits AND how long it has been
    there: the one at place 0 is the one that will make room."""
    held = [CacheLine("cache", 1, 0, 5, 0x10010000, 0x1001000F, False),
            CacheLine("cache", 1, 1, 6, 0x10010010, 0x1001001F, True)]
    drawn = cache_picture([cache(sets=4, ways=2)], held)
    kept = {(part.x, part.y): part for part in boxes(drawn)}
    first = [part for part in boxes(drawn) if part.text == "0x10010000"][0]
    second = [part for part in boxes(drawn) if part.text == "0x10010010"][0]
    assert first.fill == "clean" and second.fill == "dirty"
    assert second.x == first.x + BLOCK[0]  # the next way along
    assert first.y == second.y  # and the same set
    assert len([part for part in kept.values() if part.fill == "empty"]) == 6


def test_what_a_cache_has_done_is_written_over_its_grid():
    drawn = cache_picture([cache(accesses=256, hits=0, misses=256, rate=0.0)])
    assert words(drawn)[0] == ("cache: 4 sets of 1, 16 bytes a block - 256 "
                               "accesses, 0 hits, 256 misses (0% hit)")
    quiet = cache_picture([cache()])
    assert quiet.parts[0].text.endswith("nothing has reached it yet")


def test_two_caches_are_two_grids_one_under_the_other():
    drawn = cache_picture([cache("data", sets=2), cache("instructions", sets=2)])
    upper = [part for part in words(drawn) if part.startswith("data")]
    lower = [part for part in words(drawn) if part.startswith("instructions")]
    assert upper and lower
    headings = [part for part in drawn.parts if part.text.startswith(("data", "ins"))]
    assert headings[0].y < headings[1].y
    assert len(boxes(drawn)) == 4


def test_a_cache_nobody_asked_for_is_no_picture_at_all():
    assert cache_picture([]).parts == ()


# --------------------------------------------------------------- the pipeline


def test_the_diagram_is_a_stage_to_a_cell():
    rows = [StageSeen(0x400000, "addi", (0, 1, 2, 3, 4), 1, 0),
            StageSeen(0x400004, "lw", (1, 2, 3, 4, 5), 1, 0)]
    drawn = pipeline_picture(rows)
    assert len(boxes(drawn)) == 10  # five stages to each of two instructions
    fetches = [part for part in boxes(drawn) if part.fill == "fetch"]
    # one cycle along and one row down: the diagonal anybody reads a diagram by
    assert fetches[1].x == fetches[0].x + CYCLE
    assert fetches[1].y == fetches[0].y + STEP
    assert all(part.fill in STAGES for part in boxes(drawn))
    assert "0x00400004  lw" in words(drawn)


def test_a_stage_that_held_an_instruction_longer_is_a_wider_cell():
    rows = [StageSeen(0x400000, "div", (0, 1, 2, 6, 7), 4, 0)]
    drawn = pipeline_picture(rows)
    held = [part for part in boxes(drawn) if part.fill == "execute"][0]
    assert held.width == CYCLE * 4 - 2.0
    memory = [part for part in boxes(drawn) if part.fill == "memory"][0]
    assert memory.x == WHERE + 6 * CYCLE  # and what follows it waited


def test_the_cycles_are_numbered_along_the_top():
    rows = [StageSeen(0x400000 + 4 * one, "addi", (one, one + 1, one + 2, one + 3,
                                                   one + 4), 1, 0)
            for one in range(12)]
    drawn = pipeline_picture(rows)
    numbered = [part for part in drawn.parts
                if part.y == 0.0 and part.text.isdigit()]
    assert [part.text for part in numbered] == ["0", "5", "10", "15"]
    assert drawn.width == WHERE + 16 * CYCLE  # the last stage of the last row


def test_a_pipeline_that_kept_no_diagram():
    assert pipeline_picture([]).parts == ()


# -------------------------------------------------------------- the devices


def lab(left=0, right=0, key=-1, counting=False, counter=0):
    from pyrars.devices.lab import KEYS, PERIOD, SEGMENTS

    return {"left": left, "right": right, "segments": SEGMENTS, "keys": KEYS,
            "key": key, "counting": counting, "counter": counter,
            "period": PERIOD, "keys tell": False}


def test_the_segments_of_a_display_are_the_bits_the_program_wrote():
    dark = lab_picture(lab())
    assert len(boxes(dark, "lit")) == 0
    assert len(boxes(dark, "dark")) == 16  # two displays of eight segments
    lit = lab_picture(lab(left=0xFF, right=0x01))
    assert len(boxes(lit, "lit")) == 9  # all of the one, the first of the other
    # the bit 0 is the segment `a`, which lies across the top of the display
    one = boxes(lab_picture(lab(left=0x01)), "lit")
    assert len(one) == 1
    assert (one[0].x, one[0].y) == (SEGMENT, 0.0)
    assert one[0].width > one[0].height
    # and the bit 1 is `b`, which stands down the right of it: each bit its own
    two = boxes(lab_picture(lab(left=0x02)), "lit")
    assert len(two) == 1
    assert two[0].x > one[0].x and two[0].height > two[0].width


def test_the_key_that_is_down_is_the_one_that_is_lit():
    none = lab_picture(lab())
    assert len(boxes(none, "lit")) == 0
    drawn = lab_picture(lab(key=6))
    down = boxes(drawn, "lit")
    assert len(down) == 1 and down[0].text == "6"
    assert [part.text for part in boxes(drawn) if part.text][:5] \
        == ["0", "1", "2", "3", "4"]
    assert "F" in [part.text for part in boxes(drawn)]  # sixteen of them, 0 to F


def test_the_counter_of_the_lab_is_a_bar_while_it_runs():
    off = lab_picture(lab())
    assert len(boxes(off, "bar")) == 0
    assert "counter: off" in words(off)
    running = lab_picture(lab(counting=True, counter=10))
    assert len(boxes(running, "bar")) == 1
    assert "counter: 10 notices to go" in words(running)


def test_a_device_that_was_never_attached_draws_nothing():
    assert lab_picture({}).parts == ()
    assert blocks_picture({}).parts == ()
    assert copying_picture({}).parts == ()


def test_a_disk_is_its_blocks_with_the_one_at_work_lit():
    quiet = blocks_picture({"blocks": 4, "at": 0, "left": 0, "working": False,
                            "writing": False, "refused": False})
    assert len(boxes(quiet)) == 4 and not boxes(quiet, "lit")
    assert "not working" in words(quiet)
    working = blocks_picture({"blocks": 4, "at": 2, "left": 1, "working": True,
                              "writing": True, "refused": False})
    lit = boxes(working, "lit")
    assert len(lit) == 1 and lit[0].text == "2"
    assert "working to the disk at block 2, 1 to go" in words(working)


def test_the_copying_of_the_controller_is_how_far_it_has_got():
    drawn = copying_picture({"copied": 3, "left": 1, "copying": True, "from": 0x10,
                             "to": 0x20, "refused": False}, wide=100.0)
    bars = boxes(drawn, "bar")
    assert len(bars) == 1 and bars[0].width == 75.0  # three of four words
    assert "copying 0x00000010 to 0x00000020" in words(drawn)[0]


def test_a_copying_that_was_refused_says_so():
    drawn = copying_picture({"copied": 0, "left": 0, "copying": False, "from": 0,
                             "to": 0, "refused": True})
    assert words(drawn)[0].endswith("the last copying was refused")


# ----------------------------------------------------------- what was counted


def test_what_a_run_was_made_of_is_bars_beside_the_kinds():
    counted = StatisticsSeen(10, 10, 0, 0, 1, 1,
                             kinds=(Setting("alu", 6), Setting("branch", 2)),
                             categories=())
    drawn = bars_picture(counted, wide=120.0)
    bars = boxes(drawn, "bar")
    assert len(bars) == 2
    assert bars[0].width == 120.0  # the biggest fills the room
    assert bars[1].width == 40.0  # and the rest are to its scale
    assert "alu" in words(drawn) and "6" in words(drawn)


def test_a_run_that_was_not_counted_is_no_picture():
    assert bars_picture(None).parts == ()
    assert bars_picture(StatisticsSeen(0, 0, 0, 0, 0, 0, (), ())).parts == ()


# ------------------------------------------------------------------ all of them


def test_every_colour_a_picture_names_is_a_colour_there_is():
    """A picture names its colours; the canvas looks them up and would raise on a
    name nobody has, in a draw handler, where nobody would see it."""
    held = [CacheLine("cache", 0, 0, 1, 0, 15, True)]
    counted = StatisticsSeen(1, 1, 0, 0, 0, 0, (Setting("alu", 1),), ())
    every = [cache_picture([cache(accesses=1, misses=1)], held),
             pipeline_picture([StageSeen(0, "addi", (0, 1, 2, 3, 4), 1, 0)]),
             lab_picture(lab(left=1, key=0, counting=True, counter=1)),
             bars_picture(counted),
             blocks_picture({"blocks": 2, "at": 1, "left": 1, "working": True,
                             "writing": False, "refused": False}),
             copying_picture({"copied": 1, "left": 1, "copying": True, "from": 0,
                              "to": 4, "refused": False})]
    for picture in every:
        assert picture.parts
        for part in picture.parts:
            assert not part.fill or part.fill in COLOURS, part
            assert not part.edge or part.edge in COLOURS, part
            assert part.width >= 0.0 and part.height >= 0.0
            assert part.x >= 0.0 and part.y >= 0.0
        assert picture.width >= max(part.x + part.width for part in picture.parts)
