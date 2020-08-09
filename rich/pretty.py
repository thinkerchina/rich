import sys

from collections import defaultdict
from dataclasses import dataclass, field
from rich.highlighter import ReprHighlighter

from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

from .cells import cell_len
from .highlighter import Highlighter, NullHighlighter, ReprHighlighter
from ._loop import loop_last
from .measure import Measurement
from ._pick import pick_bool
from .text import Text

if TYPE_CHECKING:  # pragma: no cover
    from .console import (
        Console,
        ConsoleOptions,
        HighlighterType,
        OverflowMethod,
        RenderResult,
    )


def install(
    console: "Console" = None, no_wrap: bool = False, overflow: "OverflowMethod" = None
) -> None:
    """Install automatic pretty printing in the Python REPL.

    Args:
        console (Console, optional): Console instance or ``None`` to use global console. Defaults to None.
    """
    from rich import get_console

    console = console or get_console()

    def display_hook(value: Any) -> None:
        if value is not None:
            assert console is not None
            console.print(
                value
                if hasattr(value, "__rich_console__") or hasattr(value, "__rich__")
                else pretty_repr(
                    value, max_width=console.width, no_wrap=False, overflow=overflow
                )
            )

    sys.displayhook = display_hook


class Pretty:
    """A rich renderable that pretty prints an object."""

    def __init__(
        self,
        _object: Any,
        highlighter: "HighlighterType" = None,
        *,
        indent_size: int = 4,
        overflow: "OverflowMethod" = None,
        no_wrap: bool = None,
    ) -> None:
        self._object = _object
        self.highlighter = highlighter or NullHighlighter()
        self.indent_size = indent_size
        self.overflow = overflow
        self.no_wrap = no_wrap

    def __rich_console__(
        self, console: "Console", options: "ConsoleOptions"
    ) -> "RenderResult":
        pretty_text = pretty_repr(
            self._object,
            max_width=options.max_width,
            indent_size=self.indent_size,
            overflow=self.overflow or options.overflow,
            no_wrap=pick_bool(self.no_wrap, options.no_wrap, True),
        )
        yield pretty_text

    def __rich_measure__(self, console: "Console", max_width: int) -> "Measurement":
        pretty_text = pretty_repr(
            self._object, max_width=max_width, indent_size=self.indent_size
        )
        text_width = max(cell_len(line) for line in pretty_text.plain.splitlines())
        return Measurement(text_width, text_width)


_BRACES: Dict[type, Tuple[str, str, str]] = {
    dict: ("{", "}", "{}"),
    frozenset: ("frozenset({", "})", "frozenset()"),
    list: ("[", "]", "[]"),
    set: ("{", "}", "set()"),
    tuple: ("(", ")", "tuple()"),
}
_CONTAINERS = tuple(_BRACES.keys())


@dataclass
class _Line:
    """A line in a pretty repr."""

    parts: List[str] = field(default_factory=list)
    _cell_len: int = 0

    def append(self, text: str) -> None:
        """Add text to line."""
        # Efficiently keep track of cell length
        self.parts.append(text)
        self._cell_len += cell_len(text)

    @property
    def cell_len(self) -> int:
        return (
            self._cell_len
            if self.parts and not self.parts[-1].endswith(" ")
            else self._cell_len - 1
        )

    @property
    def text(self) -> str:
        """The text as a while."""
        return "".join(self.parts)


