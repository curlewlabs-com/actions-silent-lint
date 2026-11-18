"""How GitHub's runner reads the `${{ }}` expressions in one manifest string.

The runner splits a string into its text and its expressions before it checks
the string's position, and one form it turns back into plain text: a string
that is a single expression holding only a quoted string literal, such as
`${{ 'Use ${{ inputs.token }} here' }}`, loads as the literal's text wherever
it sits. Reading that as an expression would report a manifest GitHub accepts.

The reading is transcribed from the runner's template reader (`ParseScalar`,
`ParseExpression` and `IsExpressionString` in
https://github.com/actions/runner/blob/main/src/Sdk/DTObjectTemplating/ObjectTemplating/TemplateReader.cs),
not reasoned out, including its edges: a `}}` inside a quoted string does not
close an expression, `''` is the only escape inside quotes, and whitespace
around the literal is .NET's, which is not quite Python's.
"""

from __future__ import annotations

import unicodedata
from typing import Final

OPEN: Final = "${{"
CLOSE: Final = "}}"

# The runner's expression parser refuses an expression longer than this, in
# UTF-16 code units (ExpressionConstants.MaxLength).
MAX_LENGTH: Final = 21000


class NotClosed(Exception):
    """A `${{` with no `}}` after it, outside quotes."""


def is_whitespace(character: str) -> bool:
    """.NET's Char.IsWhiteSpace, which the runner trims and splits by.

    Python's str.isspace also counts U+001C to U+001F, which .NET does not.
    """
    if character in "\t\n\v\f\r\x85":
        return True
    return unicodedata.category(character) in ("Zs", "Zl", "Zp")


def trim(text: str) -> str:
    start, end = 0, len(text)
    while start < end and is_whitespace(text[start]):
        start += 1
    while end > start and is_whitespace(text[end - 1]):
        end -= 1
    return text[start:end]


def segments(text: str) -> list[tuple[bool, str]]:
    """The string as the runner splits it: (True, inner text of an
    expression, untrimmed) and (False, literal text), in order, with adjacent
    literal text joined. Raises NotClosed."""
    result: list[tuple[bool, str]] = []

    def add_text(value: str) -> None:
        if result and not result[-1][0]:
            result[-1] = (False, result[-1][1] + value)
        else:
            result.append((False, value))

    start = text.find(OPEN)
    if start < 0:
        return [(False, text)]
    i = 0
    while i < len(text):
        if i == start:
            end = -1
            in_string = False
            i += len(OPEN)
            while i < len(text):
                if text[i] == "'":
                    in_string = not in_string
                elif not in_string and text[i] == "}" and text[i - 1] == "}":
                    end = i
                    i += 1
                    break
                i += 1
            if end < start:
                raise NotClosed(text)
            result.append((True, text[start + len(OPEN) : end + 1 - len(CLOSE)]))
            start = text.find(OPEN, i)
        elif i < start:
            add_text(text[i:start])
            i = start
        else:
            add_text(text[i:])
            break
    return result


def _utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def string_literal(expression: str) -> str | None:
    """The value of a trimmed expression that is one quoted string literal,
    or None for any other expression."""
    if not expression.startswith("'") or _utf16_length(expression) > MAX_LENGTH:
        return None
    value: list[str] = []
    in_string = False
    for index, character in enumerate(expression):
        if character == "'":
            in_string = not in_string
            if in_string and index != 0:
                value.append(character)
        elif not in_string:
            return None
        else:
            value.append(character)
    # An odd count of quotes leaves the literal open, which the parser refuses.
    return None if in_string else "".join(value)


def literal_text(text: str) -> str | None:
    """The plain text GitHub reads `text` as when the whole string is one
    expression holding only a quoted string literal; None when it is anything
    else, including a string with no expression at all."""
    try:
        parts = segments(text)
    except NotClosed:
        return None
    if len(parts) != 1 or not parts[0][0]:
        return None
    return string_literal(trim(parts[0][1]))


