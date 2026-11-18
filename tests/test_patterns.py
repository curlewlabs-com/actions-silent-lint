"""Tests for matching `workflows:` entries, against what GitHub was measured
to do.

MEASURED is the record patterns.py was written from: each entry list was a
workflow's `on.push.paths` on a scratch branch, each name a file one commit
added, and GitHub either started a run for the pair or did not. REFUSED marks
a list GitHub rejected as a pattern, which failed every push it saw. Every
case is checked here, so a change to the matcher that disagrees with GitHub
on any of them fails, and a construct left unmodelled is named.
"""

from __future__ import annotations

import unittest

from actions_silent_lint.patterns import (
    NEGATION,
    Invalid,
    Unmodelled,
    compile_entry,
    selected,
)

REFUSED = None

NAMES = (
    "Build",
    "Builds",
    "Buildss",
    "Buuild",
    "Bild",
    "Build-test",
    "xBuild",
    "Cuild",
    "Build x",
    "Build-x",
    "Build C++",
    "C[x]",
    "v1.2",
    "v1x2",
    "B(u)ild",
    "{Build,Test}",
    "a|b",
    "a",
    "b",
    "Build*",
    "^Build",
    "Bb",
    "+Build",
    "[Build",
    "Build\\x",
    "Bld/test",
    "!Build",
    "Bxild",
    "B!ild",
    "B^ild",
    "?Build",
    "CI [x]",
    "CI x",
    "uild",
    "C",
    "C+",
    "casetest",
    "Build$",
    "Bu",
    "Build?",
    "xxBuild",
    "q/Build",
    "Bld/x/test",
    "Bld/xtest",
    "Bldxtest",
    "7",
    "Bu{2}ild",
    "BCuild",
    "^uild",
    "_uild",
    "-uild",
    "Build#",
)

