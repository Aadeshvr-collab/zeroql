import unittest

from zeroql.ast_nodes import BinaryOp, Comparison, Identifier, Literal, UnaryOp
from zeroql.errors import ParseError
from zeroql.parser import Parser, to_ast


def ast(query: str):
    return to_ast(Parser(query).parse())


class TestParserBasics(unittest.TestCase):
    def test_select_star(self):
        stmt = ast("SELECT * FROM employees")
        self.assertEqual(stmt.columns, ["*"])
        self.assertEqual(stmt.table, "employees")
        self.assertIsNone(stmt.where)

    def test_select_column_list(self):
        stmt = ast("SELECT name, age FROM employees")
        self.assertEqual(stmt.columns, ["name", "age"])

    def test_where_simple_comparison(self):
        stmt = ast("SELECT * FROM t WHERE age > 30")
        self.assertIsInstance(stmt.where, Comparison)
        self.assertEqual(stmt.where.op, ">")
        self.assertEqual(stmt.where.left, Identifier("age"))
        self.assertEqual(stmt.where.right, Literal(30))

    def test_order_by_defaults_to_ascending(self):
        stmt = ast("SELECT * FROM t ORDER BY age")
        self.assertEqual(stmt.order_by.column, "age")
        self.assertFalse(stmt.order_by.descending)

    def test_order_by_desc(self):
        stmt = ast("SELECT * FROM t ORDER BY age DESC")
        self.assertTrue(stmt.order_by.descending)

    def test_limit(self):
        stmt = ast("SELECT * FROM t LIMIT 5")
        self.assertEqual(stmt.limit, 5)

    def test_trailing_semicolon_is_optional(self):
        self.assertEqual(ast("SELECT * FROM t;").table, ast("SELECT * FROM t").table)

    def test_quoted_table_name(self):
        stmt = ast('SELECT * FROM "my file"')
        self.assertEqual(stmt.table, "my file")


class TestPrecedenceAndAmbiguity(unittest.TestCase):
    """
    The naive grammar `expr := expr OP expr` is ambiguous for input like
    `a AND b OR c` -- two different trees satisfy it. These tests pin
    down which one this grammar's layering (or_expr > and_expr) commits
    to, so a future edit can't silently flip operator precedence.
    """

    def test_and_binds_tighter_than_or(self):
        # a AND b OR c  must parse as  (a AND b) OR c
        stmt = ast("SELECT * FROM t WHERE a = 1 AND b = 2 OR c = 3")
        top = stmt.where
        self.assertIsInstance(top, BinaryOp)
        self.assertEqual(top.op, "OR")
        self.assertIsInstance(top.left, BinaryOp)
        self.assertEqual(top.left.op, "AND")
        self.assertEqual(top.left.left, Comparison("=", Identifier("a"), Literal(1)))
        self.assertEqual(top.left.right, Comparison("=", Identifier("b"), Literal(2)))
        self.assertEqual(top.right, Comparison("=", Identifier("c"), Literal(3)))

    def test_parens_override_default_precedence(self):
        # a AND (b OR c) must NOT collapse to the same tree as the unparenthesised form
        stmt = ast("SELECT * FROM t WHERE a = 1 AND (b = 2 OR c = 3)")
        top = stmt.where
        self.assertEqual(top.op, "AND")
        self.assertIsInstance(top.right, BinaryOp)
        self.assertEqual(top.right.op, "OR")

    def test_not_binds_tighter_than_and(self):
        # NOT a AND b  must parse as  (NOT a) AND b, not NOT (a AND b)
        stmt = ast("SELECT * FROM t WHERE NOT a = 1 AND b = 2")
        top = stmt.where
        self.assertEqual(top.op, "AND")
        self.assertIsInstance(top.left, UnaryOp)
        self.assertEqual(top.left.op, "NOT")

    def test_chained_and_is_left_associative_in_value_not_just_shape(self):
        stmt = ast("SELECT * FROM t WHERE a = 1 AND b = 2 AND c = 3")
        top = stmt.where
        self.assertEqual(top.op, "AND")
        self.assertEqual(top.right, Comparison("=", Identifier("c"), Literal(3)))
        self.assertIsInstance(top.left, BinaryOp)
        self.assertEqual(top.left.right, Comparison("=", Identifier("b"), Literal(2)))


class TestParseTreeVsAst(unittest.TestCase):
    def test_parse_tree_has_layers_ast_collapses_away(self):
        tree = Parser("SELECT * FROM t WHERE a = 1").parse()
        where_clause = tree.children[4]
        self.assertEqual(where_clause.rule, "where_clause")
        # concrete tree: where_clause -> or_expr -> and_expr -> not_expr -> comparison
        or_expr = where_clause.children[1]
        self.assertEqual(or_expr.rule, "or_expr")
        and_expr = or_expr.children[0]
        self.assertEqual(and_expr.rule, "and_expr")
        not_expr = and_expr.children[0]
        self.assertEqual(not_expr.rule, "not_expr")

        # the AST skips straight to the Comparison -- no OR/AND/NOT
        # wrapper nodes exist for input that never uses OR, AND, or NOT.
        stmt = to_ast(tree)
        self.assertIsInstance(stmt.where, Comparison)


class TestParseErrors(unittest.TestCase):
    def test_missing_from_raises_with_position(self):
        with self.assertRaises(ParseError) as ctx:
            Parser("SELECT * employees").parse()
        self.assertIn("FROM", str(ctx.exception))

    def test_missing_where_operand_raises(self):
        with self.assertRaises(ParseError):
            Parser("SELECT * FROM t WHERE").parse()

    def test_extra_trailing_tokens_raise(self):
        with self.assertRaises(ParseError):
            Parser("SELECT * FROM t LIMIT 5 6").parse()

    def test_unclosed_paren_raises(self):
        with self.assertRaises(ParseError):
            Parser("SELECT * FROM t WHERE (a = 1").parse()


if __name__ == "__main__":
    unittest.main()
