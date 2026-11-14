"""
Command-line interface for ZeroQL.

    zeroql DATA_FILE -q "SELECT ..."               one-shot query
    zeroql DATA_FILE                                interactive REPL
    zeroql DATA_FILE -q "..." --tree                show the concrete parse tree
    zeroql DATA_FILE -q "..." --ast                 show the reduced AST
    zeroql DATA_FILE -q "..." --format csv|json     machine-readable output

Only argparse, sys, and (optionally) readline from the standard
library are used here -- see STDLIB.md for the full inventory.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .errors import ZeroQLError
from .evaluator import run
from .formatter import FORMATTERS
from .loader import load_table, table_name_from_path
from .parser import Parser, dump_ast, to_ast

try:  # pragma: no cover - readline is POSIX-only in the stdlib
    import readline  # noqa: F401
except ImportError:
    pass


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="zeroql",
        description="A zero-dependency, hand-rolled SQL-like query engine for CSV/JSON files.",
    )
    p.add_argument("data_file", help="Path to a .csv, .json, or .jsonl file")
    p.add_argument("-q", "--query", help="Run a single query and exit (default: start a REPL)")
    p.add_argument(
        "--tree", action="store_true", help="Print the concrete parse tree instead of running"
    )
    p.add_argument(
        "--ast", action="store_true", help="Print the reduced AST instead of running"
    )
    p.add_argument(
        "--format",
        choices=sorted(FORMATTERS),
        default="table",
        help="Output format for query results (default: table)",
    )
    p.add_argument("--version", action="version", version=f"zeroql {__version__}")
    return p


def _run_query(query: str, table: list[dict], show_tree: bool, show_ast: bool, fmt: str) -> str:
    parse_tree = Parser(query).parse()
    if show_tree:
        return parse_tree.dump()

    stmt = to_ast(parse_tree, source_query=query)
    if show_ast:
        return dump_ast(stmt)

    rows = run(stmt, table)
    return FORMATTERS[fmt](rows)


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    try:
        table = load_table(args.data_file)
    except ZeroQLError as exc:
        print(f"error: {exc.format()}", file=sys.stderr)
        return 1

    table_name = table_name_from_path(args.data_file)

    if args.query:
        try:
            print(_run_query(args.query, table, args.tree, args.ast, args.format))
        except ZeroQLError as exc:
            print(f"error: {exc.format()}", file=sys.stderr)
            return 1
        return 0

    return _repl(table, table_name, default_tree=args.tree, default_ast=args.ast, fmt=args.format)


def _repl(table: list[dict], table_name: str, default_tree: bool, default_ast: bool, fmt: str) -> int:
    print(f"ZeroQL {__version__} -- {len(table)} row(s) loaded from '{table_name}'")
    print("Type a query ending in a newline (FROM table name is optional -- it defaults")
    print(f"to '{table_name}'). Commands: .tree <q>  .ast <q>  .help  .exit\n")

    while True:
        try:
            line = input("zeroql> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not line:
            continue
        if line in (".exit", ".quit"):
            return 0
        if line == ".help":
            print("Commands: .tree <query>   .ast <query>   .help   .exit")
            print(f"Bare SELECT statements run against '{table_name}'.")
            continue

        show_tree, show_ast = default_tree, default_ast
        if line.startswith(".tree "):
            show_tree, line = True, line[len(".tree "):]
        elif line.startswith(".ast "):
            show_ast, line = True, line[len(".ast "):]

        query = _with_default_table(line, table_name)
        try:
            print(_run_query(query, table, show_tree, show_ast, fmt))
        except ZeroQLError as exc:
            print(exc.format())
        print()


def _with_default_table(query: str, table_name: str) -> str:
    """Let the REPL user write `SELECT * WHERE x` and skip `FROM table`."""
    if " from " in f" {query.lower()} ":
        return query
    stripped = query.rstrip(";").rstrip()
    return f"{stripped} FROM {table_name}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
