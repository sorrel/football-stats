"""Turn query results into aligned text.

`len()` is wrong for width arithmetic: combining accents count as characters
but occupy no column, and wide glyphs occupy two while counting as one. Club
names reaching this table carry both, so every width calculation goes through
`display_width` and colour is applied only after padding is worked out.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

# A quantity: digits, thousands separators, an optional decimal part and an
# optional leading minus (either the hyphen or the true minus sign). A season
# such as "1982-83" is deliberately not matched.
_NUMERIC = re.compile(r"^[-\u2212]?\d[\d,]*(\.\d+)?%?$")


def display_width(text: str) -> int:
    """Width of `text` in terminal columns."""
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return width


def _cell(value: object) -> str:
    """Render one value. Empty means unknown, so `None` shows as nothing.

    Whole numbers are grouped in thousands — 4,791 rather than 4791 — since
    every integer reaching this table is a count or a crowd. Text is left
    exactly as it arrives: a season is "1982-83" and a year held as text is
    not a quantity, so neither should acquire a comma.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _is_numeric(text: str) -> bool:
    """Whether a rendered cell holds a quantity rather than a label."""
    return bool(_NUMERIC.match(text))


def render_table(headers: Sequence[str], rows: Sequence[Sequence[object]],
                 caption: str | None = None) -> str:
    """Render an aligned text table with a rule under the headings.

    Columns of quantities are set flush right, headings included, so that
    units line up under units and a run of figures can be read down the page.
    A column is only treated that way when every value in it is a number, so a
    season or a club name keeps its usual left edge.

    A blank line opens every table, so the row of headings is never mistaken
    for another line of prose. It belongs here rather than at each call site:
    a table is always worth setting apart, and one rule beats a dozen. A
    `caption` sits inside that opening, directly above the headings, so it
    cannot drift away from the table it names.
    """
    text_rows = [[_cell(value) for value in row] for row in rows]
    widths = [display_width(head) for head in headers]
    for row in text_rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], display_width(cell))

    numeric = [
        any(row[index] for row in text_rows if index < len(row))
        and all(
            _is_numeric(row[index])
            for row in text_rows
            if index < len(row) and row[index]
        )
        for index in range(len(widths))
    ]

    def line(cells: Sequence[str]) -> str:
        padded = []
        for index, cell in enumerate(cells):
            pad = " " * (widths[index] - display_width(cell))
            padded.append(pad + cell if numeric[index] else cell + pad)
        return " | ".join(padded).rstrip()

    out = ["", line(list(headers)), "-+-".join("-" * width for width in widths)]
    if caption is not None:
        out.insert(1, caption)
    out.extend(line(row) for row in text_rows)
    return "\n".join(out)
