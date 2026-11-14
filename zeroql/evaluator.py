"""
Evaluates a SelectStmt AST against an in-memory table (list of dict
rows, see loader.py). This is the "backend" of the pipeline:

    text -> [lexer] -> tokens -> [parser] -> AST -> [evaluator] -> rows

Two pipelines live here:

- The plain pipeline (`_run_plain`): filter -> sort -> offset/limit ->
  project -> distinct. This is unchanged in spirit from the original
  no-GROUP-BY, no-aggregate engine.
- The grouped pipeline (`_run_grouped`): filter -> partition into
  groups -> aggregate each group -> HAVING -> sort -> offset/limit ->
  distinct. Triggered whenever GROUP BY or an aggregate function
  (COUNT/SUM/AVG/MIN/MAX) appears anywhere in SELECT or HAVING.
"""

from __future__ import annotations

import re

from .ast_nodes import (
    AggCall,
    Between,
    BinaryOp,
    Comparison,
    Identifier,
    InList,
    IsNull,
    Literal,
    Node,
    SelectStmt,
    UnaryOp,
    default_label,
)
from .errors import EvalError


def run(stmt: SelectStmt, table: list[dict]) -> list[dict]:
    rows = table
    if stmt.where is not None:
        rows = [r for r in rows if _truthy(_eval(stmt.where, r))]

    if stmt.group_by or _uses_aggregates(stmt):
        if stmt.columns == ["*"]:
            raise EvalError("SELECT * cannot be combined with GROUP BY or aggregate functions")
        return _run_grouped(stmt, rows, table)

    return _run_plain(stmt, rows, table)


def _uses_aggregates(stmt: SelectStmt) -> bool:
    if any(isinstance(item.expr, AggCall) for item in stmt.select_items):
        return True
    return stmt.having is not None and _contains_agg(stmt.having)


# -- plain (non-aggregate) pipeline -------------------------------------
def _run_plain(stmt: SelectStmt, rows: list[dict], table: list[dict]) -> list[dict]:
    # ORDER BY runs on the pre-projection rows (so it can sort by a column
    # that wasn't SELECTed at all), but it should also accept a SELECT
    # alias -- resolve any alias back to its underlying source column.
    alias_to_source = {
        item.alias: item.expr.name
        for item in stmt.select_items
        if item.alias and isinstance(item.expr, Identifier)
    }

    if stmt.order_by_list:
        for ob in reversed(stmt.order_by_list):
            sort_col = alias_to_source.get(ob.column, ob.column)
            _check_column(sort_col, rows)
            rows = sorted(rows, key=lambda r: _sort_key(r.get(sort_col)), reverse=ob.descending)

    offset = stmt.offset or 0
    if offset:
        rows = rows[offset:]
    if stmt.limit is not None:
        rows = rows[: stmt.limit]

    if stmt.columns == ["*"]:
        projected = rows
    else:
        # select_items pairs each output label with its source column, so
        # `SELECT name AS employee_name` reads `name` but emits `employee_name`.
        pairs = [(item.expr.name, item.alias or item.expr.name) for item in stmt.select_items]
        for source_col, _ in pairs:
            _check_column(source_col, table)
        projected = [{label: r.get(source_col) for source_col, label in pairs} for r in rows]

    if stmt.distinct:
        projected = _dedupe(projected)

    return projected


# -- grouped / aggregate pipeline ----------------------------------------
def _run_grouped(stmt: SelectStmt, rows: list[dict], table: list[dict]) -> list[dict]:
    for item in stmt.select_items:
        if isinstance(item.expr, Identifier) and item.expr.name not in stmt.group_by:
            raise EvalError(
                f"Column {item.expr.name!r} must appear in GROUP BY or be used "
                "inside an aggregate function"
            )

    for col in stmt.group_by:
        _check_column(col, table)

    groups: dict[tuple, list[dict]] = {}
    order: list[tuple] = []
    if stmt.group_by:
        for r in rows:
            key = tuple(r.get(c) for c in stmt.group_by)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(r)
    else:
        # aggregates with no GROUP BY -> one implicit group over everything
        groups[()] = rows
        order = [()]

    out_rows: list[dict] = []
    for key in order:
        group_rows = groups[key]
        group_key = dict(zip(stmt.group_by, key))

        out_row: dict = {}
        for item in stmt.select_items:
            label = item.alias or default_label(item.expr)
            if isinstance(item.expr, AggCall):
                out_row[label] = _compute_agg(item.expr.func, item.expr.arg, group_rows)
            else:
                out_row[label] = group_key[item.expr.name]

        if stmt.having is not None and not _truthy(_eval_grouped(stmt.having, group_key, group_rows)):
            continue

        out_rows.append(out_row)

    if stmt.order_by_list:
        for ob in reversed(stmt.order_by_list):
            _check_column(ob.column, out_rows)
            out_rows = sorted(out_rows, key=lambda r: _sort_key(r.get(ob.column)), reverse=ob.descending)

    offset = stmt.offset or 0
    if offset:
        out_rows = out_rows[offset:]
    if stmt.limit is not None:
        out_rows = out_rows[: stmt.limit]

    if stmt.distinct:
        out_rows = _dedupe(out_rows)

    return out_rows


