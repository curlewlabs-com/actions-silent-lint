"""Tests for the `actions-silent-lint` command: which files it reads, that it
judges the document GitHub sees, and that a lint that could not run never
exits clean. They need git and mikefarah's yq on PATH."""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from actions_silent_lint.cli import main

BUILD = "name: Build\non: push\njobs: {}\n"


def chained(workflows: str) -> str:
    return (
        f"name: Publish\non:\n  workflow_run:\n    workflows: {workflows}\njobs: {{}}\n"
    )


def run(argv: list[str] | None = None) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        status = main(argv or [])
    return status, out.getvalue(), err.getvalue()


class TheCommand(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, cwd)
        subprocess.run(["git", "init", "-q"], check=True)

    def write(self, name: str, text: str, track: bool = True) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        if track:
            subprocess.run(["git", "add", name], check=True)

    def workflow(self, name: str, text: str, track: bool = True) -> None:
        self.write(f".github/workflows/{name}", text, track)

    def test_a_repository_with_nothing_to_judge_passes(self) -> None:
        # Most repositories have no workflow_run trigger and no action, and
        # the lint is meant to run in all of them.
        self.workflow("build.yml", BUILD)
        self.assertEqual(run(), (0, "", ""))

    def test_a_stranded_trigger_is_reported(self) -> None:
        self.workflow("build.yml", BUILD)
        self.workflow("publish.yml", chained('["Build", "Build and test"]'))
        status, out, _ = run()
        self.assertEqual(status, 1)
        self.assertEqual(
            out,
            '.github/workflows/publish.yml: workflow_run names "Build and test",'
            " which is no workflow's name:, so the trigger never fires\n",
        )

    def test_names_are_read_as_yaml_not_as_text(self) -> None:
        # Each of these once read wrongly in a line scanner: a quoted key, a
        # list spread over lines, a `#` inside quotes, and two spellings of
        # one escaped name.
        self.workflow("a.yml", 'name: "Lane #1"\non: push\njobs: {}\n')
        self.workflow("b.yml", "name: 'Say \"hi\"'\non: push\njobs: {}\n")
        self.workflow(
            "c.yml",
            'name: C\non:\n  workflow_run:\n    "workflows":\n      - "Lane #1"\n'
            '      - "Say \\"hi\\""\njobs: {}\n',
        )
        self.assertEqual(run(), (0, "", ""))

    def test_an_alias_is_judged_as_what_it_names(self) -> None:
        self.workflow("build.yml", "name: &n Build\non: push\njobs: {}\n")
        self.workflow("publish.yml", chained("[Missing]"))
        status, out, _ = run()
        self.assertEqual(status, 1)
        self.assertIn('"Missing"', out)

    def test_untracked_workflows_and_subdirectories_are_not_read(self) -> None:
        # GitHub reads workflows only from the directory itself, and only
        # what is committed runs.
        self.workflow("publish.yml", chained("[Build]"))
        self.workflow("build.yml", BUILD, track=False)
        self.write(".github/workflows/fixtures/build.yml", BUILD)
        status, out, _ = run()
        self.assertEqual(status, 1)
        self.assertIn('"Build"', out)

    def test_the_yaml_extension_is_read(self) -> None:
        self.workflow("build.yaml", BUILD)
        self.workflow("publish.yaml", chained("[Build]"))
        self.assertEqual(run(), (0, "", ""))

    def test_patterns_are_counted_and_never_fail(self) -> None:
        self.workflow("build.yml", BUILD)
        self.workflow("publish.yml", chained('["Build*", "Build C\\\\+\\\\+"]'))
        status, out, err = run()
        self.assertEqual((status, out), (0, ""))
        self.assertEqual(
            err,
            "2 workflow_run entries are patterns and were not checked:\n"
            '  .github/workflows/publish.yml: "Build*"\n'
            '  .github/workflows/publish.yml: "Build C\\\\+\\\\+"\n',
        )

    def test_one_pattern_is_counted_in_the_singular(self) -> None:
        self.workflow("publish.yml", chained('["Build*"]'))
        self.assertEqual(
            run()[2].splitlines()[0],
            "1 workflow_run entry is a pattern and was not checked:",
        )

    def test_manifests_are_read_at_any_depth_under_both_names(self) -> None:
        bad = 'name: a\ndescription: "Pass `${{ job.status }}`."\nruns:\n  using: node24\n  main: i.js\n'
        self.write("action.yml", bad)
        self.write("tools/notify/action.yaml", bad)
        self.write("other/action.yml", bad, track=False)
        status, out, _ = run()
        self.assertEqual(status, 1)
        self.assertEqual(
            [line.split(":")[0] for line in out.splitlines()],
            ["action.yml", "tools/notify/action.yaml"],
        )

    def test_an_escaped_literal_in_a_manifest_passes(self) -> None:
        # The form GitHub turns into plain text, as YAML spells it in a plain,
        # a double-quoted and a single-quoted scalar.
        self.write(
            "action.yml",
            "name: ${{ 'Notify' }}\n"
            "description: \"${{ 'Use ${{ inputs.token }} here' }}\"\n"
            "inputs:\n  token:\n    description: '${{ ''it''''s'' }}'\n"
            "runs:\n  using: node24\n  main: i.js\n",
        )
        self.assertEqual(run(), (0, "", ""))

    def test_from_a_subdirectory_the_whole_repository_is_read(self) -> None:
        # Listed relative to the current directory, nothing would be found,
        # and an empty run passes.
        self.workflow("publish.yml", chained("[Build]"))
        (self.root / "src").mkdir()
        os.chdir(self.root / "src")
        self.assertEqual(run()[0], 1)

    def test_a_file_yq_cannot_parse_stops_the_run(self) -> None:
        self.workflow("broken.yml", "name: [unclosed\n")
        status, out, err = run()
        self.assertEqual((status, out), (1, ""))
        self.assertTrue(
            err.startswith("ERROR: actions-silent-lint could not run: parsing")
        )

    def test_a_file_of_several_documents_stops_the_run(self) -> None:
        self.workflow("two.yml", f"{BUILD}---\n{BUILD}")
        status, _, err = run()
        self.assertEqual(status, 1)
        self.assertIn("exactly one JSON document", err)

    def test_without_yq_it_could_not_run(self) -> None:
        self.workflow("build.yml", BUILD)
        git = subprocess.run(
            ["git", "--exec-path"], capture_output=True, text=True, check=True
        ).stdout.strip()
        empty = self.root / "bin"
        empty.mkdir()
        (empty / "git").symlink_to(Path(git) / "git")
        with mock.patch.dict(os.environ, {"PATH": str(empty)}):
            status, _, err = run()
        self.assertEqual(status, 1)
        self.assertIn("yq is not on PATH", err)

    def test_outside_a_repository_it_could_not_run(self) -> None:
        with tempfile.TemporaryDirectory() as elsewhere:
            os.chdir(elsewhere)
            with mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": elsewhere}):
                status, _, err = run()
        self.assertEqual(status, 1)
        self.assertIn("git rev-parse failed", err)


if __name__ == "__main__":
    unittest.main()
