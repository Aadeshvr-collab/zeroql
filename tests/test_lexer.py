import unittest

from zeroql.errors import LexError
from zeroql.lexer import Lexer, TokType


def types(src: str):
    return [t.type for t in Lexer(src).tokenize()]


class TestLexer(unittest.TestCase):
    def test_keywords_are_case_insensitive(self):
        self.assertEqual(
            types("select * from t"),
            [TokType.SELECT, TokType.STAR, TokType.FROM, TokType.IDENT, TokType.EOF],
        )
        self.assertEqual(types("SELECT")[0], TokType.SELECT)
        self.assertEqual(types("SeLeCt")[0], TokType.SELECT)

    def test_identifier_vs_keyword(self):
        # "ordering" contains "order" as a prefix but must lex as one IDENT
        toks = Lexer("ordering").tokenize()
        self.assertEqual(toks[0].type, TokType.IDENT)
        self.assertEqual(toks[0].value, "ordering")

    def test_numbers_int_and_float(self):
        toks = Lexer("42 3.14").tokenize()
        self.assertEqual((toks[0].type, toks[0].value), (TokType.NUMBER, 42))
        self.assertEqual((toks[1].type, toks[1].value), (TokType.NUMBER, 3.14))
        self.assertIsInstance(toks[0].value, int)
        self.assertIsInstance(toks[1].value, float)

    def test_strings_single_and_double_quoted(self):
        toks = Lexer("'hi' \"there\"").tokenize()
        self.assertEqual((toks[0].type, toks[0].value), (TokType.STRING, "hi"))
        self.assertEqual((toks[1].type, toks[1].value), (TokType.STRING, "there"))

    def test_operators(self):
        self.assertEqual(
            types("= != <> < <= > >="),
            [
                TokType.EQ,
                TokType.NEQ,
                TokType.NEQ,
                TokType.LT,
                TokType.LTE,
                TokType.GT,
                TokType.GTE,
                TokType.EOF,
            ],
        )

    def test_line_comment_is_skipped(self):
        toks = Lexer("SELECT * -- everything\nFROM t").tokenize()
        self.assertEqual([t.type for t in toks[:4]], [TokType.SELECT, TokType.STAR, TokType.FROM, TokType.IDENT])

    def test_line_and_col_tracking_across_newlines(self):
        toks = Lexer("SELECT *\nFROM t").tokenize()
        from_tok = next(t for t in toks if t.type is TokType.FROM)
        self.assertEqual(from_tok.line, 2)
        self.assertEqual(from_tok.col, 1)

    def test_unterminated_string_raises(self):
        with self.assertRaises(LexError):
            Lexer("'unterminated").tokenize()

    def test_bad_character_raises(self):
        with self.assertRaises(LexError):
            Lexer("SELECT # FROM t").tokenize()

    def test_lone_bang_raises(self):
        with self.assertRaises(LexError):
            Lexer("a ! b").tokenize()


if __name__ == "__main__":
    unittest.main()