def _compute_agg(func: str, arg: str, rows: list[dict]):
    if func == "COUNT":
        if arg == "*":
            return len(rows)
        return sum(1 for r in rows if r.get(arg) is not None)

    raw_values = [r.get(arg) for r in rows if r.get(arg) is not None]

    if func in ("MIN", "MAX"):
        if not raw_values:
            return None
        return min(raw_values, key=_sort_key) if func == "MIN" else max(raw_values, key=_sort_key)

    numeric: list[float] = []
    for v in raw_values:
        if isinstance(v, bool):
            numeric.append(int(v))
        elif isinstance(v, (int, float)):
            numeric.append(v)
        else:
            try:
                numeric.append(float(v))
            except (TypeError, ValueError):
                pass  # non-numeric values are skipped, same spirit as most SQL engines

    if func == "SUM":
        return sum(numeric) if numeric else 0
    if func == "AVG":
        return (sum(numeric) / len(numeric)) if numeric else None
    raise AssertionError(f"unknown aggregate function {func}")  # pragma: no cover


def _dedupe(rows: list[dict]) -> list[dict]:
    seen: set = set()
    out: list[dict] = []
    for r in rows:
        try:
            key = tuple(r.items())
            hash(key)
        except TypeError:
            key = repr(sorted(r.items(), key=lambda kv: kv[0]))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


# -- helpers -----------------------------------------------------------
def _check_column(col: str, rows: list[dict]) -> None:
    if rows and col not in rows[0]:
        available = ", ".join(rows[0].keys())
        raise EvalError(f"Unknown column {col!r}. Available columns: {available}")


def _sort_key(value):
    # None-safe, and keeps numbers/strings from ever being compared to
    # each other (which would raise TypeError in Python 3).
    if value is None:
        return (0, "")
    if isinstance(value, bool):
        return (1, int(value))
    if isinstance(value, (int, float)):
        return (1, value)
    return (2, str(value))


def _truthy(value) -> bool:
    return bool(value)


def _contains_agg(node: Node) -> bool:
    if isinstance(node, AggCall):
        return True
    if isinstance(node, BinaryOp):
        return _contains_agg(node.left) or _contains_agg(node.right)
    if isinstance(node, UnaryOp):
        return _contains_agg(node.operand)
    if isinstance(node, Comparison):
        return _contains_agg(node.left) or _contains_agg(node.right)
    if isinstance(node, Between):
        return _contains_agg(node.expr) or _contains_agg(node.low) or _contains_agg(node.high)
    if isinstance(node, InList):
        return _contains_agg(node.expr) or any(_contains_agg(v) for v in node.values)
    if isinstance(node, IsNull):
        return _contains_agg(node.expr)
    return False


# -- per-row expression evaluation (WHERE) -------------------------------
def _eval(node: Node, row: dict):
    if isinstance(node, Identifier):
        if node.name not in row:
            available = ", ".join(row.keys())
            raise EvalError(f"Unknown column {node.name!r}. Available columns: {available}")
        return row[node.name]
    if isinstance(node, Literal):
        return node.value
    if isinstance(node, AggCall):
        raise EvalError("Aggregate functions are not allowed in WHERE -- use HAVING instead")
    if isinstance(node, UnaryOp):
        assert node.op == "NOT"
        return not _truthy(_eval(node.operand, row))
    if isinstance(node, BinaryOp):
        if node.op == "AND":
            return _truthy(_eval(node.left, row)) and _truthy(_eval(node.right, row))
        if node.op == "OR":
            return _truthy(_eval(node.left, row)) or _truthy(_eval(node.right, row))
        raise AssertionError(f"unknown boolean op {node.op}")  # pragma: no cover
    if isinstance(node, Comparison):
        left = _eval(node.left, row)
        right = _eval(node.right, row)
        return _compare(node.op, left, right)
    if isinstance(node, Between):
        value = _eval(node.expr, row)
        low = _eval(node.low, row)
        high = _eval(node.high, row)
        return _compare(">=", value, low) and _compare("<=", value, high)
    if isinstance(node, InList):
        value = _eval(node.expr, row)
        return any(_compare("=", value, _eval(v, row)) for v in node.values)
    if isinstance(node, IsNull):
        is_null = _eval(node.expr, row) is None
        return (not is_null) if node.negated else is_null
    raise AssertionError(f"unreachable AST node: {node!r}")  # pragma: no cover


