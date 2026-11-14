"""
Recursive-descent parser for ZeroQL.

Grammar (EBNF)
--------------
    select_stmt   := SELECT DISTINCT? select_list FROM table_ref
                      where? group_clause? having_clause? order_clause? limit_clause? ";"?
    select_list   := "*" | select_item ("," select_item)*
    select_item   := (agg_call | IDENT) (AS IDENT)?
    agg_call      := AGGFUNC "(" ("*" | IDENT) ")"
                      -- AGGFUNC in {COUNT, SUM, AVG, MIN, MAX}, case-insensitive.
                      -- Not reserved keywords: recognized contextually (IDENT
                      -- directly followed by "("), so a plain column named
                      -- e.g. "count" still lexes and parses as an ordinary IDENT.
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

Two data structures come out of this file, deliberately kept distinct:

1. ParseNode  -- the *concrete* parse tree. It has one node for every
   grammar rule that fires, even the ones that only ever pass a single
   child through (e.g. `or_expr` when there is no `OR` in sight). This
   is what a parser generator would hand you.

2. The AST (ast_nodes.py) -- the *abstract* syntax tree. `to_ast()`
   walks the ParseNode tree and collapses all of that pass-through
   scaffolding away, so `a AND b OR c` becomes a two-level BinaryOp
   tree instead of a five-level chain of single-child rule nodes.

Precedence/ambiguity note: the naive grammar `expr := expr OP expr`
is ambiguous -- `a AND b OR c` has two different parse trees under it
(is it `(a AND b) OR c` or `a AND (b OR c)`?). Standard-library-only
means no parser-generator to hand that ambiguity to, so it's resolved
the classic way: by layering the grammar itself into precedence levels
(or_expr > and_expr > not_expr > comparison), the same technique used
to disambiguate arithmetic expression grammars for + vs *.

`to_ast()` is written to scan a select_stmt's children by rule/token
type rather than by fixed index, since optional clauses (DISTINCT,
GROUP BY, HAVING, ...) can appear or not, shifting positions around.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .ast_nodes import (
    AggCall,
    Between,
    BinaryOp,
    Comparison,
    Identifier,
    InList,
    IsNull,
    Literal,
    Node,
    OrderBy,
    SelectItem,
    SelectStmt,
    UnaryOp,
    default_label,
)
from .errors import ParseError
from .lexer import Lexer, Token, TokType

COMPARISON_OPS = {
    TokType.EQ: "=",
    TokType.NEQ: "!=",
    TokType.LT: "<",
    TokType.LTE: "<=",
    TokType.GT: ">",
    TokType.GTE: ">=",
    TokType.LIKE: "LIKE",
}

AGG_FUNCS = {"count", "sum", "avg", "min", "max"}


@dataclass
class ParseNode:
    """A node in the *concrete* parse tree (see module docstring)."""

    rule: str
    children: list["ParseNode | Token"] = field(default_factory=list)

    def dump(self, indent: int = 0) -> str:
        pad = "  " * indent
        lines = [f"{pad}{self.rule}"]
        for child in self.children:
            if isinstance(child, ParseNode):
                lines.append(child.dump(indent + 1))
            else:
                lines.append(f"{pad}  '{child.value}'  [{child.type.name}]")
        return "\n".join(lines)


class Parser:
    def __init__(self, source: str):
        self.source = source
        self.tokens = Lexer(source).tokenize()
        self.pos = 0

    # -- token cursor -------------------------------------------------
    def _peek(self) -> Token:
        return self.tokens[self.pos]

    def _peek_ahead(self, offset: int) -> Token:
        idx = self.pos + offset
        if idx < len(self.tokens):
            return self.tokens[idx]
        return self.tokens[-1]  # EOF

    def _at(self, *types: TokType) -> bool:
        return self._peek().type in types

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.type is not TokType.EOF:
            self.pos += 1
        return tok

    def _expect(self, type_: TokType, what: str) -> Token:
        if not self._at(type_):
            tok = self._peek()
            raise ParseError(
                f"Expected {what}, found {tok.value!r}", self.source, tok.line, tok.col
            )
        return self._advance()

    # -- public API -----------------------------------------------------
    def parse(self) -> ParseNode:
        """Parse a single statement and return the concrete parse tree."""
        tree = self._select_stmt()
        if not self._at(TokType.EOF):
            tok = self._peek()
            raise ParseError(
                f"Unexpected trailing input {tok.value!r}", self.source, tok.line, tok.col
            )
        return tree

    # -- grammar rules, one method per production ----------------------
    def _select_stmt(self) -> ParseNode:
        children: list[ParseNode | Token] = [self._expect(TokType.SELECT, "SELECT")]
        if self._at(TokType.DISTINCT):
            children.append(self._advance())
        children.append(self._select_list())
        children.append(self._expect(TokType.FROM, "FROM"))
        children.append(self._table_ref())

        if self._at(TokType.WHERE):
            children.append(self._where_clause())
        if self._at(TokType.GROUP):
            children.append(self._group_clause())
        if self._at(TokType.HAVING):
            children.append(self._having_clause())
        if self._at(TokType.ORDER):
            children.append(self._order_clause())
        if self._at(TokType.LIMIT):
            children.append(self._limit_clause())
        if self._at(TokType.SEMI):
            children.append(self._advance())

        return ParseNode("select_stmt", children)

    def _select_list(self) -> ParseNode:
        if self._at(TokType.STAR):
            return ParseNode("select_list", [self._advance()])
        children: list[ParseNode | Token] = [self._select_item()]
        while self._at(TokType.COMMA):
            children.append(self._advance())  # comma, kept for tree fidelity
            children.append(self._select_item())
        return ParseNode("select_list", children)

    def _is_agg_call_start(self) -> bool:
        tok = self._peek()
        return (
            tok.type is TokType.IDENT
            and isinstance(tok.value, str)
            and tok.value.lower() in AGG_FUNCS
            and self._peek_ahead(1).type is TokType.LPAREN
        )

    def _agg_call(self) -> ParseNode:
        func_tok = self._advance()  # IDENT naming the function
        lp = self._advance()  # LPAREN
        if self._at(TokType.STAR):
            arg = self._advance()
        else:
            arg = self._expect(TokType.IDENT, "a column name or '*'")
        rp = self._expect(TokType.RPAREN, "')'")
        return ParseNode("agg_call", [func_tok, lp, arg, rp])

    def _select_item(self) -> ParseNode:
        if self._is_agg_call_start():
            expr_node = self._agg_call()
        else:
            col = self._expect(TokType.IDENT, "a column name")
            expr_node = ParseNode("column_ref", [col])
        children: list[ParseNode | Token] = [expr_node]
        if self._at(TokType.AS):
            children.append(self._advance())
            children.append(self._expect(TokType.IDENT, "an alias name"))
        return ParseNode("select_item", children)

    def _table_ref(self) -> ParseNode:
        if self._at(TokType.IDENT, TokType.STRING):
            return ParseNode("table_ref", [self._advance()])
        tok = self._peek()
        raise ParseError(
            f"Expected a table/file name, found {tok.value!r}", self.source, tok.line, tok.col
        )

    def _where_clause(self) -> ParseNode:
        kw = self._advance()  # WHERE
        return ParseNode("where_clause", [kw, self._expr()])

    def _group_clause(self) -> ParseNode:
        group_kw = self._advance()  # GROUP
        by_kw = self._expect(TokType.BY, "BY")
        children: list[ParseNode | Token] = [
            group_kw,
            by_kw,
            self._expect(TokType.IDENT, "a column name"),
        ]
        while self._at(TokType.COMMA):
            children.append(self._advance())
            children.append(self._expect(TokType.IDENT, "a column name"))
        return ParseNode("group_clause", children)

    def _having_clause(self) -> ParseNode:
        kw = self._advance()  # HAVING
        return ParseNode("having_clause", [kw, self._expr()])

    def _order_clause(self) -> ParseNode:
        order_kw = self._advance()  # ORDER
        by_kw = self._expect(TokType.BY, "BY")
        children: list[ParseNode | Token] = [order_kw, by_kw, self._order_item()]
        while self._at(TokType.COMMA):
            children.append(self._advance())
            children.append(self._order_item())
        return ParseNode("order_clause", children)

    def _order_item(self) -> ParseNode:
        col = self._expect(TokType.IDENT, "a column name")
        children: list[ParseNode | Token] = [col]
        if self._at(TokType.ASC, TokType.DESC):
            children.append(self._advance())
        return ParseNode("order_item", children)

    def _limit_clause(self) -> ParseNode:
        kw = self._advance()  # LIMIT
        num = self._expect(TokType.NUMBER, "a number")
        children: list[ParseNode | Token] = [kw, num]
        if self._at(TokType.OFFSET):
            children.append(self._advance())
            children.append(self._expect(TokType.NUMBER, "a number"))
        return ParseNode("limit_clause", children)

    # -- expression grammar, precedence climbing via rule layering -----
    def _expr(self) -> ParseNode:
        return self._or_expr()

    def _or_expr(self) -> ParseNode:
        left = self._and_expr()
        children: list[ParseNode | Token] = [left]
        while self._at(TokType.OR):
            children.append(self._advance())
            children.append(self._and_expr())
        return ParseNode("or_expr", children)

    def _and_expr(self) -> ParseNode:
        left = self._not_expr()
        children: list[ParseNode | Token] = [left]
        while self._at(TokType.AND):
            children.append(self._advance())
            children.append(self._not_expr())
        return ParseNode("and_expr", children)

    def _not_expr(self) -> ParseNode:
        if self._at(TokType.NOT):
            kw = self._advance()
            return ParseNode("not_expr", [kw, self._not_expr()])
        return ParseNode("not_expr", [self._comparison()])

    def _comparison(self) -> ParseNode:
        left = self._operand()
        children: list[ParseNode | Token] = [left]

        if self._peek().type in COMPARISON_OPS:
            children.append(self._advance())
            children.append(self._operand())
            return ParseNode("comparison", children)

        if self._at(TokType.BETWEEN):
            children.append(self._advance())
            children.append(self._operand())
            children.append(self._expect(TokType.AND, "AND"))
            children.append(self._operand())
            return ParseNode("comparison", children)

        if self._at(TokType.NOT) and self._peek_ahead(1).type is TokType.IN:
            children.append(self._advance())  # NOT
            children.append(self._advance())  # IN
            children.append(self._in_list())
            return ParseNode("comparison", children)

        if self._at(TokType.IN):
            children.append(self._advance())
            children.append(self._in_list())
            return ParseNode("comparison", children)

        if self._at(TokType.IS):
            children.append(self._advance())
            if self._at(TokType.NOT):
                children.append(self._advance())
            children.append(self._expect(TokType.NULL, "NULL"))
            return ParseNode("comparison", children)

        return ParseNode("comparison", children)

    def _in_list(self) -> ParseNode:
        lp = self._expect(TokType.LPAREN, "'('")
        children: list[ParseNode | Token] = [lp, self._operand()]
        while self._at(TokType.COMMA):
            children.append(self._advance())
            children.append(self._operand())
        children.append(self._expect(TokType.RPAREN, "')'"))
        return ParseNode("in_list", children)

    def _operand(self) -> ParseNode:
        if self._is_agg_call_start():
            return ParseNode("operand", [self._agg_call()])
        tok = self._peek()
        if tok.type in (TokType.IDENT, TokType.NUMBER, TokType.STRING, TokType.BOOL):
            return ParseNode("operand", [self._advance()])
        if tok.type is TokType.LPAREN:
            lp = self._advance()
            inner = self._expr()
            rp = self._expect(TokType.RPAREN, "')'")
            return ParseNode("operand", [lp, inner, rp])
        raise ParseError(
            f"Expected a column, literal, or '(', found {tok.value!r}",
            self.source,
            tok.line,
            tok.col,
        )


# ------------------------------------------------------------------
# Parse tree -> AST reduction
# ------------------------------------------------------------------
def to_ast(tree: ParseNode, source_query: str = "") -> SelectStmt:
    """Collapse a concrete ParseNode tree into the abstract AST.

    Walks `tree.children` by rule/token type rather than fixed index,
    since optional clauses (DISTINCT, GROUP BY, HAVING, ...) shift
    later children around depending on which ones are present.
    """
    assert tree.rule == "select_stmt"

    distinct = False
    select_items: list[SelectItem] = []
    columns: list[str] = []
    table = ""
    where_ast: Node | None = None
    group_by: list[str] = []
    having_ast: Node | None = None
    order_by_list: list[OrderBy] = []
    limit_val: int | None = None
    offset_val: int | None = None

    for child in tree.children:
        if isinstance(child, Token):
            if child.type is TokType.DISTINCT:
                distinct = True
            continue  # SELECT / FROM / trailing ';' keywords -- no AST content

        if child.rule == "select_list":
            select_items, columns = _select_list_to_ast(child)
        elif child.rule == "table_ref":
            table = child.children[0].value
        elif child.rule == "where_clause":
            where_ast = _expr_to_ast(child.children[1])
        elif child.rule == "group_clause":
            group_by = [
                c.value for c in child.children if isinstance(c, Token) and c.type is TokType.IDENT
            ]
        elif child.rule == "having_clause":
            having_ast = _expr_to_ast(child.children[1])
        elif child.rule == "order_clause":
            order_by_list = _order_clause_to_ast(child)
        elif child.rule == "limit_clause":
            nums = [c for c in child.children if isinstance(c, Token) and c.type is TokType.NUMBER]
            limit_val = nums[0].value
            if len(nums) > 1:
                offset_val = nums[1].value

    return SelectStmt(
        columns=columns,
        table=table,
        select_items=select_items,
        distinct=distinct,
        where=where_ast,
        group_by=group_by,
        having=having_ast,
        order_by=order_by_list[0] if order_by_list else None,
        order_by_list=order_by_list,
        limit=limit_val,
        offset=offset_val,
        source_query=source_query,
    )


def _select_list_to_ast(node: ParseNode) -> tuple[list[SelectItem], list[str]]:
    first = node.children[0]
    if isinstance(first, Token) and first.type is TokType.STAR:
        return [], ["*"]

    items = [
        _select_item_to_ast(c) for c in node.children if isinstance(c, ParseNode) and c.rule == "select_item"
    ]
    columns = [item.alias or default_label(item.expr) for item in items]
    return items, columns


def _select_item_to_ast(node: ParseNode) -> SelectItem:
    first = node.children[0]
    if first.rule == "agg_call":
        expr: Node = _agg_call_to_ast(first)
    else:  # column_ref
        expr = Identifier(name=first.children[0].value)
    alias = node.children[-1].value if len(node.children) > 1 else None
    return SelectItem(expr=expr, alias=alias)


def _agg_call_to_ast(node: ParseNode) -> AggCall:
    func_tok = node.children[0]
    arg_tok = node.children[2]
    arg = "*" if arg_tok.type is TokType.STAR else arg_tok.value
    return AggCall(func=func_tok.value.upper(), arg=arg)


def _order_clause_to_ast(node: ParseNode) -> list[OrderBy]:
    result: list[OrderBy] = []
    for item in node.children:
        if not (isinstance(item, ParseNode) and item.rule == "order_item"):
            continue
        col = item.children[0].value
        descending = len(item.children) > 1 and item.children[1].type is TokType.DESC
        result.append(OrderBy(column=col, descending=descending))
    return result


def _expr_to_ast(node: ParseNode) -> Node:
    """Dispatch on rule name; collapses single-child chains automatically."""
    if node.rule == "or_expr":
        return _binary_chain_to_ast(node, "OR")
    if node.rule == "and_expr":
        return _binary_chain_to_ast(node, "AND")
    if node.rule == "not_expr":
        if len(node.children) == 2:  # NOT <not_expr>
            return UnaryOp(op="NOT", operand=_expr_to_ast(node.children[1]))
        return _expr_to_ast(node.children[0])  # pass-through to comparison
    if node.rule == "comparison":
        return _comparison_to_ast(node)
    raise AssertionError(f"unreachable expr rule: {node.rule}")


def _comparison_to_ast(node: ParseNode) -> Node:
    left = _operand_to_ast(node.children[0])
    if len(node.children) == 1:
        return left

    second = node.children[1]
    assert isinstance(second, Token)

    if second.type in COMPARISON_OPS:
        op = COMPARISON_OPS[second.type]
        right = _operand_to_ast(node.children[2])
        return Comparison(op=op, left=left, right=right)

    if second.type is TokType.BETWEEN:
        low = _operand_to_ast(node.children[2])
        high = _operand_to_ast(node.children[4])  # children[3] is the inner AND token
        return Between(expr=left, low=low, high=high)

    if second.type is TokType.NOT:  # NOT IN (...)
        in_list_node = node.children[3]
        values = _in_list_values(in_list_node)
        return UnaryOp(op="NOT", operand=InList(expr=left, values=values))

    if second.type is TokType.IN:
        in_list_node = node.children[2]
        values = _in_list_values(in_list_node)
        return InList(expr=left, values=values)

    if second.type is TokType.IS:
        negated = isinstance(node.children[2], Token) and node.children[2].type is TokType.NOT
        return IsNull(expr=left, negated=negated)

    raise AssertionError(f"unreachable comparison shape: {node!r}")  # pragma: no cover


def _in_list_values(node: ParseNode) -> list[Node]:
    return [_operand_to_ast(c) for c in node.children if isinstance(c, ParseNode) and c.rule == "operand"]


def _binary_chain_to_ast(node: ParseNode, op: str) -> Node:
    # children alternate: operand, OP-token, operand, OP-token, operand...
    operands = [c for c in node.children if isinstance(c, ParseNode)]
    result = _expr_to_ast(operands[0])
    for operand in operands[1:]:
        result = BinaryOp(op=op, left=result, right=_expr_to_ast(operand))
    return result


def _operand_to_ast(node: ParseNode) -> Node:
    assert node.rule == "operand"
    first = node.children[0]
    if isinstance(first, ParseNode) and first.rule == "agg_call":
        return _agg_call_to_ast(first)
    if isinstance(first, Token) and first.type is TokType.LPAREN:
        # parenthesised sub-expression: '(' expr ')' -- the AST drops the
        # parens entirely, since grouping was only ever a parsing-time
        # concern; the tree shape itself now encodes precedence.
        return _expr_to_ast(node.children[1])
    if isinstance(first, Token):
        if first.type is TokType.IDENT:
            return Identifier(name=first.value)
        return Literal(value=first.value)  # NUMBER, STRING, or BOOL
    raise AssertionError(f"unreachable operand shape: {node!r}")  # pragma: no cover


def dump_ast(node: Node, indent: int = 0) -> str:
    """Pretty-print an AST node, purely for --ast / teaching output."""
    pad = "  " * indent
    if isinstance(node, SelectStmt):
        col_repr = "*" if node.columns == ["*"] else ", ".join(node.columns)
        header = f"{pad}SelectStmt columns=[{col_repr}] table={node.table!r}"
        if node.distinct:
            header += " DISTINCT"
        lines = [header]
        if node.where is not None:
            lines.append(f"{pad}  where:")
            lines.append(dump_ast(node.where, indent + 2))
        if node.group_by:
            lines.append(f"{pad}  group_by: {', '.join(node.group_by)}")
        if node.having is not None:
            lines.append(f"{pad}  having:")
            lines.append(dump_ast(node.having, indent + 2))
        if node.order_by_list:
            parts = [f"{ob.column} {'DESC' if ob.descending else 'ASC'}" for ob in node.order_by_list]
            lines.append(f"{pad}  order_by: {', '.join(parts)}")
        if node.limit is not None:
            lines.append(f"{pad}  limit: {node.limit}")
        if node.offset is not None:
            lines.append(f"{pad}  offset: {node.offset}")
        return "\n".join(lines)
    if isinstance(node, BinaryOp):
        return "\n".join(
            [
                f"{pad}BinaryOp({node.op})",
                dump_ast(node.left, indent + 1),
                dump_ast(node.right, indent + 1),
            ]
        )
    if isinstance(node, UnaryOp):
        return "\n".join([f"{pad}UnaryOp({node.op})", dump_ast(node.operand, indent + 1)])
    if isinstance(node, Comparison):
        return "\n".join(
            [
                f"{pad}Comparison({node.op})",
                dump_ast(node.left, indent + 1),
                dump_ast(node.right, indent + 1),
            ]
        )
    if isinstance(node, Between):
        return "\n".join(
            [
                f"{pad}Between",
                dump_ast(node.expr, indent + 1),
                dump_ast(node.low, indent + 1),
                dump_ast(node.high, indent + 1),
            ]
        )
    if isinstance(node, InList):
        lines = [f"{pad}InList", dump_ast(node.expr, indent + 1)]
        lines.extend(dump_ast(v, indent + 1) for v in node.values)
        return "\n".join(lines)
    if isinstance(node, IsNull):
        return "\n".join([f"{pad}IsNull(negated={node.negated})", dump_ast(node.expr, indent + 1)])
    if isinstance(node, AggCall):
        return f"{pad}AggCall({node.func}, {node.arg})"
    if isinstance(node, Identifier):
        return f"{pad}Identifier({node.name})"
    if isinstance(node, Literal):
        return f"{pad}Literal({node.value!r})"
    return f"{pad}{node!r}"  # pragma: no cover - defensive fallback


def parse(source: str) -> tuple[ParseNode, SelectStmt]:
    """Convenience: parse `source` and return (parse_tree, ast)."""
    tree = Parser(source).parse()
    return tree, to_ast(tree, source_query=source)
