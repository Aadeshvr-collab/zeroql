#!/usr/bin/env python3
"""
verify_deps.py -- automated "dependency proof" for the Zero Dependency
challenge.

Rather than trusting an empty requirements.txt on its word, this walks
every .py file in the project, parses it with the `ast` module (so
imports inside strings/comments can't fool it the way a grep would),
and checks every imported top-level module name against
`sys.stdlib_module_names`. Anything that isn't stdlib and isn't part
of this project itself is reported as a violation.

Usage:
    python3 verify_deps.py            # scan the current project
    python3 verify_deps.py --root DIR # scan a different tree

Exit code 0 = clean (proof passes). Exit code 1 = a third-party
import was found, or the tree couldn't be parsed.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

EXCLUDE_DIRS = {".git", "__pycache__", ".venv", "venv", "build", "dist"}

# A handful of always-available names that some Python builds omit
# from sys.stdlib_module_names (e.g. private/underscore variants).
# Kept tiny and explicit rather than papering over real gaps.
EXTRA_STDLIB = {"__future__"}


def find_py_files(root: Path):
    for path in sorted(root.rglob("*.py")):
        if not any(part in EXCLUDE_DIRS for part in path.parts):
            yield path


def top_level_local_packages(root: Path) -> set[str]:
    """Any directory directly under root with an __init__.py counts as
    a first-party package (e.g. `zeroql/`), so `import zeroql.cli` is
    correctly treated as local, not third-party."""
    return {
        p.name
        for p in root.iterdir()
        if p.is_dir() and (p / "__init__.py").exists() and p.name not in EXCLUDE_DIRS
    }


def extract_imports(py_file: Path) -> set[str]:
    """Return the set of top-level module names imported by `py_file`,
    found anywhere in the file (including inside try/except and
    functions), via a real AST walk rather than a text search."""
    source = py_file.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(py_file))

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # relative import ("from . import x") -> always local
            if node.module:
                names.add(node.module.split(".")[0])
    return names


def classify(root: Path) -> tuple[dict[str, str], list[Path]]:
    local_packages = top_level_local_packages(root)
    # a script sitting at the project root (main.py, verify_deps.py) is
    # also "this project" even though it isn't a package directory
    local_modules = {p.stem for p in root.glob("*.py")} | local_packages

    stdlib_names = set(sys.stdlib_module_names) | EXTRA_STDLIB
    classification: dict[str, str] = {}
    scanned: list[Path] = []

    for py_file in find_py_files(root):
        scanned.append(py_file)
        for name in extract_imports(py_file):
            if name in classification:
                continue
            if name in local_modules:
                classification[name] = "local"
            elif name in stdlib_names:
                classification[name] = "stdlib"
            else:
                classification[name] = "THIRD-PARTY"

    return classification, scanned


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", default=str(Path(__file__).parent), help="Project root to scan"
    )
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    try:
        classification, scanned = classify(root)
    except SyntaxError as exc:
        print(f"FAIL: could not parse {exc.filename}: {exc}", file=sys.stderr)
        return 1

    print(f"Scanned {len(scanned)} .py file(s) under {root}\n")

    by_kind: dict[str, list[str]] = {"local": [], "stdlib": [], "THIRD-PARTY": []}
    for name, kind in classification.items():
        by_kind[kind].append(name)

    for kind in ("stdlib", "local", "THIRD-PARTY"):
        names = sorted(by_kind[kind])
        if names:
            print(f"[{kind}] ({len(names)})")
            for name in names:
                print(f"  - {name}")
            print()

    if by_kind["THIRD-PARTY"]:
        print("FAIL: third-party imports found -- this violates Zero Dependency rules.")
        return 1

    print(f"PASS: every import across {len(scanned)} file(s) resolves to the")
    print("standard library or to this project's own modules. Zero third-party")
    print("runtime dependencies confirmed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