MEASURED: tuple[tuple[tuple[str, ...], frozenset[str] | None], ...] = (
    (("Build",), frozenset(["Build"])),
    (
        ("Build*",),
        frozenset(
            [
                "Build",
                "Build C++",
                "Build x",
                "Build#",
                "Build$",
                "Build*",
                "Build-test",
                "Build-x",
                "Build?",
                "Build\\x",
                "Builds",
                "Buildss",
            ]
        ),
    ),
    (("Bld*",), frozenset(["Bldxtest"])),
    (("Bld**",), frozenset(["Bld/test", "Bld/x/test", "Bld/xtest", "Bldxtest"])),
    (("Bld/*",), frozenset(["Bld/test", "Bld/xtest"])),
    (
        ("**/test",),
        frozenset(
            [
                "Bld/test",
                "Bld/x/test",
                "Bld/xtest",
                "Bldxtest",
                "Build-test",
                "casetest",
            ]
        ),
    ),
    (("Builds?",), frozenset(["Build", "Builds"])),
    (("Bu?ild",), frozenset(["Bild", "Build"])),
    (("Bu+ild",), frozenset(["Build", "Buuild"])),
    (("[BC]uild",), frozenset(["Build", "Cuild"])),
    (("[BC]?uild",), frozenset(["Build", "Cuild", "uild"])),
    (("[Bb]+",), frozenset(["Bb", "b"])),
    (("[a-cB]uild",), frozenset(["Build"])),
    (("Build[ -]x",), REFUSED),
    (("Build[]",), REFUSED),
    (("[Build",), REFUSED),
    (("B[!u]ild",), REFUSED),
    (("B[^u]ild",), frozenset(["B!ild", "B^ild", "Bxild"])),
    (("Build C\\+\\+",), frozenset(["Build C++"])),
    (("C\\[x\\]",), frozenset(["C[x]"])),
    (("C\\+?",), frozenset(["C", "C+"])),
    (("\\Build",), frozenset([])),
    (("Build\\*",), frozenset(["Build*"])),
    (("Build\\\\x",), frozenset(["Build\\x"])),
    (("Build\\",), REFUSED),
    (("\\!Build",), frozenset(["!Build"])),
    (("B!ild",), frozenset(["B!ild"])),
    (("v1.2",), frozenset(["v1.2"])),
    (("B(u)ild",), frozenset(["B(u)ild"])),
    (("{Build,Test}",), frozenset(["{Build,Test}"])),
    (("a|b",), frozenset(["a|b"])),
    (("^Build",), frozenset(["^Build"])),
    (("Build$",), frozenset(["Build$"])),
    (("+Build",), frozenset(["Build"])),
    (
        ("?Build",),
        frozenset(
            [
                "!Build",
                "+Build",
                "?Build",
                "Build",
                "[Build",
                "^Build",
                "q/Build",
                "xBuild",
                "xxBuild",
            ]
        ),
    ),
    (
        ("*Build",),
        frozenset(
            [
                "!Build",
                "+Build",
                "?Build",
                "Build",
                "[Build",
                "^Build",
                "xBuild",
                "xxBuild",
            ]
        ),
    ),
    (
        ("Bu*",),
        frozenset(
            [
                "Bu",
                "Build",
                "Build C++",
                "Build x",
                "Build#",
                "Build$",
                "Build*",
                "Build-test",
                "Build-x",
                "Build?",
                "Build\\x",
                "Builds",
                "Buildss",
                "Buuild",
                "Bu{2}ild",
            ]
        ),
    ),
    (("Bu*+",), REFUSED),
    (("CI [x]",), frozenset(["CI x"])),
    (("CASETEST",), frozenset([])),
    (("casetest",), frozenset(["casetest"])),
    (
        ("Build*", "!Build x"),
        frozenset(
            [
                "Build",
                "Build C++",
                "Build#",
                "Build$",
                "Build*",
                "Build-test",
                "Build-x",
                "Build?",
                "Build\\x",
                "Builds",
                "Buildss",
            ]
        ),
    ),
    (("!Build x",), frozenset([])),
    (
        ("!Build x", "Build*"),
        frozenset(
            [
                "Build",
                "Build C++",
                "Build x",
                "Build#",
                "Build$",
                "Build*",
                "Build-test",
                "Build-x",
                "Build?",
                "Build\\x",
                "Builds",
                "Buildss",
            ]
        ),
    ),
    (
        ("**",),
        frozenset(
            [
                "!Build",
                "+Build",
                "-uild",
                "7",
                "?Build",
                "B!ild",
                "B(u)ild",
                "BCuild",
                "B^ild",
                "Bb",
                "Bild",
                "Bld/test",
                "Bld/x/test",
                "Bld/xtest",
                "Bldxtest",
                "Bu",
                "Build",
                "Build C++",
                "Build x",
                "Build#",
                "Build$",
                "Build*",
                "Build-test",
                "Build-x",
                "Build?",
                "Build\\x",
                "Builds",
                "Buildss",
                "Buuild",
                "Bu{2}ild",
                "Bxild",
                "C",
                "C+",
                "CI [x]",
                "CI x",
                "C[x]",
                "Cuild",
                "[Build",
                "^Build",
                "^uild",
                "_uild",
                "a",
                "a|b",
                "b",
                "casetest",
                "q/Build",
                "uild",
                "v1.2",
                "v1x2",
                "xBuild",
                "xxBuild",
                "{Build,Test}",
            ]
        ),
    ),
    (("Bld/**/test",), frozenset(["Bld/test", "Bld/x/test", "Bld/xtest"])),
    (("Bld/**",), frozenset(["Bld/test", "Bld/x/test", "Bld/xtest"])),
    (("Bld**test",), frozenset(["Bld/test", "Bld/x/test", "Bld/xtest", "Bldxtest"])),
    (("Build\\?",), frozenset(["Build?"])),
    (("Build\\-x",), frozenset(["Build-x"])),
    (("v1\\.2",), frozenset(["v1.2"])),
    (("Build\\ x",), frozenset(["Build x"])),
    (("\\d",), frozenset(["7"])),
    (("B\\x75ild",), frozenset(["Build"])),
    (("Bu\\ild",), REFUSED),
    (("Bu*?",), REFUSED),
    (("Bu??ild",), REFUSED),
    (("Bu+?ild",), REFUSED),
    (("Bu++ild",), REFUSED),
    (("Bu?+ild",), REFUSED),
    (("[BC]*uild",), frozenset(["BCuild", "Build", "Buuild", "Cuild"])),
    (("Bu{2}ild",), frozenset(["Bu{2}ild"])),
    (("[-B]uild",), REFUSED),
    (("[B-]uild",), REFUSED),
    (("[A-z]uild",), frozenset(["Build", "Cuild", "^uild", "_uild"])),
    (("[a^B]uild",), REFUSED),
    (("[^]uild",), REFUSED),
    (("[^a-z]uild",), frozenset(["-uild", "Build", "Cuild", "^uild", "_uild"])),
    (("[^ ]uild",), REFUSED),
    (("\\?Build",), frozenset(["?Build"])),
    (
        ("*",),
        frozenset(
            [
                "!Build",
                "+Build",
                "-uild",
                "7",
                "?Build",
                "B!ild",
                "B(u)ild",
                "BCuild",
                "B^ild",
                "Bb",
                "Bild",
                "Bldxtest",
                "Bu",
                "Build",
                "Build C++",
                "Build x",
                "Build#",
                "Build$",
                "Build*",
                "Build-test",
                "Build-x",
                "Build?",
                "Build\\x",
                "Builds",
                "Buildss",
                "Buuild",
                "Bu{2}ild",
                "Bxild",
                "C",
                "C+",
                "CI [x]",
                "CI x",
                "C[x]",
                "Cuild",
                "[Build",
                "^Build",
                "^uild",
                "_uild",
                "a",
                "a|b",
                "b",
                "casetest",
                "uild",
                "v1.2",
                "v1x2",
                "xBuild",
                "xxBuild",
                "{Build,Test}",
            ]
        ),
    ),
    (("?+Build",), REFUSED),
    (("+?Build",), REFUSED),
    (("++Build",), REFUSED),
    (("??Build",), REFUSED),
    (("Bu**?",), REFUSED),
    (("Bu**+",), REFUSED),
    (("Bu***",), REFUSED),
    (("[0-z]uild",), REFUSED),
    (("[z-a]uild",), REFUSED),
    (("B[u-u]ild",), frozenset(["Build"])),
    (("Bld\\/test",), frozenset(["Bld/test"])),
    (("Build\\#",), frozenset(["Build#"])),
    (("!",), frozenset([])),
    (("Build", "!"), frozenset(["Build"])),
)

