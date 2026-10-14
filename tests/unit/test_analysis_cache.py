"""The cache watching a run.

Expected values are worked out by hand from the way a cache is defined, and the
defaults and the way a block is found are those of RARS (R-DEV-CACHE, its
`tools/CacheSimulator`: four words to a block, eight blocks, direct, LRU; the
block is `address / 4 / words of a block`, the set is that modulo the sets, the
rest is the tag; the size of an access does not matter).
"""

import pytest

from pyrars.analysis.cache import Cache, Caches, Settings, Use

WORDS = 4  # words to a block, in the defaults of RARS


def seen(cache: Cache, *addresses: int) -> str:
    """A run of reads as hits and misses, for comparing a whole trace at once."""
    return "".join("h" if cache.read(address).hit else "m" for address in addresses)


# -------------------------------------------------------------- where a block goes


@pytest.mark.parametrize("address, block_bytes, sets, ways, where", [
    # the block is address // block_bytes; the set is that modulo the sets, and what
    # is left of it is the tag
    (0x0000, 4, 2, 1, (0, 0)),
    (0x0004, 4, 2, 1, (1, 0)),
    (0x0008, 4, 2, 1, (0, 1)),
    (0x0010, 16, 8, 1, (1, 0)),  # block 1 of eight sets
    (0x0080, 16, 8, 1, (0, 1)),  # block 8: the set comes round again
    (0x1000, 16, 8, 1, (0, 32)),
    (0x0010, 16, 1, 8, (0, 1)),  # fully associative: one set, every block its tag
    (0x0030, 16, 2, 2, (1, 1)),  # two sets of two ways: block 3 -> set 1, tag 1
])
def test_where_an_address_belongs(address, block_bytes, sets, ways, where):
    cache = Cache(Settings(block_bytes=block_bytes, sets=sets, ways=ways))
    access = cache.read(address)
    assert (access.set, access.tag) == where


def test_the_size_of_an_access_does_not_matter():
    """A byte and a word of the same block are the same block, as in RARS."""
    cache = Cache(Settings(block_bytes=4, sets=4))
    assert seen(cache, 0x10, 0x11, 0x12, 0x13) == "mhhh"


# ------------------------------------------------------------------- the placement


def test_a_direct_cache_keeps_one_block_to_a_set():
    cache = Cache(Settings(block_bytes=4, sets=2))
    # 0 and 8 belong to the same set and push each other out
    assert seen(cache, 0, 4, 0, 8, 0) == "mmhmm"
    assert (cache.accesses, cache.hits, cache.misses) == (5, 1, 4)
    assert cache.hit_rate == 0.2


def test_a_fully_associative_cache_keeps_a_block_wherever_there_is_room():
    cache = Cache(Settings(block_bytes=4, sets=1, ways=4))
    assert seen(cache, 0, 8, 16, 24) == "mmmm"  # all four fit, though one set
    assert seen(cache, 0, 8, 16, 24) == "hhhh"
    assert seen(cache, 32) == "m"  # the fifth throws the least lately used out
    assert seen(cache, 0) == "m"  # which was the block of 0, so it comes back
    # and it in turn threw out the block of 8, so a walk round the five blocks
    # misses every time: four blocks cannot hold five.
    assert seen(cache, 8, 16, 24, 32) == "mmmm"


def test_a_cache_of_two_ways_has_two_of_each_set():
    cache = Cache(Settings(block_bytes=4, sets=2, ways=2))
    # blocks 0, 2, 4 all belong to set 0; two of them fit at once
    assert seen(cache, 0x00, 0x08, 0x00, 0x08) == "mmhh"
    assert seen(cache, 0x10) == "m"  # the third pushes one out
    assert seen(cache, 0x00) == "m"


# ------------------------------------------------------------- what makes room


def test_the_least_lately_used_block_makes_room():
    cache = Cache(Settings(block_bytes=4, sets=1, ways=2, replacement="lru"))
    assert seen(cache, 0x00, 0x08, 0x00) == "mmh"  # 0x00 is the fresher of the two
    assert seen(cache, 0x10) == "m"  # so 0x08 is the one thrown out
    assert seen(cache, 0x00) == "h"
    assert seen(cache, 0x08) == "m"


