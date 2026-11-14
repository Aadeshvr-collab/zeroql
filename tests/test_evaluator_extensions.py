import unittest

from zeroql.errors import EvalError
from zeroql.evaluator import run
from zeroql.parser import Parser, to_ast

TABLE = [
    {"name": "Ada", "dept": "Engineering", "age": 36, "salary": 98000, "bonus": None},
    {"name": "Grace", "dept": "Engineering", "age": 45, "salary": 112000, "bonus": 5000},
    {"name": "Alan", "dept": "Research", "age": 41, "salary": 105000, "bonus": None},
    {"name": "Margaret", "dept": "Research", "age": 58, "salary": 131000, "bonus": 8000},
    {"name": "Barbara", "dept": "Engineering", "age": 39, "salary": 121000, "bonus": 3000},
]


def q(query: str, table=TABLE):
    stmt = to_ast(Parser(query).parse())
    return run(stmt, table)


class TestGroupByAndAggregates(unittest.TestCase):
    def test_count_star_per_group(self):
        rows = q("SELECT dept, COUNT(*) AS n FROM t GROUP BY dept ORDER BY dept")
        self.assertEqual(rows, [{"dept": "Engineering", "n": 3}, {"dept": "Research", "n": 2}])

    def test_count_column_skips_nulls(self):
        rows = q("SELECT dept, COUNT(bonus) AS n FROM t GROUP BY dept ORDER BY dept")
        self.assertEqual(rows, [{"dept": "Engineering", "n": 2}, {"dept": "Research", "n": 1}])

    def test_sum_and_avg(self):
        rows = q("SELECT dept, SUM(salary) AS total, AVG(salary) AS avg FROM t GROUP BY dept ORDER BY dept")
        eng = rows[0]
        self.assertEqual(eng["total"], 98000 + 112000 + 121000)
        self.assertAlmostEqual(eng["avg"], (98000 + 112000 + 121000) / 3)

    def test_min_and_max(self):
        rows = q("SELECT dept, MIN(age) AS youngest, MAX(age) AS oldest FROM t GROUP BY dept ORDER BY dept")
        self.assertEqual(rows[0], {"dept": "Engineering", "youngest": 36, "oldest": 45})

    def test_aggregate_without_group_by_is_one_implicit_group(self):
        rows = q("SELECT COUNT(*) AS n, AVG(age) AS avg_age FROM t")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["n"], 5)

    def test_having_filters_groups(self):
        rows = q("SELECT dept, COUNT(*) AS n FROM t GROUP BY dept HAVING COUNT(*) > 2")
        self.assertEqual(rows, [{"dept": "Engineering", "n": 3}])

    def test_having_can_reference_a_group_column(self):
        rows = q("SELECT dept, COUNT(*) AS n FROM t GROUP BY dept HAVING dept = 'Research'")
        self.assertEqual(rows, [{"dept": "Research", "n": 2}])

    def test_select_column_not_in_group_by_raises(self):
        with self.assertRaises(EvalError):
            q("SELECT name, COUNT(*) FROM t GROUP BY dept")

    def test_select_star_with_group_by_raises(self):
        with self.assertRaises(EvalError):
            q("SELECT * FROM t GROUP BY dept")

    def test_aggregate_in_where_raises(self):
        with self.assertRaises(EvalError):
            q("SELECT * FROM t WHERE COUNT(*) > 1")

    def test_group_by_after_where_filter(self):
        rows = q("SELECT dept, COUNT(*) AS n FROM t WHERE age > 38 GROUP BY dept ORDER BY dept")
        self.assertEqual(rows, [{"dept": "Engineering", "n": 2}, {"dept": "Research", "n": 2}])


class TestDistinct(unittest.TestCase):
    def test_distinct_removes_duplicate_rows(self):
        rows = q("SELECT DISTINCT dept FROM t ORDER BY dept")
        self.assertEqual(rows, [{"dept": "Engineering"}, {"dept": "Research"}])


class TestAliases(unittest.TestCase):
    def test_alias_renames_output_column_but_reads_source(self):
        rows = q("SELECT name AS employee FROM t WHERE dept = 'Research' ORDER BY employee")
        self.assertEqual(rows, [{"employee": "Alan"}, {"employee": "Margaret"}])


class TestBetweenInIsNull(unittest.TestCase):
    def test_between_is_inclusive(self):
        rows = q("SELECT name FROM t WHERE age BETWEEN 39 AND 45 ORDER BY name")
        self.assertEqual({r["name"] for r in rows}, {"Barbara", "Alan", "Grace"})

    def test_in_list(self):
        rows = q("SELECT name FROM t WHERE dept IN ('Research')")
        self.assertEqual({r["name"] for r in rows}, {"Alan", "Margaret"})

    def test_not_in_list(self):
        rows = q("SELECT name FROM t WHERE dept NOT IN ('Research')")
        self.assertEqual({r["name"] for r in rows}, {"Ada", "Grace", "Barbara"})

    def test_is_null(self):
        rows = q("SELECT name FROM t WHERE bonus IS NULL")
        self.assertEqual({r["name"] for r in rows}, {"Ada", "Alan"})

    def test_is_not_null(self):
        rows = q("SELECT name FROM t WHERE bonus IS NOT NULL")
        self.assertEqual({r["name"] for r in rows}, {"Grace", "Margaret", "Barbara"})


class TestMultiColumnOrderAndOffset(unittest.TestCase):
    def test_multi_column_order_by(self):
        rows = q("SELECT name, dept, age FROM t ORDER BY dept ASC, age DESC")
        self.assertEqual(
            [r["name"] for r in rows], ["Grace", "Barbara", "Ada", "Margaret", "Alan"]
        )

    def test_offset_skips_leading_rows(self):
        # salary desc: Margaret(131k), Barbara(121k), Grace(112k), Alan(105k), Ada(98k)
        rows = q("SELECT name FROM t ORDER BY salary DESC LIMIT 2 OFFSET 1")
        self.assertEqual([r["name"] for r in rows], ["Barbara", "Grace"])


if __name__ == "__main__":
    unittest.main()