def pretty_repr(
    _object: Any,
    *,
    max_width: Optional[int] = 80,
    indent_size: int = 4,
    highlighter: Highlighter = None,
    overflow: "OverflowMethod" = None,
    no_wrap: bool = True,
) -> Text:
    """Return a 'pretty' repr.

    Args:
        _object (Any): Object to repr.
        max_width (int, optional): Maximum desired width. Defaults to 80.
        indent_size (int, optional): Number of spaces in an indent. Defaults to 4.
        highlighter (Highlighter, optional): A highlighter for repr strings. Defaults to ReprHighlighter.

    Returns:
        Text: A Text instance conaining a pretty repr.
    """
    print("MAX WIDTH=", max_width)

    class MaxLineReached(Exception):
        """Line is greater than maximum"""

        def __init__(self, line_no: int) -> None:
            self.line_no = line_no
            super().__init__()

    if highlighter is None:
        highlighter = ReprHighlighter()

    indent = " " * indent_size
    expand_level = 0
    lines: List[_Line] = [_Line()]

    visited_set: Set[int] = set()
    repr_cache: Dict[int, str] = {}
    repr_cache_get = repr_cache.get

    def to_repr_text(node: Any) -> str:
        """Convert object to repr."""
        node_id = id(node)
        cached = repr_cache_get(node_id)
        if cached is not None:
            return cached
        try:
            repr_text = repr(node)
        except Exception as error:
            repr_text = f"<error in repr: {error}>"
        repr_cache[node_id] = repr_text
        return repr_text

    comma = ", "
    colon = ": "
    line_break: Optional[int] = None

    def traverse(node: Any, level: int = 0) -> None:
        """Walk the data structure."""
        nonlocal line_break
        append_line = lines.append

        def append_text(text: str) -> None:
            nonlocal line_break
            line = lines[-1]
            line.append(text)
            if max_width is not None and line.cell_len > max_width:
                if line_break is not None and len(lines) <= line_break:
                    return
                line_break = len(lines)
                raise MaxLineReached(level)

        node_id = id(node)
        if node_id in visited_set:
            # Recursion detected
            append_text("...")
            return

        visited_set.add(node_id)
        if type(node) in _CONTAINERS:
            brace_open, brace_close, empty = _BRACES[type(node)]
            expanded = level < expand_level

            if not node:
                append_text(empty)
            else:
                append_text(brace_open)
                if isinstance(node, dict):
                    for last, (key, value) in loop_last(node.items()):
                        if expanded:
                            append_line(_Line())
                            append_text(indent * (level + 1))
                        append_text(to_repr_text(key))
                        append_text(colon)
                        traverse(value, level + 1)
                        if not last:
                            append_text(comma)
                else:
                    for last, value in loop_last(node):
                        if expanded:
                            append_line(_Line())
                            append_text(indent * (level + 1))
                        traverse(value, level + 1)
                        if not last:
                            append_text(comma)
                if expanded:
                    lines.append(_Line())
                    append_text(f"{indent * level}{brace_close}")
                else:
                    append_text(brace_close)
        else:
            append_text(to_repr_text(node))
        visited_set.remove(node_id)

    # Keep expanding levels until the text fits
    while True:
        try:
            traverse(_object)
        except MaxLineReached as max_line:
            del lines[:]
            visited_set.clear()
            lines.append(_Line())
            expand_level += 1
        else:
            break  # pragma: no cover

    text = Text(
        "\n".join(line.text for line in lines), overflow=overflow, no_wrap=no_wrap
    )
    text = highlighter(text)
    return text


if __name__ == "__main__":  # pragma: no cover
    from collections import defaultdict

    class BrokenRepr:
        def __repr__(self):
            1 / 0

    d = defaultdict(int)
    d["foo"] = 5
    data = {
        "foo": [1, "Hello World!", 2, 3, 4, {5, 6, 7, (1, 2, 3, 4), 8}],
        "bar": frozenset({1, 2, 3}),
        False: "This is false",
        True: "This is true",
        None: "This is None",
        "Broken": BrokenRepr(),
    }
    data["foo"].append(data)  # type: ignore

    from rich.console import Console

    console = Console()
    from rich import print

    p = Pretty(data, overflow="ellipsis")
    print(Measurement.get(console, p))
    console.print(p)


# if __name__ == "__main__":
#     import json
#     from time import time
#     from rich.console import Console

#     with open("cats.json") as f:
#         cats = json.load(f)
#     c = Console()
#     start = time()
#     c.print(Pretty(cats))
#     print((time() - start) * 1000)

