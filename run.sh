#!/usr/bin/env bash
# One-command build+run for ZeroQL (nothing to "build" -- pure stdlib Python --
# but this satisfies "build with one command and run locally" and doubles as
# a scripted walkthrough for the demo video).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "error: python3 not found on PATH. ZeroQL needs Python 3.10+ and nothing else." >&2
  exit 1
fi

echo "== ZeroQL :: Zero Dependency challenge entry (track: Parsers) =="
echo

echo "-- 1. Dependency proof (AST-scans every .py file's imports) --"
"$PYTHON" verify_deps.py
echo

echo "-- 2. Unit tests (lexer / parser / evaluator) --"
"$PYTHON" -m unittest discover -s tests
echo

echo "-- 3. Demo query: employees.csv --"
"$PYTHON" main.py examples/employees.csv -q \
  "SELECT name, age, salary FROM employees WHERE dept = 'Engineering' AND age > 30 ORDER BY salary DESC"
echo

echo "-- 4. Demo query: medicines.csv (low stock, prescription-only) --"
"$PYTHON" main.py examples/medicines.csv -q \
  "SELECT name, stock, price FROM medicines WHERE stock < 20 AND prescription_required = true ORDER BY stock"
echo

echo "-- 5. GROUP BY + aggregates + HAVING --"
"$PYTHON" main.py examples/employees.csv -q \
  "SELECT dept, COUNT(*) AS headcount, AVG(salary) AS avg_salary FROM employees GROUP BY dept HAVING COUNT(*) > 1 ORDER BY avg_salary DESC"
echo

echo "-- 6. BETWEEN / IN / IS NULL / DISTINCT --"
"$PYTHON" main.py examples/employees.csv -q \
  "SELECT DISTINCT dept FROM employees WHERE age BETWEEN 35 AND 50 AND dept IN ('Engineering', 'Research')"
echo

echo "-- 7. Same result set, exported as CSV and JSON --"
"$PYTHON" main.py examples/employees.csv --format csv -q "SELECT name, dept FROM employees LIMIT 3"
echo
"$PYTHON" main.py examples/employees.csv --format json -q "SELECT name, dept FROM employees LIMIT 3"
echo

echo "-- 8. Parse tree vs. AST, side by side, for the same query --"
"$PYTHON" main.py examples/employees.csv --tree -q "SELECT name FROM employees WHERE age > 40 AND dept = 'Research'"
echo
"$PYTHON" main.py examples/employees.csv --ast -q "SELECT name FROM employees WHERE age > 40 AND dept = 'Research'"
echo

echo "-- 9. Dropping into the REPL on examples/employees.csv (.exit to quit) --"
exec "$PYTHON" main.py examples/employees.csv
