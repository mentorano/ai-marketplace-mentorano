"""The inline JavaScript of an HTML file.

Imported by measure.py and typescript.py; nothing runs this file. A block is
the content of one `<script>` element the browser would run as JavaScript: no
`src`, and no `type` or a JavaScript one. A `src` script holds its code in
another file, and a block of any other type (`application/json`,
`application/ld+json`, `importmap`, a template) is data, so neither is code
of this file.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

# A `type` the browser runs: the classic JavaScript MIME types and `module`.
JAVASCRIPT_TYPES = frozenset(
    {
        "",
        "module",
        "text/javascript",
        "application/javascript",
        "text/ecmascript",
        "application/ecmascript",
        "application/x-javascript",
    }
)


@dataclass(frozen=True)
class ScriptBlock:
    """The content of one inline script: text[start:end] of the HTML file."""

    start: int
    end: int


def _is_javascript(attrs: list[tuple[str, str | None]]) -> bool:
    given = dict(attrs)
    if "src" in given:
        return False
    essence = (given.get("type") or "").split(";", 1)[0].strip().lower()
    return essence in JAVASCRIPT_TYPES


class _ScriptFinder(HTMLParser):
    """Records where each inline JavaScript block starts and ends."""

    def __init__(self, text: str):
        super().__init__(convert_charrefs=False)
        self._line_starts = [0, *(match.end() for match in re.finditer("\n", text))]
        self._text = text
        self._open: int | None = None
        self.blocks: list[ScriptBlock] = []

    def _offset(self) -> int:
        line, column = self.getpos()
        return self._line_starts[line - 1] + column

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # getpos() is where the tag starts; the content starts after the whole
        # tag, which may span several lines.
        if tag == "script" and _is_javascript(attrs):
            self._open = self._offset() + len(self.get_starttag_text() or "")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # `<script/>` has no content this parser can give: it reads what follows as markup.
        if tag != "script":
            super().handle_startendtag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._close(self._offset())

    def _close(self, end: int) -> None:
        # An empty or blank script is no code: a page that has only those needs no parser.
        if self._open is not None and self._text[self._open : end].strip():
            self.blocks.append(ScriptBlock(self._open, end))
        self._open = None

    def finish(self) -> list[ScriptBlock]:
        self.close()
        # A script the file never closes runs to the end of the file.
        self._close(len(self._text))
        return self.blocks


def script_blocks(text: str) -> list[ScriptBlock]:
    """The inline JavaScript blocks of an HTML text, in file order."""
    finder = _ScriptFinder(text)
    finder.feed(text)
    return finder.finish()


def in_place(text: str, block: ScriptBlock) -> str:
    """The block alone at its own line and column, so a parser reports the HTML file's line numbers."""
    line_start = text.rfind("\n", 0, block.start) + 1
    return "\n" * text.count("\n", 0, block.start) + " " * (block.start - line_start) + text[block.start : block.end]


def script_text(text: str, blocks: list[ScriptBlock]) -> str:
    return "\n".join(text[block.start : block.end] for block in blocks)


def _code_lines(text: str, block: ScriptBlock) -> range:
    """The line numbers from the block's first code character to its last."""
    content = text[block.start : block.end]
    first = block.start + len(content) - len(content.lstrip())
    last = block.start + len(content.rstrip()) - 1
    return range(text.count("\n", 0, first), text.count("\n", 0, last) + 1)


def script_lines(text: str, blocks: list[ScriptBlock]) -> int:
    """Lines the blocks' code takes, each line once: blank lines inside a block count, the ones around it do not."""
    return len({line for block in blocks for line in _code_lines(text, block)})
