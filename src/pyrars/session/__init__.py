"""The way the world outside asks the machine to do things.

Everything above the engine talks to it through here: the console debugger of
`pyrars.cli`, and later the window of `pyrars.ui`. What lives here answers in
DATA - places, values, frames, what a movement ended on - and never in text, so
that a terminal and a window can show the same session each in its own way.
"""
