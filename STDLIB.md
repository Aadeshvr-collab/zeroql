# STDLIB.md

ZeroQL is written in Python 3.10+ and imports **only** the standard
library. This file lists every module that appears anywhere in the
project and what it's used for. It is a manually-written companion to
the automated proof in [`verify_deps.py`](verify_deps.py) — run that
script yourself rather than taking this table's word for it (see
"How this was verified" below).

| Module | Used in | Why |
|---|---|---|
| `__future__` | almost every file | `from __future__ import annotations` — postponed evaluation of type hints, so signatures like `list[Token]` and `Node \| None` work cleanly. |
| `argparse` | `cli.py`, `verify_deps.py` | Parses command-line flags (`-q`, `--tree`, `--ast`, `--version`, `--root`). |
| `ast` | `verify_deps.py` **only** | Parses this project's *own* `.py` source files to extract their `import` statements for the dependency proof. This is a meta use on Claude's own codebase, not part of the ZeroQL language implementation — see "A note on `ast`" below. |
| `csv` | `loader.py` | Reads `.csv` data files (`csv.DictReader`) into row dicts. |
| `dataclasses` | `lexer.py`, `ast_nodes.py`, `parser.py` | `@dataclass` for `Token`, every AST node type, and `ParseNode` — structured data without hand-writing `__init__`/`__eq__`/`__repr__`. |
| `enum` | `lexer.py` | `TokType`, the enum of every token kind the lexer can produce. |
| `io` | `formatter.py` | `io.StringIO` as an in-memory buffer for `csv.writer` output (`--format csv`), avoiding a temp file. |
| `json` | `loader.py`, `formatter.py` | Reads `.json` (array) and `.jsonl` (newline-delimited) data files; serializes query results for `--format json`. |
| `pathlib` | `loader.py`, `verify_deps.py` | Filesystem paths: checking a data file exists, reading it, deriving a default table name from the filename. |
| `re` | `evaluator.py` | Translates a SQL-style `LIKE` pattern (`%`, `_` wildcards) into a regex and matches it. |
| `readline` | `cli.py` (optional) | If present, gives the REPL arrow-key history/line-editing. Imported in a `try`/`except ImportError` because it's POSIX-only in the stdlib (absent on stock Windows Python) — its absence never breaks anything, it just degrades to plain `input()`. |
| `sys` | `cli.py`, `main.py`, `verify_deps.py` | Exit codes, `stderr` output, and (in `verify_deps.py`) `sys.stdlib_module_names` — the actual list this whole proof is checked against. |
| `unittest` | everything under `tests/` | The test framework: 90 tests across the lexer, parser, evaluator, and formatter. |

## A note on `ast`

The one module on this list worth double-checking is `ast` — using
Python's own `ast` module to help *parse ZeroQL queries* would rather
miss the point of a Parsers-track, zero-dependency entry. **It isn't
used for that.** ZeroQL's lexer (`lexer.py`) and recursive-descent
parser (`parser.py`) are hand-written from scratch: no `tokenize`, no
`ast`, no parser-generator, no regex-based tokenizing. `ast` shows up
in exactly one place — `verify_deps.py` — where it's turned on *this
project's own source code* to read off its `import` statements for the
dependency-proof tool. That's a completely different task (static
analysis of Python source) from parsing ZeroQL's SQL-like grammar.

## How this was verified

```bash
python3 verify_deps.py
```

This walks every `.py` file in the repo, parses each one with `ast`,
collects every top-level imported name, and checks each against
`sys.stdlib_module_names` (plus this project's own `zeroql` package,
which is correctly classified as first-party, not third-party). It
exits `0` and prints `PASS` only if every single import resolves to
the standard library or to this project. `run.sh` runs it as step 1
of the demo, and it's cheap enough to run before every commit.
