"""Renders query results in a few output formats: an aligned plain-text
table (default, no deps beyond str.ljust), CSV, or JSON -- all stdlib
only (csv/json modules), so results can be piped straight into other
tools instead of only being eyeballed in a terminal."""

from __future__ import annotations

import csv
import io
import json


def format_table(rows: list[dict]) -> str:
    if not rows:
        return "(0 rows)"

    columns = list(rows[0].keys())
    str_rows = [[_cell(r.get(c)) for c in columns] for r in rows]
    widths = [
        max(len(col), *(len(row[i]) for row in str_rows)) if str_rows else len(col)
        for i, col in enumerate(columns)
    ]

    def fmt_row(cells: list[str]) -> str:
        return " | ".join(cell.ljust(width) for cell, width in zip(cells, widths))

    header = fmt_row(columns)
    separator = "-+-".join("-" * w for w in widths)
    body = "\n".join(fmt_row(r) for r in str_rows)
    footer = f"({len(rows)} row{'s' if len(rows) != 1 else ''})"
    return f"{header}\n{separator}\n{body}\n{footer}"


def format_csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    columns = list(rows[0].keys())
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for r in rows:
        writer.writerow({c: _csv_cell(r.get(c)) for c in columns})
    return buf.getvalue().rstrip("\n")


def format_json(rows: list[dict]) -> str:
    return json.dumps(rows, indent=2, default=str)


FORMATTERS = {
    "table": format_table,
    "csv": format_csv,
    "json": format_json,
}


def _cell(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _csv_cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return value