# Characters that end a word or a number, as the runner's lexer has them
# (LexicalAnalyzer.TestTokenBoundary), besides whitespace.
_BOUNDARY: Final = frozenset("([)],.!><=&|")
# The token kinds a `.` after which starts a number rather than a property.
_BEFORE_A_NUMBER: Final = frozenset(
    {None, "separator", "start-group", "start-index", "start-parameters", "logical"}
)
# Words the lexer reads as literals, compared case-sensitively as it does.
_LITERAL_WORDS: Final = frozenset({"null", "true", "false", "NaN", "Infinity"})
_TWO_CHARACTER_OPERATORS: Final = frozenset({"!=", ">=", "<=", "==", "&&", "||"})


def _is_boundary(character: str) -> bool:
    return character in _BOUNDARY or is_whitespace(character)


def _is_legal_word(word: str) -> bool:
    if not ("a" <= word[0] <= "z" or "A" <= word[0] <= "Z" or word[0] == "_"):
        return False
    return all(
        "a" <= c <= "z" or "A" <= c <= "Z" or "0" <= c <= "9" or c in "_-"
        for c in word[1:]
    )


def references(expression: str) -> tuple[list[str], list[str]]:
    """The named values (contexts) and the functions an expression names, in
    order, as the runner's lexer classifies its words.

    Transcribed from LexicalAnalyzer
    (https://github.com/actions/runner/blob/main/src/Sdk/DTExpressions2/Expressions2/Tokens/LexicalAnalyzer.cs):
    a word after `.` is a property, a word followed by `(` is a function, the
    literal words are literals, and any other word is a named value; text in
    quotes is a string. The lexer also turns a token that may not follow the
    one before it into an error, which only an expression the parser refuses
    has, so that is left out: a word read here as a named value is one in
    every expression GitHub accepts.
    """
    named: list[str] = []
    functions: list[str] = []
    last: str | None = None
    i, n = 0, len(expression)
    while True:
        while i < n and is_whitespace(expression[i]):
            i += 1
        if i >= n:
            return named, functions
        c = expression[i]
        kind: str
        if c == "(":
            kind = "start-parameters" if last == "function" else "start-group"
            i += 1
        elif c == "[":
            kind, i = "start-index", i + 1
        elif c in ")],*":
            kind = {")": "end", "]": "end-index", ",": "separator", "*": "wildcard"}[c]
            i += 1
        elif c == "'":
            i += 1
            kind = "error"
            while i < n:
                i += 1
                if expression[i - 1] == "'":
                    if i >= n or expression[i] != "'":
                        kind = "string"
                        break
                    i += 1
        elif c in "!><=&|":
            if expression[i : i + 2] in _TWO_CHARACTER_OPERATORS:
                kind, i = "logical", i + 2
            elif c in "!><":
                kind, i = "logical", i + 1
            else:
                i += 1
                while i < n and not _is_boundary(expression[i]):
                    i += 1
                kind = "error"
        elif c == "." and last not in _BEFORE_A_NUMBER:
            kind, i = "dereference", i + 1
        elif c in ".-+" or "0" <= c <= "9":
            i += 1
            while i < n and (not _is_boundary(expression[i]) or expression[i] == "."):
                i += 1
            kind = "number"
        else:
            start = i
            i += 1
            while i < n and not _is_boundary(expression[i]):
                i += 1
            word = expression[start:i]
            if not _is_legal_word(word):
                kind = "error"
            elif last == "dereference":
                kind = "property"
            elif word in _LITERAL_WORDS:
                kind = "literal"
            else:
                ahead = i
                while ahead < n and is_whitespace(expression[ahead]):
                    ahead += 1
                if ahead < n and expression[ahead] == "(":
                    kind = "function"
                    functions.append(word)
                else:
                    kind = "named-value"
                    named.append(word)
        last = kind
