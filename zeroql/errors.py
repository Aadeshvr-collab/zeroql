"""
Error types for ZeroQL.

Every error carries the original query text plus a line/column so the
CLI can print a caret (^) pointing at the exact offending character,
the same way a compiler front-end would.
"""


class ZeroQLError(Exception):
    """Base class for all ZeroQL errors."""

    def __init__(self, message: str, source: str = "", line: int = 1, col: int = 1):
        self.message = message
        self.source = source
        self.line = line
        self.col = col
        super().__init__(self.format())

    def format(self) -> str:
        if not self.source:
            return self.message

        lines = self.source.split("\n")
        idx = max(0, min(self.line - 1, len(lines) - 1))
        bad_line = lines[idx] if lines else ""
        pointer = " " * max(0, self.col - 1) + "^"
        return (
            f"{self.message} (line {self.line}, col {self.col})\n"
            f"    {bad_line}\n"
            f"    {pointer}"
        )


class LexError(ZeroQLError):
    """Raised when the lexer finds a character it can't tokenize."""


class ParseError(ZeroQLError):
    """Raised when the token stream doesn't match the ZeroQL grammar."""


class EvalError(ZeroQLError):
    """Raised at evaluation time: unknown column, bad ORDER BY key, etc."""


class LoadError(ZeroQLError):
    """Raised when a data source file can't be loaded (bad path, bad format)."""
