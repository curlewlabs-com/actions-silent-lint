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
