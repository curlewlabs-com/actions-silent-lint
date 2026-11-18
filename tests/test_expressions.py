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
    references,
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
            ("${{ '\u00a0' }}", "\u00a0"),
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
        self.assertEqual(trim("\u001f x \u2003"), "\u001f x")
        self.assertIsNone(literal_text("${{ \u001f'a' }}"))


class References(unittest.TestCase):
    """Which words the runner's lexer reads as contexts and functions."""

    def test_named_values_and_functions_are_told_apart(self) -> None:
        self.assertEqual(
            references("contains(github.ref, inputs.a) && success ()"),
            (["github", "inputs"], ["contains", "success"]),
        )

    def test_a_word_after_a_dot_is_a_property(self) -> None:
        self.assertEqual(references("steps.a.outputs.b"), (["steps"], []))
        self.assertEqual(references("fromJSON(x).secrets"), (["x"], ["fromJSON"]))

    def test_strings_hold_no_names(self) -> None:
        self.assertEqual(
            references("format('{0} secrets.T ''q'' x', a)"), (["a"], ["format"])
        )

    def test_a_dot_starts_a_number_after_an_operator_or_opening(self) -> None:
        # So `.5` is a number, not a property of what came before.
        self.assertEqual(references("a == .5 || [.5]"), (["a"], []))

    def test_a_number_runs_to_the_next_boundary(self) -> None:
        # The lexer reads `1secrets` as one (bad) number, not as a number and
        # a named value, so nothing here is a context.
        self.assertEqual(references("1secrets"), ([], []))

    def test_the_literal_words_are_matched_exactly(self) -> None:
        self.assertEqual(
            references("true false null NaN Infinity True"), (["True"], [])
        )

    def test_a_word_the_lexer_refuses_names_nothing(self) -> None:
        self.assertEqual(references("a$b 9"), ([], []))


if __name__ == "__main__":
    unittest.main()
