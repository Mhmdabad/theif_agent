"""The zero-dependency test tier.

Everything here runs with **nothing installed** — stdlib `unittest`, an in-process transport and a
fake clock. That is deliberate: the promise that this kit can be verified without an install has
to survive the arrival of the package's one dependency, so the entire game layer, including a full
six-sub-game series, is testable before fastmcp enters the picture.

Run from the repository root:

    python -m unittest discover -s sparring/tests -t .
"""
