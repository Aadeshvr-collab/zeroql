"""
AST node types for ZeroQL.

These are deliberately *not* the same shape as the parse tree the
parser builds internally (see parser.py's `--tree` output) — the AST
strips out punctuation tokens (commas, parens, the keywords) and keeps
only what the evaluator actually needs. Run any query with `--tree`
and `--ast` back to back to see the difference concretely.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class Node:
    """Marker base class for every AST node."""


@dataclass
class Identifier(Node):
    name: str


@dataclass
class Literal(Node):
    value: object  # int | float | str | bool | None


@dataclass
class BinaryOp(Node):
    op: str          # "AND" | "OR"
    left: Node
    right: Node


@dataclass
class UnaryOp(Node):
    op: str          # "NOT"
    operand: Node


@dataclass
class Comparison(Node):
    op: str          # "=" "!=" "<" "<=" ">" ">=" "LIKE"
    left: Node
    right: Node


@dataclass
class Between(Node):
    """`expr BETWEEN low AND high` -- inclusive on both ends, the SQL way."""

    expr: Node
    low: Node
    high: Node


@dataclass
class InList(Node):
    """`expr IN (v1, v2, ...)`. `NOT IN` is represented as UnaryOp(NOT, InList(...))."""

    expr: Node
    values: list[Node]


@dataclass
class IsNull(Node):
    """`expr IS NULL` / `expr IS NOT NULL`."""

    expr: Node
    negated: bool = False


@dataclass
class AggCall(Node):
    """An aggregate function call, e.g. `COUNT(*)` or `AVG(salary)`."""

    func: str        # "COUNT" | "SUM" | "AVG" | "MIN" | "MAX"
    arg: str          # a column name, or "*" (COUNT only)


@dataclass
class SelectItem(Node):
    """One entry in the SELECT list: a column or aggregate, plus an optional alias."""

    expr: Node               # Identifier | AggCall
    alias: str | None = None


@dataclass
class OrderBy(Node):
    column: str
    descending: bool = False


@dataclass
class SelectStmt(Node):
    columns: list[str]               # ["*"] means all columns; otherwise display names
    table: str
    select_items: list[SelectItem] = field(default_factory=list)
    distinct: bool = False
    where: Node | None = None
    group_by: list[str] = field(default_factory=list)
    having: Node | None = None
    order_by: OrderBy | None = None            # first sort key, kept for backwards compat
    order_by_list: list[OrderBy] = field(default_factory=list)
    limit: int | None = None
    offset: int | None = None
    source_query: str = field(default="", repr=False, compare=False)


def default_label(expr: Node) -> str:
    """The display/column name for a SELECT item that has no explicit alias."""
    if isinstance(expr, Identifier):
        return expr.name
    if isinstance(expr, AggCall):
        return f"{expr.func}({expr.arg})"
    return repr(expr)  # pragma: no cover - defensive fallback
