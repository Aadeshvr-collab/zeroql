"""
Lexer for ZeroQL.

Converts raw query text into a flat list of Tokens. This is the first
stage of the classic three-stage pipeline used throughout the project:

    text  --[lexer]-->  tokens  --[parser]-->  AST  --[evaluator]--> rows

Every token remembers its own (line, col) so downstream errors (in the
parser or evaluator) can still point back at the original source text.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from .errors import LexError


class TokType(Enum):
    SELECT = auto()
    FROM = auto()
    WHERE = auto()
    AND = auto()
    OR = auto()
    NOT = auto()
    ORDER = auto()
    BY = auto()
    ASC = auto()
    DESC = auto()
    LIMIT = auto()
    OFFSET = auto()
    LIKE = auto()
    DISTINCT = auto()
    GROUP = auto()
    HAVING = auto()
    AS = auto()
    IN = auto()
    BETWEEN = auto()
    IS = auto()
    NULL = auto()

    IDENT = auto()
    NUMBER = auto()
    STRING = auto()
    BOOL = auto()

    STAR = auto()
    COMMA = auto()
    LPAREN = auto()
    RPAREN = auto()
    EQ = auto()
    NEQ = auto()
    LT = auto()
    LTE = auto()
    GT = auto()
    GTE = auto()
    SEMI = auto()

    EOF = auto()


KEYWORDS = {
    "select": TokType.SELECT,
    "from": TokType.FROM,
    "where": TokType.WHERE,
    "and": TokType.AND,
    "or": TokType.OR,
    "not": TokType.NOT,
    "order": TokType.ORDER,
    "by": TokType.BY,
    "asc": TokType.ASC,
    "desc": TokType.DESC,
    "limit": TokType.LIMIT,
    "offset": TokType.OFFSET,
    "like": TokType.LIKE,
    "distinct": TokType.DISTINCT,
    "group": TokType.GROUP,
    "having": TokType.HAVING,
    "as": TokType.AS,
    "in": TokType.IN,
    "between": TokType.BETWEEN,
    "is": TokType.IS,
    "null": TokType.NULL,
}


@dataclass(frozen=True)
class Token:
    type: TokType
    value: object
    line: int
    col: int

    def __repr__(self) -> str:  # pragma: no cover - debug convenience
        return f"Token({self.type.name}, {self.value!r}, {self.line}:{self.col})"


class Lexer:
    def __init__(self, source: str):
        self.source = source
        self.pos = 0
        self.line = 1
        self.col = 1

    # -- low level cursor helpers -----------------------------------
    def _peek(self, offset: int = 0) -> str:
        i = self.pos + offset
        return self.source[i] if i < len(self.source) else ""

    def _advance(self) -> str:
        ch = self.source[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def _match(self, ch: str) -> bool:
        if self._peek() == ch:
            self._advance()
            return True
        return False

    # -- public API ---------------------------------------------------
    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        while True:
            self._skip_whitespace()
            if self.pos >= len(self.source):
                tokens.append(Token(TokType.EOF, None, self.line, self.col))
                break
            tok = self._next_token()
            tokens.append(tok)
        return tokens

    # -- internals ------------------------------------------------------
    def _skip_whitespace(self) -> None:
        while self._peek() and self._peek() in " \t\r\n":
            self._advance()
        # -- line comments starting with `--`, purely a developer nicety
        if self._peek() == "-" and self._peek(1) == "-":
            while self._peek() and self._peek() != "\n":
                self._advance()
            self._skip_whitespace()

    def _next_token(self) -> Token:
        line, col = self.line, self.col
        ch = self._peek()

        if ch.isalpha() or ch == "_":
            return self._read_ident_or_keyword(line, col)
        if ch.isdigit():
            return self._read_number(line, col)
        if ch in "'\"":
            return self._read_string(line, col)

        simple = {
            "*": TokType.STAR,
            ",": TokType.COMMA,
            "(": TokType.LPAREN,
            ")": TokType.RPAREN,
            ";": TokType.SEMI,
        }
        if ch in simple:
            self._advance()
            return Token(simple[ch], ch, line, col)

        if ch == "=":
            self._advance()
            return Token(TokType.EQ, "=", line, col)
        if ch == "!":
            self._advance()
            if self._match("="):
                return Token(TokType.NEQ, "!=", line, col)
            raise LexError("Unexpected '!' (did you mean '!='?)", self.source, line, col)
        if ch == "<":
            self._advance()
            if self._match("="):
                return Token(TokType.LTE, "<=", line, col)
            if self._match(">"):
                return Token(TokType.NEQ, "<>", line, col)
            return Token(TokType.LT, "<", line, col)
        if ch == ">":
            self._advance()
            if self._match("="):
                return Token(TokType.GTE, ">=", line, col)
            return Token(TokType.GT, ">", line, col)

        raise LexError(f"Unexpected character {ch!r}", self.source, line, col)

    def _read_ident_or_keyword(self, line: int, col: int) -> Token:
        start = self.pos
        while self._peek() and (self._peek().isalnum() or self._peek() == "_"):
            self._advance()
        text = self.source[start:self.pos]
        lower = text.lower()
        if lower == "true":
            return Token(TokType.BOOL, True, line, col)
        if lower == "false":
            return Token(TokType.BOOL, False, line, col)
        kw = KEYWORDS.get(lower)
        if kw is not None:
            return Token(kw, lower, line, col)
        return Token(TokType.IDENT, text, line, col)

    def _read_number(self, line: int, col: int) -> Token:
        start = self.pos
        seen_dot = False
        while self._peek() and (self._peek().isdigit() or (self._peek() == "." and not seen_dot)):
            if self._peek() == ".":
                seen_dot = True
            self._advance()
        text = self.source[start:self.pos]
        value = float(text) if seen_dot else int(text)
        return Token(TokType.NUMBER, value, line, col)

    def _read_string(self, line: int, col: int) -> Token:
        quote = self._advance()  # consume opening quote
        start = self.pos
        while True:
            if self.pos >= len(self.source):
                raise LexError("Unterminated string literal", self.source, line, col)
            ch = self._peek()
            if ch == quote:
                break
            self._advance()
        text = self.source[start:self.pos]
        self._advance()  # consume closing quote
        return Token(TokType.STRING, text, line, col)