# The measured entries this module reports as not checked, rather than
# judged: a backslash before a letter is a regular expression escape to
# GitHub, whose meaning is the engine's.
UNMODELLED = frozenset({"\\Build", "\\d", "B\\x75ild", "Bu\\ild"})


class Measured(unittest.TestCase):
    def test_every_measured_list_with_a_negation(self) -> None:
        # Measured as a whole: what each name ends up as after every entry.
        lists = [(e, m) for e, m in MEASURED if any(x.startswith(NEGATION) for x in e)]
        self.assertTrue(lists)
        for entries, matched in lists:
            with self.subTest(entries=entries):
                patterns = [compile_entry(entry) for entry in entries]
                self.assertEqual(selected(patterns, NAMES), matched)

    def test_every_measured_single_entry(self) -> None:
        # The lists holding a ! entry are checked as wholes above.
        for entries, matched in MEASURED:
            if any(entry.startswith(NEGATION) for entry in entries):
                continue
            self.assertEqual(len(entries), 1)
            with self.subTest(entries=entries):
                if any(entry in UNMODELLED for entry in entries):
                    with self.assertRaises(Unmodelled):
                        for entry in entries:
                            compile_entry(entry)
                elif matched is REFUSED:
                    with self.assertRaises(Invalid):
                        for entry in entries:
                            compile_entry(entry)
                else:
                    pattern = compile_entry(entries[0])
                    self.assertEqual(
                        {name for name in NAMES if pattern.matches(name)}, matched
                    )

    def test_the_unmodelled_set_is_only_measured_entries(self) -> None:
        measured = {entry for entries, _ in MEASURED for entry in entries}
        self.assertLessEqual(UNMODELLED, measured)


class Grammar(unittest.TestCase):
    def test_an_entry_without_pattern_syntax_is_literal(self) -> None:
        for entry in ("Build", "v1.2", "B(u)ild", "a|b", "{Build,Test}", "Build#"):
            with self.subTest(entry=entry):
                pattern = compile_entry(entry)
                self.assertTrue(pattern.literal)
                self.assertTrue(pattern.matches(entry))

    def test_pattern_syntax_is_not_literal(self) -> None:
        for entry in ("Build*", "C\\+\\+", "[BC]uild", "Builds?", "!Build", "+B"):
            with self.subTest(entry=entry):
                self.assertFalse(compile_entry(entry).literal)

    def test_a_run_of_four_stars_is_not_modelled(self) -> None:
        # Three are refused; four were not measured.
        with self.assertRaises(Unmodelled):
            compile_entry("Bu****")

    def test_a_backslash_or_non_ascii_in_brackets_is_not_modelled(self) -> None:
        # Neither was measured, so neither may be refused, and an escaped end
        # of a range is the same backslash.
        for entry in ("[\u00e9]uild", "[a-\u00e9]", "[\\]]", "Build[A-\\x5a]"):
            with self.subTest(entry=entry), self.assertRaises(Unmodelled):
                compile_entry(entry)

    def test_a_closing_bracket_alone_is_not_modelled(self) -> None:
        with self.assertRaises(Unmodelled):
            compile_entry("Build]")

    def test_a_refusal_says_why(self) -> None:
        for entry, reason in (
            ("[Build", "a [ is never closed"),
            ("Build[]", "[] holds nothing"),
            ("Build\\", "a pattern cannot end in \\"),
            ("Bu***", "*** is not a pattern"),
            ("Bu*?", "? after * is not a pattern"),
            ("[0-z]", "0-z is not a range of letters or of digits"),
        ):
            with self.subTest(entry=entry):
                with self.assertRaises(Invalid) as raised:
                    compile_entry(entry)
                self.assertEqual(str(raised.exception), reason)

    def test_a_near_miss_costs_no_more_than_a_match(self) -> None:
        # Each of these fails only at its last character. A backtracking
        # matcher tries every way of splitting the name among the repeats, work
        # that grows as the name's length to the power of their count; this one
        # walks the name once, so the test finishes at once or not at all.
        name = "a" * 256
        for entry in (
            "*a" * 8 + "*b",
            "a+" * 16 + "b",
            "**a" * 8 + "b",
            "?" + "a?" * 16 + "b",
        ):
            with self.subTest(entry=entry):
                self.assertFalse(compile_entry(entry).matches(name + "c"))
        self.assertTrue(compile_entry("*a" * 8 + "*").matches(name))

    def test_a_line_break_in_a_name_never_turns_a_match_into_a_finding(
        self,
    ) -> None:
        # How GitHub's stars treat one was not measured, so both read it as
        # one more character, the reading that can only pass an entry.
        self.assertTrue(compile_entry("**").matches("a\nb"))
        self.assertTrue(compile_entry("*").matches("a\nb"))


if __name__ == "__main__":
    unittest.main()