# -- group-level expression evaluation (HAVING) --------------------------
def _eval_grouped(node: Node, group_key: dict, group_rows: list[dict]):
    """Like `_eval`, but Identifiers resolve against the GROUP BY key and
    AggCall nodes are computed directly over the group's raw rows -- so
    `HAVING COUNT(*) > 2` works even if COUNT(*) was never SELECTed."""
    if isinstance(node, Identifier):
        if node.name not in group_key:
            raise EvalError(
                f"Column {node.name!r} in HAVING must appear in GROUP BY or be used "
                "inside an aggregate function"
            )
        return group_key[node.name]
    if isinstance(node, Literal):
        return node.value
    if isinstance(node, AggCall):
        return _compute_agg(node.func, node.arg, group_rows)
    if isinstance(node, UnaryOp):
        assert node.op == "NOT"
        return not _truthy(_eval_grouped(node.operand, group_key, group_rows))
    if isinstance(node, BinaryOp):
        if node.op == "AND":
            return _truthy(_eval_grouped(node.left, group_key, group_rows)) and _truthy(
                _eval_grouped(node.right, group_key, group_rows)
            )
        if node.op == "OR":
            return _truthy(_eval_grouped(node.left, group_key, group_rows)) or _truthy(
                _eval_grouped(node.right, group_key, group_rows)
            )
        raise AssertionError(f"unknown boolean op {node.op}")  # pragma: no cover
    if isinstance(node, Comparison):
        left = _eval_grouped(node.left, group_key, group_rows)
        right = _eval_grouped(node.right, group_key, group_rows)
        return _compare(node.op, left, right)
    if isinstance(node, Between):
        value = _eval_grouped(node.expr, group_key, group_rows)
        low = _eval_grouped(node.low, group_key, group_rows)
        high = _eval_grouped(node.high, group_key, group_rows)
        return _compare(">=", value, low) and _compare("<=", value, high)
    if isinstance(node, InList):
        value = _eval_grouped(node.expr, group_key, group_rows)
        return any(_compare("=", value, _eval_grouped(v, group_key, group_rows)) for v in node.values)
    if isinstance(node, IsNull):
        is_null = _eval_grouped(node.expr, group_key, group_rows) is None
        return (not is_null) if node.negated else is_null
    raise AssertionError(f"unreachable AST node: {node!r}")  # pragma: no cover


def _compare(op: str, left, right) -> bool:
    if op == "LIKE":
        return _like(left, right)

    left, right = _coerce_pair(left, right)
    if op == "=":
        return left == right
    if op == "!=":
        return left != right
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    if op == ">=":
        return left >= right
    raise AssertionError(f"unknown comparison op {op}")  # pragma: no cover


def _coerce_pair(left, right):
    """If one side is numeric and the other is a numeric-looking string,
    compare both as numbers rather than falling back to lexicographic
    string comparison (so `age > 30` behaves even if `age` arrived as
    text from a data source that didn't type-infer it)."""
    if isinstance(left, (int, float)) and not isinstance(left, bool) and isinstance(right, str):
        try:
            right = float(right)
        except ValueError:
            pass
    elif isinstance(right, (int, float)) and not isinstance(right, bool) and isinstance(left, str):
        try:
            left = float(left)
        except ValueError:
            pass
    return left, right


def _like(value, pattern) -> bool:
    """SQL-style LIKE: % matches any run of characters, _ matches exactly one."""
    if value is None:
        return False
    value = str(value)
    pattern = str(pattern)
    regex = "".join(
        ".*" if ch == "%" else "." if ch == "_" else re.escape(ch) for ch in pattern
    )
    return re.fullmatch(regex, value, flags=re.IGNORECASE) is not None
