"""Tests for judging workflow_run triggers, over parsed documents.

The documents are what the command hands over after parsing, so YAML forms
(quoting, flow lists, anchors) are not tested here; test_cli.py covers them.
"""

from __future__ import annotations

import unittest

from actions_silent_lint.parents import (
    Finding,
    Unchecked,
    Unreadable,
    declared_parents,
    judge,
    workflow_name,
)


def child(*entries: str) -> dict[str, object]:
    return {
        "name": "Publish",
        "on": {"workflow_run": {"workflows": list(entries), "types": ["completed"]}},
    }


BUILD = {"name": "Build", "on": "push"}


class Triggers(unittest.TestCase):
    def test_a_renamed_parent_strands_its_child(self) -> None:
        # The mistake this exists for: the parent's name: changed and the
        # trigger still names the old one, so it never fires again.
        verdict = judge(
            {"build.yml": {"name": "Build and test"}, "p.yml": child("Build")}
        )
        self.assertEqual(
            verdict.findings,
            [
                Finding(
                    "p.yml",
                    'workflow_run names "Build", which is no workflow\'s name:,'
                    " so the trigger never fires",
                )
            ],
        )

    def test_an_entry_naming_a_parent_passes(self) -> None:
        verdict = judge({"build.yml": BUILD, "p.yml": child("Build")})
        self.assertEqual(verdict.findings, [])
        self.assertEqual(verdict.unchecked, [])

    def test_matching_is_exact(self) -> None:
        # A literal entry is not a pattern, so case and spacing are significant.
        verdict = judge({"build.yml": BUILD, "p.yml": child("build", "Build ")})
        self.assertEqual(len(verdict.findings), 2)

    def test_a_live_entry_does_not_cover_a_stranded_one(self) -> None:
        verdict = judge({"build.yml": BUILD, "p.yml": child("Build", "Lint")})
        self.assertEqual([f.what.split('"')[1] for f in verdict.findings], ["Lint"])

    def test_a_bare_string_entry_is_read(self) -> None:
        document = {"name": "P", "on": {"workflow_run": {"workflows": "Missing"}}}
        self.assertEqual(len(judge({"p.yml": document}).findings), 1)

    def test_a_workflow_may_chain_off_itself_by_name(self) -> None:
        document = {"name": "Loop", "on": {"workflow_run": {"workflows": ["Loop"]}}}
        self.assertEqual(judge({"loop.yml": document}).findings, [])

    def test_a_numeric_name_is_matched_as_the_text_github_shows(self) -> None:
        # Dropped instead, every entry naming the workflow would be stranded.
        verdict = judge({"v.yml": {"name": 1.5}, "p.yml": child("1.5")})
        self.assertEqual(verdict.findings, [])

    def test_an_unnamed_workflow_cannot_be_named_by_its_path(self) -> None:
        # Whether GitHub matches an unnamed workflow by its path is not
        # something this can check, so the child is reported, and the fix is
        # to give the parent a name.
        verdict = judge({"build.yml": {"on": "push"}, "p.yml": child("build.yml")})
        self.assertEqual(len(verdict.findings), 1)


class Patterns(unittest.TestCase):
    def test_each_pattern_character_leaves_the_entry_unchecked(self) -> None:
        # GitHub matches these on its servers by rules that cannot be checked
        # here; judging them would fail runs that GitHub would fire.
        entries = ["Build*", "Build ?", "C\\+\\+", "CI [x]", "!Docs", "a+b"]
        verdict = judge({"build.yml": BUILD, "p.yml": child(*entries)})
        self.assertEqual(verdict.findings, [])
        self.assertEqual(verdict.unchecked, [Unchecked("p.yml", e) for e in entries])

    def test_a_name_holding_brackets_is_not_passed_as_resolved(self) -> None:
        # Read literally, this entry matches the name exactly and would pass,
        # but GitHub reads the brackets as a character class.
        verdict = judge({"ci.yml": {"name": "CI [x]"}, "p.yml": child("CI [x]")})
        self.assertEqual(verdict.unchecked, [Unchecked("p.yml", "CI [x]")])

    def test_a_literal_beside_a_pattern_is_still_judged(self) -> None:
        verdict = judge({"build.yml": BUILD, "p.yml": child("Build*", "Gone")})
        self.assertEqual(len(verdict.findings), 1)
        self.assertEqual(len(verdict.unchecked), 1)


class Shapes(unittest.TestCase):
    def test_on_forms_without_a_workflows_list_declare_nothing(self) -> None:
        for on in ("push", ["push", "workflow_run"], {"workflow_run": None}, {}):
            with self.subTest(on=on):
                self.assertEqual(declared_parents({"on": on}), [])
        self.assertEqual(
            declared_parents({"on": {"workflow_run": {"types": ["completed"]}}}), []
        )

    def test_a_workflow_run_key_elsewhere_is_not_a_trigger(self) -> None:
        document = {
            "on": "push",
            "jobs": {"workflow_run": {"with": {"workflows": ["Missing"]}}},
        }
        self.assertEqual(declared_parents(document), [])

    def test_an_entry_that_is_not_a_string_is_a_finding(self) -> None:
        # Read as no parents, a real but oddly shaped list would pass.
        for value in ([1], [["Build"]], {"Build": None}, 3):
            with self.subTest(value=value):
                document = {"name": "P", "on": {"workflow_run": {"workflows": value}}}
                findings = judge({"build.yml": BUILD, "p.yml": document}).findings
                self.assertEqual([f.path for f in findings], ["p.yml"])

    def test_a_document_that_is_not_a_mapping_is_a_finding(self) -> None:
        for document in (None, "text", ["a"]):
            with self.subTest(document=document):
                with self.assertRaises(Unreadable):
                    workflow_name(document)
                self.assertEqual(
                    judge({"x.yml": document}).findings,
                    [Finding("x.yml", "the document's top level is not a mapping")],
                )

    def test_an_unreadable_workflow_holds_back_the_stranded_reports(self) -> None:
        # Its name could be the one a trigger names, so reporting the trigger
        # would bury the real finding under a false one.
        verdict = judge({"broken.yml": None, "p.yml": child("Build")})
        self.assertEqual([f.path for f in verdict.findings], ["broken.yml"])

    def test_one_unreadable_trigger_does_not_hide_another(self) -> None:
        bad = {"name": "Q", "on": {"workflow_run": {"workflows": [1]}}}
        verdict = judge({"q.yml": bad, "p.yml": child("Missing")})
        self.assertEqual(sorted(f.path for f in verdict.findings), ["p.yml", "q.yml"])


if __name__ == "__main__":
    unittest.main()
