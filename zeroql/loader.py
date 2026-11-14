"""
Loads a data file into a uniform "table" -- a list of plain dicts, one
per row -- so the evaluator never has to care whether the data came
from CSV or JSON. Every value is passed through `infer_type` because
CSV gives everything back as strings, and `age > 30` needs to compare
as numbers, not lexicographically as text.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .errors import LoadError

Row = dict
Table = list


def infer_type(raw: str):
    """Best-effort promotion of a raw CSV string to int / float / bool / str."""
    if not isinstance(raw, str):
        return raw
    text = raw.strip()
    if text.lower() in ("true", "false"):
        return text.lower() == "true"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return raw


def load_table(path: str) -> Table:
    p = Path(path)
    if not p.exists():
        raise LoadError(f"No such data file: {path}")

    suffix = p.suffix.lower()
    try:
        if suffix == ".csv":
            return _load_csv(p)
        if suffix in (".json",):
            return _load_json(p)
        if suffix in (".jsonl", ".ndjson"):
            return _load_jsonl(p)
    except LoadError:
        raise
    except Exception as exc:  # noqa: BLE001 - surfaced as a clean LoadError
        raise LoadError(f"Failed to read {path}: {exc}") from exc

    raise LoadError(f"Unsupported file type {suffix!r} (expected .csv, .json, or .jsonl)")


def _load_csv(p: Path) -> Table:
    with p.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [{k: infer_type(v) for k, v in row.items()} for row in reader]


def _load_json(p: Path) -> Table:
    with p.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise LoadError(f"{p}: top-level JSON must be an array of objects")
    return [dict(row) for row in data]


def _load_jsonl(p: Path) -> Table:
    rows = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def table_name_from_path(path: str) -> str:
    """`examples/employees.csv` -> `employees`, used so `FROM employees` reads naturally."""
    return Path(path).stem
