import unittest

from zeroql.errors import EvalError
from zeroql.evaluator import run
from zeroql.parser import Parser, to_ast

TABLE = [
    {"name": "Ada", "dept": "Engineering", "age": 36, "active": True},
    {"name": "Grace", "dept": "Engineering", "age": 45, "active": True},
    {"name": "Alan", "dept": "Research", "age": 41, "active": False},
    {"name": "Margaret", "dept": "Research", "age": 58, "active": True},
]


def q(query: str, table=TABLE):
    stmt = to_ast(Parser(query).parse())
    return run(stmt, table)


class TestSelectAndWhere(unittest.TestCase):
    def test_select_star_returns_all_columns(self):
        rows = q("SELECT * FROM t")
        self.assertEqual(len(rows), 4)
        self.assertEqual(set(rows[0].keys()), {"name", "dept", "age", "active"})

    def test_projection_limits_columns(self):
        rows = q("SELECT name, age FROM t")
        self.assertEqual(set(rows[0].keys()), {"name", "age"})

    def test_numeric_comparison(self):
        rows = q("SELECT name FROM t WHERE age > 40")
        self.assertEqual({r["name"] for r in rows}, {"Grace", "Alan", "Margaret"})

    def test_string_equality(self):
        rows = q("SELECT name FROM t WHERE dept = 'Research'")
        self.assertEqual({r["name"] for r in rows}, {"Alan", "Margaret"})

    def test_and_or_combination_matches_precedence(self):
        # dept = 'Engineering' AND age > 40 OR dept = 'Research'
        # == (dept = 'Engineering' AND age > 40) OR dept = 'Research'
        rows = q("SELECT name FROM t WHERE dept = 'Engineering' AND age > 40 OR dept = 'Research'")
        self.assertEqual({r["name"] for r in rows}, {"Grace", "Alan", "Margaret"})

    def test_not(self):
        rows = q("SELECT name FROM t WHERE NOT active = true")
        self.assertEqual({r["name"] for r in rows}, {"Alan"})

    def test_like_wildcard(self):
        rows = q("SELECT name FROM t WHERE name LIKE 'A%'")
        self.assertEqual({r["name"] for r in rows}, {"Ada", "Alan"})

    def test_like_single_char_wildcard(self):
        rows = q("SELECT name FROM t WHERE name LIKE 'Ad_'")
        self.assertEqual({r["name"] for r in rows}, {"Ada"})

    def test_unknown_column_raises(self):
        with self.assertRaises(EvalError):
            q("SELECT * FROM t WHERE nonexistent = 1")


class TestOrderByAndLimit(unittest.TestCase):
    def test_order_by_ascending_default(self):
        rows = q("SELECT name FROM t ORDER BY age")
        self.assertEqual([r["name"] for r in rows], ["Ada", "Alan", "Grace", "Margaret"])

    def test_order_by_descending(self):
        rows = q("SELECT name FROM t ORDER BY age DESC")
        self.assertEqual([r["name"] for r in rows], ["Margaret", "Grace", "Alan", "Ada"])

    def test_limit_applies_after_order(self):
        rows = q("SELECT name FROM t ORDER BY age DESC LIMIT 2")
        self.assertEqual([r["name"] for r in rows], ["Margaret", "Grace"])


class TestTypeCoercion(unittest.TestCase):
    def test_numeric_string_column_compares_numerically(self):
        # simulate a column that arrived as un-inferred text, e.g. "41"
        table = [{"age": "41"}, {"age": "9"}, {"age": "100"}]
        rows = q("SELECT age FROM t WHERE age > 40", table=table)
        # lexicographic string comparison would wrongly exclude "100" > "40"
        # being false ("100" < "40" as strings) -- numeric coercion fixes this
        self.assertEqual({r["age"] for r in rows}, {"41", "100"})


if __name__ == "__main__":
    unittest.main()
