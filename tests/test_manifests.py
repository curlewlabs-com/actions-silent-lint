"""Tests for judging action manifests, over parsed documents.

The positions are enumerated in both directions, against the table in
manifests.py's docstring, which is transcribed from the runner's schema: a
suite holding only the flagged half would pass a lint that also flagged
correct manifests, and a lint that fails valid files gets switched off.
"""

from __future__ import annotations

import unittest

from actions_silent_lint.manifests import Finding, is_evaluated, judge, render


class Positions(unittest.TestCase):
    def test_evaluated_positions(self) -> None:
        for position in (
            ("inputs", "token", "default"),
            ("outputs", "result", "value"),
            ("runs", "args", 1),
            ("runs", "env", "TARGET"),
            ("runs", "steps", 0, "name"),
            ("runs", "steps", 0, "if"),
            ("runs", "steps", 0, "run"),
            ("runs", "steps", 0, "shell"),
            ("runs", "steps", 0, "working-directory"),
            ("runs", "steps", 0, "continue-on-error"),
            ("runs", "steps", 0, "env", "TOKEN"),
            ("runs", "steps", 0, "with", "status"),
            ("runs", "steps", 2, "with", "nested", 0),
        ):
            with self.subTest(position=position):
                self.assertTrue(is_evaluated(position))

    def test_positions_that_are_not_evaluated(self) -> None:
        for position in (
            (),
            ("name",),
            ("author",),
            ("description",),
            ("inputs", "token", "description"),
            ("inputs", "token", "deprecationMessage"),
            ("outputs", "result", "description"),
            ("branding", "icon"),
            ("branding", "color"),
            # The schema gives the items of args a context, not args itself.
            ("runs", "args"),
            # Unnamed, so read as not evaluated: the table fails closed.
            ("metadata", "owner"),
        ):
            with self.subTest(position=position):
                self.assertFalse(is_evaluated(position))

    def test_runs_is_not_evaluated_wholesale(self) -> None:
        # Each of these is a plain string in the schema. Exempting all of
        # `runs` would pass every one of them.
        for key in (
            "using",
            "image",
            "entrypoint",
            "pre-entrypoint",
            "post-entrypoint",
            "pre-if",
            "post-if",
            "main",
            "pre",
            "post",
            "plugin",
        ):
            with self.subTest(key=key):
                self.assertFalse(is_evaluated(("runs", key)))
        self.assertFalse(is_evaluated(("runs", "steps", 0, "id")))
        self.assertFalse(is_evaluated(("runs", "steps", 0, "uses")))

    def test_an_evaluated_name_at_another_depth_is_not_evaluated(self) -> None:
        self.assertFalse(is_evaluated(("branding", "inputs", "x", "default")))
        self.assertFalse(is_evaluated(("inputs", "x", "default", "nested")))
        self.assertFalse(is_evaluated(("runs", "steps", 0, "name", "extra")))

    def test_render(self) -> None:
        self.assertEqual(
            render(("inputs", "job-status", "description")),
            "inputs.job-status.description",
        )
        self.assertEqual(render(("runs", "steps", 0, "run")), "runs.steps[0].run")


COMPOSITE: dict[str, object] = {
    "name": "Upload report",
    "description": "Uploads the report the job wrote.",
    "inputs": {
        "path": {
            "description": "Where the report is.",
            "default": "${{ github.workspace }}",
        }
    },
    "outputs": {
        "url": {"description": "Where it went.", "value": "${{ steps.up.outputs.url }}"}
    },
    "runs": {
        "using": "composite",
        "steps": [
            {
                "id": "up",
                "name": "Upload ${{ inputs.path }}",
                "if": "${{ inputs.path != '' }}",
                "shell": "bash",
                "working-directory": "${{ github.workspace }}",
                "continue-on-error": "${{ inputs.path == '' }}",
                # A key is a template where its mapping has a context.
                "env": {"REPORT": "${{ inputs.path }}", "${{ inputs.path }}": "x"},
                "run": '"$GITHUB_ACTION_PATH/upload.sh"',
            },
            {"uses": "./notify", "with": {"status": "${{ job.status }}"}},
        ],
    },
}


class Manifests(unittest.TestCase):
    def test_expressions_where_github_evaluates_them_pass(self) -> None:
        self.assertEqual(judge("action.yml", COMPOSITE), [])

    def test_a_docker_actions_args_and_env_pass(self) -> None:
        manifest = {
            "name": "Build image",
            "description": "d",
            "runs": {
                "using": "docker",
                "image": "Dockerfile",
                "args": ["--target", "${{ inputs.target }}"],
                "env": {"TARGET": "${{ inputs.target }}"},
            },
        }
        self.assertEqual(judge("action.yml", manifest), [])

    def test_an_expression_standing_in_for_a_docker_actions_args_is_a_finding(
        self,
    ) -> None:
        # Each argument is evaluated, the list is not, and GitHub rejects a
        # manifest whose args is one expression.
        manifest = {
            "name": "Build image",
            "description": "d",
            "runs": {
                "using": "docker",
                "image": "Dockerfile",
                "args": "${{ inputs.a }}",
            },
        }
        self.assertEqual(
            [f.position for f in judge("action.yml", manifest)], ["runs.args"]
        )

    def test_an_expression_in_an_input_description_is_a_finding(self) -> None:
        # The mistake this exists for: prose that describes a value with the
        # syntax of the expression that produces it. It reads naturally, and
        # the manifest fails to load on the first job that uses it.
        manifest = dict(COMPOSITE)
        manifest["inputs"] = {
            "status": {"description": "The caller's `${{ job.status }}`."}
        }
        self.assertEqual(
            judge("notify/action.yml", manifest),
            [
                Finding(
                    "notify/action.yml",
                    "inputs.status.description",
                    "holds a ${{ }} expression where GitHub does not evaluate one",
                )
            ],
        )

    def test_an_unterminated_expression_is_a_finding(self) -> None:
        manifest = {"name": "a", "description": "see ${{ job.status", "runs": {}}
        self.assertEqual(
            [f.position for f in judge("a.yml", manifest)], ["description"]
        )

    def test_every_finding_in_a_manifest_is_reported(self) -> None:
        manifest = {
            "name": "Deploy ${{ github.ref }}",
            "description": "d",
            "runs": {"using": "${{ inputs.kind }}", "main": "${{ inputs.entry }}.js"},
        }
        self.assertEqual(
            [f.position for f in judge("action.yml", manifest)],
            ["name", "runs.using", "runs.main"],
        )

    def test_an_expression_as_a_key_where_no_context_exists_is_a_finding(self) -> None:
        for manifest, position in (
            ({"name": "a", "${{ github.actor }}": "x"}, "${{ github.actor }}"),
            (
                {"name": "a", "inputs": {"${{ github.actor }}": {"description": "x"}}},
                "inputs.${{ github.actor }}",
            ),
        ):
            with self.subTest(position=position):
                self.assertEqual(
                    judge("action.yml", manifest),
                    [
                        Finding(
                            "action.yml", position, "a key holds a ${{ }} expression"
                        )
                    ],
                )

    def test_a_document_that_is_not_a_mapping_is_a_finding(self) -> None:
        # There is nothing in it to judge, so passing it would be a pass over
        # nothing; GitHub cannot load it as an action either.
        for document in (None, "text", ["a"]):
            with self.subTest(document=document):
                self.assertEqual(
                    judge("action.yml", document),
                    [Finding("action.yml", "-", "the file is not an action mapping")],
                )


if __name__ == "__main__":
    unittest.main()
