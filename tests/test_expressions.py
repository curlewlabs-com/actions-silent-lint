"""Tests for reading a manifest string the way GitHub's runner does.

Each case is one the runner's template reader decides, so a reading that
differs here either reports a manifest GitHub loads or passes one it refuses.
"""

from __future__ import annotations

import unittest

from actions_silent_lint.expressions import (
    MAX_LENGTH,
    NotClosed,
    literal_text,
    segments,
    trim,
)


class Segments(unittest.TestCase):
    def test_text_and_expressions_are_split_in_order(self) -> None:
        self.assertEqual(
            segments("a ${{ x }} b ${{y}}"),
            [(False, "a "), (True, " x "), (False, " b "), (True, "y")],
        )

    def test_a_string_without_an_expression_is_one_text_segment(self) -> None:
        self.assertEqual(segments("plain }} text"), [(False, "plain }} text")])

    def test_a_closer_inside_quotes_does_not_close_the_expression(self) -> None:
        # The runner tracks quotes while it looks for `}}`, which is what lets
        # a literal carry the delimiters.
        self.assertEqual(segments("${{ 'a }} b' }}"), [(True, " 'a }} b' ")])

    def test_an_unterminated_expression_is_not_closed(self) -> None:
        for text in ("${{ job.status", "${{ 'a }}", "x ${{ a }} ${{ b"):
            with self.subTest(text=text), self.assertRaises(NotClosed):
                segments(text)


class LiteralText(unittest.TestCase):
    def test_one_quoted_literal_is_read_as_its_text(self) -> None:
        for text, value in (
            ("${{ 'Use ${{ inputs.token }} here' }}", "Use ${{ inputs.token }} here"),
            ("${{'tight'}}", "tight"),
            ("${{ \t'spaced'\n }}", "spaced"),
            ("${{ 'it''s' }}", "it's"),
            ("${{ '' }}", ""),
            ("${{ ' ' }}", " "),
        ):
            with self.subTest(text=text):
                self.assertEqual(literal_text(text), value)

    def test_anything_else_is_not_a_literal(self) -> None:
        # Each of these is an expression to the runner, or not one at all, so
        # its position decides whether it loads.
        for text in (
            "no expression",
            "${{ 'a' }} and text",
            " ${{ 'a' }}",
            "${{ 'a' }}${{ 'b' }}",
            "${{ 'a' || 'b' }}",
            "${{ 'a' 'b' }}",
            "${{ format('a') }}",
            "${{ 1 }}",
            '${{ "double" }}',
            "${{ }}",
            "${{ 'open }}",
            "${{ 'unclosed",
        ):
            with self.subTest(text=text):
                self.assertIsNone(literal_text(text))

    def test_the_parsers_length_limit_holds(self) -> None:
        # Past it the runner refuses the expression, so the manifest fails.
        fits = "'" + "a" * (MAX_LENGTH - 2) + "'"
        self.assertEqual(literal_text("${{ " + fits + " }}"), "a" * (MAX_LENGTH - 2))
        self.assertIsNone(literal_text("${{ '" + "a" * (MAX_LENGTH - 1) + "' }}"))
        # The limit counts UTF-16 code units, so a character outside the
        # Basic Multilingual Plane counts twice.
        wide = "'" + "\U0001f600" * ((MAX_LENGTH - 2) // 2 + 1) + "'"
        self.assertIsNone(literal_text("${{ " + wide + " }}"))

    def test_whitespace_is_dotnets(self) -> None:
        # U+001F is whitespace to Python, not to .NET, so the runner keeps it
        # and the expression no longer starts with a quote.
        self.assertEqual(trim("\u001f x  "), "\u001f x")
        self.assertIsNone(literal_text("${{ \u001f'a' }}"))


if __name__ == "__main__":
    unittest.main()
