# ZeroQL

A zero-dependency, hand-rolled SQL-like query engine for CSV/JSON
files — lexer, recursive-descent parser, AST, and evaluator, all
built from scratch on nothing but the Python standard library.

```
SELECT dept, COUNT(*) AS headcount, AVG(salary) AS avg_salary
FROM employees
WHERE age > 30
GROUP BY dept
HAVING COUNT(*) > 1
ORDER BY avg_salary DESC
```

Built for the **🔥 Zero Dependency** challenge (72 hours, standard
library only). **Track: Parsers.**

**Author:** _(add your name / team here before submitting)_

---

## Why a query engine

Grepping and cutting CSV columns by hand gets old fast, and reaching
for `pandas` or `sqlite3`-backed tooling is the opposite of "zero
dependency." ZeroQL is a small, real, useful tool: point it at a
`.csv`/`.json`/`.jsonl` file and query it with a familiar SQL subset,
with nothing to `pip install`. It's also, deliberately, a compact
teaching example of a full lex → parse → evaluate pipeline — the
`--tree` and `--ast` flags below exist specifically to make that
pipeline visible.

## Quickstart

```bash
./run.sh
```

That's the whole "build." There's no compilation step — it checks
`python3` is on your `PATH`, runs the automated dependency proof, runs
the test suite, runs a couple of demo queries against the bundled
example data, prints a parse-tree-vs-AST comparison, and drops you
into an interactive REPL. Requires **Python 3.10+**, nothing else.

Or run it directly:

```bash
python3 main.py examples/employees.csv -q "SELECT * FROM employees LIMIT 3"
```

## Usage

```
zeroql DATA_FILE [-q QUERY] [--tree | --ast] [--format table|csv|json]

  DATA_FILE        a .csv, .json, or .jsonl file
  -q, --query       run one query and exit (omit to start a REPL)
  --tree            print the concrete parse tree instead of running
  --ast             print the reduced AST instead of running
  --format          table (default), csv, or json output
```

**One-shot mode:**

```bash
$ python3 main.py examples/employees.csv \
    -q "SELECT name, age, salary FROM employees WHERE dept = 'Engineering' AND age > 30 ORDER BY salary DESC"
name           | age | salary
---------------+-----+-------
Barbara Liskov | 39  | 121000
Grace Hopper   | 45  | 112000
Ada Lovelace   | 36  | 98000
Dennis Ritchie | 34  | 94000
(4 rows)
```

