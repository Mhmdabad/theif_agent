"""The four delegating lines that put :mod:`.paint` onto a real Tk canvas.

Split out of :mod:`.app` so the adapter and the Protocol it satisfies sit on
their own, below every drawing routine and below both windows.
"""

from typing import Protocol

from .paint import CELL


class Canvas(Protocol):
    """The slice of ``tkinter.Canvas`` this module uses.

    Describes the exact three calls made below, not the library. A looser
    Protocol — ``*args: object`` — reads as more accommodating and is in fact
    *stricter on the implementation*: it promises callers may pass anything,
    which a real ``tkinter.Canvas`` does not honour, so the real canvas would
    not satisfy it. That is the same mistake ``ToolHost`` made about ``FastMCP``
    in #285, caught here by mypy for the same reason: a Protocol is only true
    once something concrete is passed to it.
    """

    def create_rectangle(
        self, x0: int, y0: int, x1: int, y1: int, *, fill: str, outline: str
    ) -> object: ...

    def create_text(
        self, x: int, y: int, *, text: str, fill: str, font: tuple[str, int]
    ) -> object: ...

    def delete(self, tag: str) -> object: ...


class CanvasPainter:
    """Adapts a Tk canvas to :class:`~.paint.Painter`. Four lines, no logic."""

    def __init__(self, canvas: Canvas) -> None:
        self.canvas = canvas

    def rectangle(self, x0: int, y0: int, x1: int, y1: int, fill: str, outline: str) -> None:
        self.canvas.create_rectangle(x0, y0, x1, y1, fill=fill, outline=outline)

    def text(self, x: int, y: int, body: str, fill: str) -> None:
        self.canvas.create_text(x, y, text=body, fill=fill, font=("TkFixedFont", CELL // 2))

    def clear(self) -> None:
        self.canvas.delete("all")