def test_the_block_that_came_first_makes_room():
    cache = Cache(Settings(block_bytes=4, sets=1, ways=2, replacement="fifo"))
    assert seen(cache, 0x00, 0x08, 0x00) == "mmh"  # using it again changes nothing
    assert seen(cache, 0x10) == "m"  # 0x00 came first, so 0x00 goes
    assert seen(cache, 0x00) == "m"  # and bringing it back throws 0x08 out
    assert seen(cache, 0x08) == "m"  # where a cache of the lately used would hit


WALK = [0, 8, 16, 24, 32] * 3  # five blocks round a cache that holds four


def test_a_block_chosen_by_chance_is_not_the_one_a_rule_would_choose():
    """Walking five blocks round a cache of four misses every time under any rule
    that keeps an order - and chance saves some of them."""
    def run(replacement: str, seed: int | None = None) -> str:
        cache = Cache(Settings(block_bytes=4, sets=1, ways=4,
                               replacement=replacement, seed=seed))
        return seen(cache, *WALK)

    assert run("lru") == run("fifo") == "m" * len(WALK)
    assert run("random", 7) == "mmmmmhhmhhhmmhh"  # our own stream, seeded with 7


def test_a_block_chosen_by_chance_is_chosen_the_same_way_twice():
    """The seed makes a run repeat (INV-D)."""
    def run() -> str:
        cache = Cache(Settings(block_bytes=4, sets=1, ways=4,
                               replacement="random", seed=7))
        return seen(cache, *WALK)

    assert run() == run()


# -------------------------------------------------------------------- the writes


def test_a_block_written_to_is_written_back_when_it_is_thrown_out():
    cache = Cache(Settings(block_bytes=4, sets=1))
    cache.write(0x00)  # a miss that brings the block in and marks it
    assert (cache.misses, cache.writebacks, cache.through) == (1, 0, 0)
    cache.read(0x04)  # it throws the written block out, so memory hears of it
    assert cache.writebacks == 1


def test_a_block_nobody_wrote_to_is_not_written_back():
    cache = Cache(Settings(block_bytes=4, sets=1))
    cache.read(0x00)
    cache.read(0x04)
    assert cache.writebacks == 0


def test_a_write_can_go_to_memory_at_once():
    cache = Cache(Settings(block_bytes=4, sets=1, write_back=False))
    cache.write(0x00)
    cache.write(0x00)
    assert (cache.through, cache.writebacks) == (2, 0)
    cache.read(0x04)  # nothing to write back: the block was never dirty
    assert cache.writebacks == 0


def test_a_write_that_misses_need_not_bring_its_block_in():
    cache = Cache(Settings(block_bytes=4, sets=2, write_allocate=False))
    assert cache.write(0x00).hit is False
    assert cache.read(0x00).hit is False  # the block was never brought in
    assert (cache.misses, cache.through) == (2, 1)


def test_a_write_that_misses_can_bring_its_block_in():
    cache = Cache(Settings(block_bytes=4, sets=2, write_allocate=True))
    assert cache.write(0x00).hit is False
    assert cache.read(0x00).hit is True


# ------------------------------------------------------------ what is kept of it


def test_the_log_holds_the_last_accesses_and_no_more():
    cache = Cache(Settings(block_bytes=4, sets=4, log=3))
    seen(cache, 0, 4, 8, 12, 16)
    assert [access.address for access in cache.log] == [8, 12, 16]
    assert cache.accesses == 5  # and the totals are still exact


def test_a_log_of_nothing_keeps_nothing():
    cache = Cache(Settings(log=0))
    seen(cache, 0, 4, 8)
    assert list(cache.log) == [] and cache.accesses == 3


def test_an_access_says_what_it_was():
    cache = Cache(Settings(block_bytes=4, sets=1))
    cache.write(0x00)
    thrown = cache.read(0x04)
    assert (thrown.use, thrown.address, thrown.hit) == (Use.READ, 0x04, False)
    assert (thrown.evicted, thrown.wrote_back) == (0, True)


def test_the_time_series_tells_how_the_cache_warmed_up():
    cache = Cache(Settings(block_bytes=4, sets=4, sample=2))
    seen(cache, 0, 0, 4, 4, 8, 8)
    assert [(point.accesses, point.hits, point.misses) for point in cache.series] == [
        (2, 1, 1), (4, 1, 1), (6, 1, 1)]


def test_without_a_sample_there_is_no_series():
    cache = Cache(Settings(block_bytes=4, sets=4))
    seen(cache, 0, 4, 8)
    assert cache.series == []


