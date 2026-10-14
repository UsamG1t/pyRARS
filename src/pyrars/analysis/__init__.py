"""What a run was made of: models that watch and never touch.

Everything here is passive (INV-P): it is handed what a run did - the record of
every turn of the loop from `core/simulator.py`, and the accesses of memory from
`Memory.subscribe` - and says something about it. None of it may change a
register, a byte of memory or the reason a run ended, and nothing of it is built
unless someone asks for it.
"""