**REPL mode** (`FROM table` is optional here — it defaults to the
loaded file's name):

```
$ python3 main.py examples/medicines.csv
ZeroQL 1.0.0 -- 10 row(s) loaded from 'medicines'
Type a query ending in a newline (FROM table name is optional -- it defaults
to 'medicines'). Commands: .tree <q>  .ast <q>  .help  .exit

zeroql> SELECT name, stock FROM medicines WHERE stock < 20 AND prescription_required = true ORDER BY stock
name               | stock
-------------------+------
Azithromycin 500mg | 0
Insulin Glargine   | 5
Metformin 500mg    | 8
Amoxicillin 250mg  | 12
Atorvastatin 10mg  | 18
(5 rows)
```

**Query language at a glance:**

- `SELECT col, col AS alias, AGG(col) | *` -- optional column aliases
  (`AS`), optional `DISTINCT`.
- `FROM table`
- `WHERE` with `AND` / `OR` / `NOT` / parentheses,
  `= != < <= > >= LIKE`, `BETWEEN ... AND ...`, `IN (...)` / `NOT IN (...)`,
  `IS NULL` / `IS NOT NULL`.
- `GROUP BY col, col ...` with aggregate functions `COUNT(*)`,
  `COUNT(col)`, `SUM(col)`, `AVG(col)`, `MIN(col)`, `MAX(col)`.
- `HAVING expr` -- filters on aggregates *after* grouping (unlike
  `WHERE`, which can't see aggregate results); can reference
  `COUNT(*)` etc. directly even if it wasn't SELECTed.
- `ORDER BY col [ASC|DESC], col [ASC|DESC], ...` -- multiple sort keys,
  can reference a `SELECT ... AS alias`.
- `LIMIT n [OFFSET m]`.

Aggregate function names (`COUNT`, `SUM`, `AVG`, `MIN`, `MAX`) are
**not** reserved keywords -- they're recognized contextually (an
identifier immediately followed by `(`), so a genuine column named
e.g. `count` still lexes and parses as a plain column reference.

Numeric-looking columns from CSV are type-inferred, so `age > 30`
compares numerically even though CSV only stores text.

**More examples:**

```bash
$ python3 main.py examples/employees.csv -q \
    "SELECT dept, COUNT(*) AS headcount, AVG(salary) AS avg_salary FROM employees GROUP BY dept HAVING COUNT(*) > 1 ORDER BY avg_salary DESC"
dept        | headcount | avg_salary
------------+-----------+------------------
Research    | 5         | 111600.0
Engineering | 5         | 102800.0
(2 rows)

$ python3 main.py examples/employees.csv -q \
    "SELECT DISTINCT dept FROM employees WHERE age BETWEEN 35 AND 50 AND dept IN ('Engineering', 'Research')"
dept
------------
Engineering
Research
(2 rows)

$ python3 main.py examples/employees.csv --format csv -q \
    "SELECT name, dept FROM employees ORDER BY dept, name LIMIT 3"
name,dept
Ada Lovelace,Engineering
Barbara Liskov,Engineering
Dennis Ritchie,Engineering
```

## Architecture: parse tree vs. AST

The whole pipeline is the classic four stages:

```
query text --[lexer.py]--> tokens --[parser.py]--> parse tree --[to_ast()]--> AST --[evaluator.py]--> rows
```

`parser.py` deliberately keeps two distinct structures rather than
collapsing straight to one:

- **Parse tree** (`ParseNode`) — the *concrete* derivation: one node
  for every grammar rule that fired, including the ones that only
  ever pass a single child through.
- **AST** (`ast_nodes.py`) — the *abstract* tree the evaluator
  actually walks, with all of that pass-through scaffolding reduced
  away.

Run the same query both ways to see the difference concretely:

```
$ python3 main.py examples/employees.csv --tree -q "SELECT name FROM employees WHERE age > 40 AND dept = 'Research'"
select_stmt
  'select'  [SELECT]
  select_list
    select_item
      column_ref
        'name'  [IDENT]
  'from'  [FROM]
  table_ref
    'employees'  [IDENT]
  where_clause
    'where'  [WHERE]
    or_expr
      and_expr
        not_expr
          comparison
            operand
              'age'  [IDENT]
            '>'  [GT]
            operand
              '40'  [NUMBER]
        'and'  [AND]
        not_expr
          comparison
            operand
              'dept'  [IDENT]
            '='  [EQ]
            operand
              'Research'  [STRING]

$ python3 main.py examples/employees.csv --ast -q "SELECT name FROM employees WHERE age > 40 AND dept = 'Research'"
SelectStmt columns=[name] table='employees'
  where:
    BinaryOp(AND)
      Comparison(>)
        Identifier(age)
        Literal(40)
      Comparison(=)
        Identifier(dept)
        Literal('Research')
```

The parse tree carries an `or_expr` and a `where_clause` wrapper even
though this query never uses `OR` — that scaffolding exists because
the *grammar* always invokes those rules, whether or not they end up
mattering for this particular input. `to_ast()` (in `parser.py`)
throws that away and keeps only what the evaluator needs.

### Resolving ambiguity by layering the grammar

A naive grammar for boolean expressions, `expr := expr OP expr`, is
ambiguous: `a AND b OR c` has two different valid parse trees under
it — `(a AND b) OR c` and `a AND (b OR c)` are both grammatical. With
no parser-generator available (stdlib only) to hand that ambiguity
to, it's resolved the standard way: by splitting one ambiguous rule
into a chain of unambiguous ones, ordered by precedence —

```
or_expr := and_expr (OR and_expr)*
and_expr := not_expr (AND not_expr)*
not_expr := NOT not_expr | comparison
```

— so `AND` always binds tighter than `OR` by construction, and
parentheses (`operand := "(" expr ")"`) let a query override that
default explicitly. `tests/test_parser.py::TestPrecedenceAndAmbiguity`
pins this down with concrete before/after trees so a future edit can't
silently flip precedence without a test failing.

## Grammar (EBNF)

```
select_stmt   := SELECT DISTINCT? select_list FROM table_ref
                  where? group_clause? having_clause? order_clause? limit_clause? ";"?
select_list   := "*" | select_item ("," select_item)*
select_item   := (agg_call | IDENT) (AS IDENT)?
agg_call      := AGGFUNC "(" ("*" | IDENT) ")"
                  -- AGGFUNC in {COUNT, SUM, AVG, MIN, MAX}, case-insensitive,
                  -- not reserved: recognized contextually (IDENT immediately
                  -- followed by "(") so a column literally named "count"
                  -- still parses as a plain column reference.
table_ref     := IDENT | STRING
where_clause  := WHERE expr
group_clause  := GROUP BY IDENT ("," IDENT)*
having_clause := HAVING expr
order_clause  := ORDER BY order_item ("," order_item)*
order_item    := IDENT (ASC | DESC)?
limit_clause  := LIMIT NUMBER (OFFSET NUMBER)?

expr          := or_expr
or_expr       := and_expr (OR and_expr)*
and_expr      := not_expr (AND not_expr)*
not_expr      := NOT not_expr | comparison
comparison    := operand ( comp_op operand
                          | BETWEEN operand AND operand
                          | NOT IN in_list
                          | IN in_list
                          | IS NOT? NULL
                          )?
in_list       := "(" operand ("," operand)* ")"
comp_op       := "=" | "!=" | "<" | "<=" | ">" | ">=" | LIKE
operand       := agg_call | IDENT | NUMBER | STRING | BOOL | "(" expr ")"
```

`to_ast()` walks a `select_stmt`'s children by rule/token type rather
than fixed index, since the optional clauses (`DISTINCT`, `GROUP BY`,
`HAVING`, ...) shift later children around depending on which ones are
present in a given query.

## Project layout

```
zeroql/
├── main.py              entry point: python3 main.py <file> [-q "..."]
├── run.sh                one-command demo (proof + tests + queries + REPL)
├── verify_deps.py         dependency-proof script (see STDLIB.md)
├── requirements.txt       intentionally empty
├── STDLIB.md              which stdlib modules are used, and why
├── zeroql/
│   ├── lexer.py           text -> tokens
│   ├── parser.py          tokens -> parse tree -> AST (grammar lives here)
│   ├── ast_nodes.py        AST node dataclasses
│   ├── evaluator.py        AST -> result rows (plain + GROUP BY/aggregate pipelines)
│   ├── loader.py           CSV/JSON/JSONL -> in-memory table, type inference
│   ├── formatter.py         result rows -> table / CSV / JSON
│   ├── cli.py               argparse + REPL
│   └── errors.py            error types with line/col + caret formatting
├── tests/                 90 unittest cases across lexer/parser/evaluator/formatter
└── examples/               employees.csv, medicines.csv
```

## Testing

```bash
python3 -m unittest discover -s tests -v
```

90 tests: lexer tokenization (keywords, literals, operators, line
comments, position tracking, malformed input); parser AST shape,
including the AND/OR/NOT precedence tests, the newer `GROUP BY` /
`HAVING` / aggregate / `BETWEEN` / `IN` / `IS NULL` grammar, and their
parse-error cases; evaluator correctness (filtering, projection,
multi-column `ORDER BY`, `LIMIT`/`OFFSET`, `LIKE`, `DISTINCT`,
aliases, numeric type coercion, grouping + aggregates + `HAVING`,
unknown-column errors); and formatter round-trips for table/CSV/JSON
output.

## Dependency proof

```bash
python3 verify_deps.py
```

AST-parses every `.py` file in the repo (using Python's own `ast`
module — see the "A note on `ast`" section of `STDLIB.md` for why that
doesn't undercut a from-scratch parser) and checks every imported
top-level name against `sys.stdlib_module_names`. Exits `0`/`PASS`
only if everything resolves to the standard library or to this
project's own `zeroql` package. Full module-by-module rationale is in
[`STDLIB.md`](STDLIB.md).

## Error handling

Errors point at the exact character, the way a compiler front-end
would:

```
$ python3 main.py examples/employees.csv -q "SELECT name employees"
error: Expected FROM, found 'employees' (line 1, col 13)
    SELECT name employees
                ^
```

The evaluator also gives SQL-shaped semantic errors, not just parse
errors — e.g. using an aggregate where it isn't allowed, or selecting
a bare column that isn't part of the `GROUP BY`:

```
$ python3 main.py examples/employees.csv -q "SELECT * FROM employees WHERE COUNT(*) > 1"
error: Aggregate functions are not allowed in WHERE -- use HAVING instead

$ python3 main.py examples/employees.csv -q "SELECT name, COUNT(*) FROM employees GROUP BY dept"
error: Column 'name' must appear in GROUP BY or be used inside an aggregate function
```

## Known limitations

Scoped deliberately for a 72-hour, single-file-grammar entry:

- No `JOIN` across multiple tables/files.
- No nested/derived-table subqueries (`FROM (SELECT ...)`).
- One statement per query/REPL line; no multi-statement scripts.
- Whole file is loaded into memory — fine for hackathon-sized data,
  not a streaming engine.
- `GROUP BY` keys must be plain columns (no `GROUP BY` on an
  expression), and `HAVING`/`SELECT` items must be either grouped
  columns or aggregate calls — the same restriction real SQL engines
  enforce.

None of these are hard blockers on the design (the grammar in
`parser.py` is the natural place to extend), they just weren't in
scope for the window. `GROUP BY`, aggregate functions, `HAVING`,
`DISTINCT`, `BETWEEN`/`IN`/`IS NULL`, multi-column `ORDER BY`,
`LIMIT ... OFFSET`, column aliases, and CSV/JSON output all *were*
originally on this list and have since been implemented.

## Rules checklist

- [x] Real, useful, working software project
- [x] Standard library only — see `STDLIB.md` and `verify_deps.py`
- [x] `requirements.txt` empty
- [x] No vendored/copied third-party code
- [x] Software only
- [x] Builds and runs locally with one command (`./run.sh`)
- [x] Track: **Parsers**
- [x] `README.md` (this file) + `STDLIB.md` + dependency proof (`verify_deps.py`)