def test_a_cache_can_be_emptied():
    cache = Cache(Settings(block_bytes=4, sets=2, sample=1))
    seen(cache, 0, 0)
    cache.reset()
    assert (cache.accesses, cache.hits, cache.series, list(cache.log)) == (0, 0, [], [])
    assert seen(cache, 0) == "m"  # it holds nothing again


def test_the_share_of_hits_of_nothing():
    assert Cache().hit_rate == 0.0


# ------------------------------------------------------------------- the settings


def test_the_defaults():
    """A block of sixteen bytes, eight sets, direct, the lately used thrown out -
    the numbers RARS starts its own tool with, so that a run held against it needs
    no translating (user decision 2026-10-14). They are numbers, not a tie."""
    settings = Settings()
    assert (settings.block_bytes, settings.sets, settings.ways) == (16, 8, 1)
    assert (settings.replacement, settings.blocks) == ("lru", 8)


@pytest.mark.parametrize("options, says", [
    ({"block_bytes": 3}, "power of two"),
    ({"block_bytes": 0}, "power of two"),
    ({"sets": 6}, "power of two"),
    ({"sets": 0}, "power of two"),
    ({"ways": 0}, "at least one block"),
    ({"replacement": "oldest"}, "lru or fifo or random"),
    ({"log": -1}, "never below nothing"),
    ({"sample": -2}, "never below nothing"),
])
def test_settings_that_make_no_cache(options, says):
    with pytest.raises(ValueError, match=says):
        Settings(**options)


def test_the_blocks_need_be_no_power_of_two():
    """Three ways over four sets is twelve blocks, and such caches are built: only
    the size of a block and the number of sets are fields of an address."""
    settings = Settings(block_bytes=4, sets=4, ways=3)
    assert settings.blocks == 12
    cache = Cache(settings)
    # blocks 0, 4 and 8 all belong to set 0, and all three fit at once
    assert seen(cache, 0x00, 0x10, 0x20, 0x00, 0x10, 0x20) == "mmmhhh"
    assert seen(cache, 0x30) == "m"  # the fourth of that set pushes one out


def test_a_cache_of_a_million_sets_costs_nothing_until_it_is_used():
    """The sets are made when they are first touched, as the pages of our memory
    are, so nothing limits how large a cache may be described."""
    cache = Cache(Settings(block_bytes=64, sets=1 << 20, ways=8))
    assert cache.settings.blocks == 8 << 20
    assert len(cache.lines) == 0
    cache.read(0x10010000)
    assert len(cache.lines) == 1


# -------------------------------------------------------------- one cache or two


def test_one_cache_sees_everything():
    caches = Caches()
    caches.fetch(0x00400000)
    caches.read(0x10010000)
    caches.write(0x10010004)
    assert caches.split is False
    assert caches.data.accesses == 3
    assert set(caches.each()) == {"cache"}


def test_two_caches_divide_the_work():
    caches = Caches(data=Settings(block_bytes=4, sets=4),
                    instructions=Settings(block_bytes=4, sets=4))
    caches.fetch(0x00400000)
    caches.fetch(0x00400004)
    caches.read(0x10010000)
    assert caches.split is True
    assert (caches.instructions.accesses, caches.data.accesses) == (2, 1)
    assert set(caches.each()) == {"instructions", "data"}


def test_both_caches_can_be_emptied():
    caches = Caches(instructions=Settings())
    caches.fetch(0x00400000)
    caches.read(0x10010000)
    caches.reset()
    assert (caches.instructions.accesses, caches.data.accesses) == (0, 0)


# ------------------------------------------------------- a run as RARS would see it


def test_a_walk_through_an_array_with_the_defaults():
    """A block of sixteen bytes holds four words: the first word of a block misses
    and the next three hit, so walking sixteen words gives four misses."""
    cache = Cache()
    addresses = [0x10010000 + 4 * index for index in range(16)]
    assert seen(cache, *addresses) == "mhhh" * 4
    assert (cache.misses, cache.hits) == (4, 12)
    assert cache.hit_rate == 0.75


def test_a_walk_too_long_for_the_cache():
    """Eight blocks of sixteen bytes hold thirty-two words; the thirty-third pushes
    the first out."""
    cache = Cache()
    addresses = [0x10010000 + 4 * index for index in range(36)]
    seen(cache, *addresses)
    assert cache.misses == 9
    assert seen(cache, 0x10010000) == "m"  # its block was thrown out by the last one
