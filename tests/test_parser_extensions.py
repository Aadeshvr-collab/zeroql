import unittest

from zeroql.ast_nodes import (
    AggCall,
    Between,
    BinaryOp,
    Comparison,
    Identifier,
    InList,
    IsNull,
    Literal,
    UnaryOp,
)
from zeroql.errors import ParseError
from zeroql.parser import Parser, to_ast


def ast(query: str):
    return to_ast(Parser(query).parse())


class TestDistinctAndAliases(unittest.TestCase):
    def test_distinct_flag(self):
        self.assertTrue(ast("SELECT DISTINCT dept FROM t").distinct)
        self.assertFalse(ast("SELECT dept FROM t").distinct)

    def test_column_alias(self):
        stmt = ast("SELECT name AS employee_name FROM t")
        item = stmt.select_items[0]
        self.assertEqual(item.expr, Identifier("name"))
        self.assertEqual(item.alias, "employee_name")
        self.assertEqual(stmt.columns, ["employee_name"])

    def test_column_without_alias_uses_its_own_name(self):
        stmt = ast("SELECT name FROM t")
        self.assertEqual(stmt.columns, ["name"])
        self.assertIsNone(stmt.select_items[0].alias)


class TestAggregatesAndGroupBy(unittest.TestCase):
    def test_agg_call_parses(self):
        stmt = ast("SELECT COUNT(*) FROM t")
        item = stmt.select_items[0]
        self.assertEqual(item.expr, AggCall(func="COUNT", arg="*"))
        self.assertEqual(stmt.columns, ["COUNT(*)"])

    def test_agg_call_with_column_arg(self):
        stmt = ast("SELECT AVG(salary) AS avg_salary FROM t")
        self.assertEqual(stmt.select_items[0].expr, AggCall(func="AVG", arg="salary"))
        self.assertEqual(stmt.select_items[0].alias, "avg_salary")

    def test_agg_functions_are_case_insensitive(self):
        stmt = ast("SELECT count(*) FROM t")
        self.assertEqual(stmt.select_items[0].expr, AggCall(func="COUNT", arg="*"))

    def test_plain_column_named_like_agg_func_still_works(self):
        # "count" is not a reserved keyword: it's only treated as an
        # aggregate call when immediately followed by "(".
        stmt = ast("SELECT count FROM t")
        self.assertEqual(stmt.select_items[0].expr, Identifier("count"))

    def test_group_by_single_column(self):
        stmt = ast("SELECT dept, COUNT(*) FROM t GROUP BY dept")
        self.assertEqual(stmt.group_by, ["dept"])

    def test_group_by_multiple_columns(self):
        stmt = ast("SELECT a, b FROM t GROUP BY a, b")
        self.assertEqual(stmt.group_by, ["a", "b"])

    def test_having_clause(self):
        stmt = ast("SELECT dept, COUNT(*) FROM t GROUP BY dept HAVING COUNT(*) > 2")
        self.assertIsInstance(stmt.having, Comparison)
        self.assertEqual(stmt.having.left, AggCall(func="COUNT", arg="*"))
        self.assertEqual(stmt.having.right, Literal(2))


class TestExtendedComparisons(unittest.TestCase):
    def test_between(self):
        stmt = ast("SELECT * FROM t WHERE age BETWEEN 30 AND 40")
        self.assertEqual(stmt.where, Between(Identifier("age"), Literal(30), Literal(40)))

    def test_in_list(self):
        stmt = ast("SELECT * FROM t WHERE dept IN ('Eng', 'Research')")
        self.assertEqual(
            stmt.where, InList(Identifier("dept"), [Literal("Eng"), Literal("Research")])
        )

    def test_not_in_list(self):
        stmt = ast("SELECT * FROM t WHERE dept NOT IN ('Eng')")
        self.assertIsInstance(stmt.where, UnaryOp)
        self.assertEqual(stmt.where.op, "NOT")
        self.assertEqual(stmt.where.operand, InList(Identifier("dept"), [Literal("Eng")]))

    def test_is_null(self):
        stmt = ast("SELECT * FROM t WHERE age IS NULL")
        self.assertEqual(stmt.where, IsNull(Identifier("age"), negated=False))

    def test_is_not_null(self):
        stmt = ast("SELECT * FROM t WHERE age IS NOT NULL")
        self.assertEqual(stmt.where, IsNull(Identifier("age"), negated=True))

    def test_between_combines_with_and_correctly(self):
        # "age BETWEEN 1 AND 10 AND active = true" -- the BETWEEN's own AND
        # must not be confused with the outer AND chaining the next comparison.
        stmt = ast("SELECT * FROM t WHERE age BETWEEN 1 AND 10 AND active = true")
        self.assertIsInstance(stmt.where, BinaryOp)
        self.assertEqual(stmt.where.op, "AND")
        self.assertIsInstance(stmt.where.left, Between)
        self.assertEqual(stmt.where.right, Comparison("=", Identifier("active"), Literal(True)))


class TestMultiColumnOrderAndOffset(unittest.TestCase):
    def test_multiple_order_columns(self):
        stmt = ast("SELECT * FROM t ORDER BY dept ASC, age DESC")
        self.assertEqual(len(stmt.order_by_list), 2)
        self.assertEqual(stmt.order_by_list[0].column, "dept")
        self.assertFalse(stmt.order_by_list[0].descending)
        self.assertEqual(stmt.order_by_list[1].column, "age")
        self.assertTrue(stmt.order_by_list[1].descending)
        # first-key back-compat field still populated
        self.assertEqual(stmt.order_by.column, "dept")

    def test_limit_with_offset(self):
        stmt = ast("SELECT * FROM t LIMIT 10 OFFSET 5")
        self.assertEqual(stmt.limit, 10)
        self.assertEqual(stmt.offset, 5)

    def test_limit_without_offset_leaves_it_none(self):
        stmt = ast("SELECT * FROM t LIMIT 10")
        self.assertIsNone(stmt.offset)


class TestNewGrammarParseErrors(unittest.TestCase):
    def test_unterminated_in_list_raises(self):
        with self.assertRaises(ParseError):
            Parser("SELECT * FROM t WHERE dept IN ('Eng'").parse()

    def test_between_missing_and_raises(self):
        with self.assertRaises(ParseError):
            Parser("SELECT * FROM t WHERE age BETWEEN 1 10").parse()

    def test_is_without_null_raises(self):
        with self.assertRaises(ParseError):
            Parser("SELECT * FROM t WHERE age IS 5").parse()

    def test_agg_call_missing_paren_raises(self):
        with self.assertRaises(ParseError):
            Parser("SELECT COUNT * FROM t").parse()


if __name__ == "__main__":
    unittest.main()
