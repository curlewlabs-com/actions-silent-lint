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

    def test_an_escaped_literal_passes_where_no_expression_may_sit(self) -> None:
        # GitHub turns a string that is one expression holding only a quoted
        # literal into that text before it checks the position, so this loads;
        # reporting it would fail a manifest GitHub accepts.
        literal = "${{ 'Use ${{ inputs.token }} here' }}"
        manifest = {
            "name": literal,
            "description": "${{ 'it''s' }}",
            "inputs": {"token": {"description": literal}, literal: {}},
            literal: "x",
            "runs": {"using": "node24", "main": "${{ 'index.js' }}"},
        }
        self.assertEqual(judge("action.yml", manifest), [])

    def test_an_escaped_key_is_judged_as_the_key_github_reads(self) -> None:
        # The runner reads the key as its literal text before it picks the
        # key's schema, so `${{ 'default' }}` is an input's default and its
        # expression is evaluated; judged by the spelling instead, the valid
        # expression beneath it would be reported.
        manifest = {
            "inputs": {"ref": {"${{ 'default' }}": "${{ github.ref }}"}},
            "${{ 'runs' }}": {
                "using": "composite",
                "steps": [{"run": "${{ inputs.ref }}", "shell": "sh"}],
            },
        }
        self.assertEqual(judge("action.yml", manifest), [])

    def test_a_finding_beneath_an_escaped_key_names_it_as_written(self) -> None:
        # An author searches for the spelling in the file, not the text the
        # runner turns it into.
        manifest = {"${{ 'runs' }}": {"using": "${{ inputs.kind }}"}}
        self.assertEqual(
            [f.position for f in judge("action.yml", manifest)],
            ["${{ 'runs' }}.using"],
        )

    def test_a_literal_beside_text_or_another_expression_is_a_finding(self) -> None:
        # Only the whole string as one literal is turned into text; anything
        # else is an expression, which these positions refuse.
        for text in (
            "${{ 'a' }} and text",
            "${{ 'a' }}${{ 'b' }}",
            "${{ 'a' || inputs.b }}",
            "${{ 'unclosed }}",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    [f.position for f in judge("a.yml", {"description": text})],
                    ["description"],
                )
                self.assertEqual(
                    [f.what for f in judge("a.yml", {"inputs": {text: {}}})],
                    ["a key holds a ${{ }} expression"],
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


def step(**fields: object) -> dict[str, object]:
    """A composite action whose one step has `fields`."""
    return {
        "name": "a",
        "description": "d",
        "runs": {"using": "composite", "steps": [{"shell": "sh", **fields}]},
    }


def problems(manifest: object) -> list[tuple[str, str]]:
    return [(f.position, f.what) for f in judge("action.yml", manifest)]


class Contexts(unittest.TestCase):
    def test_a_secret_in_a_composite_run_is_a_finding(self) -> None:
        # The mistake this exists for: an action cannot read the caller's
        # secrets, so the manifest fails to load though `run:` is evaluated.
        self.assertEqual(
            problems(step(run="curl -H ${{ secrets.TOKEN }} x")),
            [
                (
                    "runs.steps[0].run",
                    "names secrets, which is not a context GitHub provides here",
                )
            ],
        )

    def test_each_position_has_its_own_contexts(self) -> None:
        # Transcribed from the schema's lists; each of these loads.
        manifest = {
            "inputs": {"ref": {"default": "${{ github.ref }}-${{ hashFiles('x') }}"}},
            "outputs": {"o": {"value": "${{ steps.s.outputs.o }}${{ env.E }}"}},
            "runs": {
                "using": "composite",
                "steps": [
                    {
                        "id": "s",
                        "if": "${{ success() && inputs.ok }}",
                        "name": "${{ matrix.os }} ${{ strategy.job-index }}",
                        "run": "${{ runner.os }} ${{ job.status }} ${{ hashFiles('a') }}",
                        "shell": "${{ inputs.shell }}",
                        "working-directory": "${{ github.workspace }}",
                        "continue-on-error": "${{ inputs.lenient }}",
                        "env": {"${{ inputs.name }}": "${{ steps.s.outputs.v }}"},
                    }
                ],
            },
        }
        self.assertEqual(problems(manifest), [])

    def test_a_context_one_position_has_another_lacks(self) -> None:
        # An input's default is read before the action's inputs exist, an
        # output has no hashFiles, and a docker action's args and env see
        # only its inputs; only a step's `if` has the status functions.
        for manifest, position, what in (
            (
                {"inputs": {"a": {"default": "${{ inputs.b }}"}}},
                "inputs.a.default",
                "names inputs, which is not a context GitHub provides here",
            ),
            (
                {"outputs": {"o": {"value": "${{ hashFiles('x') }}"}}},
                "outputs.o.value",
                "calls hashFiles(), which is not a function GitHub provides here",
            ),
            (
                {"runs": {"using": "docker", "args": ["${{ github.sha }}"]}},
                "runs.args[0]",
                "names github, which is not a context GitHub provides here",
            ),
            (
                {"runs": {"using": "docker", "env": {"A": "${{ env.B }}"}}},
                "runs.env.A",
                "names env, which is not a context GitHub provides here",
            ),
            (
                step(run="${{ success() }}"),
                "runs.steps[0].run",
                "calls success(), which is not a function GitHub provides here",
            ),
            (
                step(uses="./x", **{"with": {"k": "${{ vars.V }}"}}),
                "runs.steps[0].with.k",
                "names vars, which is not a context GitHub provides here",
            ),
        ):
            with self.subTest(position=position):
                self.assertEqual(problems(manifest), [(position, what)])

    def test_a_key_in_a_mapping_with_a_context_is_judged_by_it(self) -> None:
        manifest = step(run="x", env={"${{ secrets.NAME }}": "v"})
        self.assertEqual(
            problems(manifest),
            [
                (
                    "runs.steps[0].env.${{ secrets.NAME }}",
                    "names secrets, which is not a context GitHub provides here",
                )
            ],
        )

    def test_names_and_functions_ignore_case_as_the_runner_does(self) -> None:
        self.assertEqual(
            problems(step(run="${{ GitHub.SHA }} ${{ HASHFILES('a') }}")), []
        )
        self.assertEqual(
            [what for _, what in problems(step(run="${{ Secrets.T }}"))],
            ["names Secrets, which is not a context GitHub provides here"],
        )

    def test_only_a_named_value_is_a_context(self) -> None:
        # A property, a string, a function's argument that is a string, and
        # the literal words name no context; reading any of them as one would
        # fail a manifest that loads.
        for expression in (
            "steps.secrets.outputs.x",
            "github.event['secrets']",
            "fromJSON(inputs.x).secrets",
            "format('{0} secrets', inputs.x)",
            "true && null || 1.5 != NaN && Infinity",
            "toJSON(github.*.secrets)",
            "case(inputs.a, 'x', 'y')",
        ):
            with self.subTest(expression=expression):
                self.assertEqual(problems(step(run="${{ " + expression + " }}")), [])

    def test_a_context_inside_a_call_or_an_index_is_found(self) -> None:
        for expression in (
            "format('{0}', secrets.T)",
            "github.event[secrets.key]",
            "!secrets.T",
            "(inputs.a || secrets.T)",
        ):
            with self.subTest(expression=expression):
                self.assertEqual(
                    [
                        what
                        for _, what in problems(step(run="${{ " + expression + " }}"))
                    ],
                    ["names secrets, which is not a context GitHub provides here"],
                )

    def test_the_literal_words_are_case_sensitive(self) -> None:
        # `True` is not the literal `true` to the runner's lexer, so it is a
        # named value, and no position has one by that name.
        self.assertEqual(
            [what for _, what in problems(step(run="${{ True }}"))],
            ["names True, which is not a context GitHub provides here"],
        )

    def test_a_name_used_twice_in_one_string_is_reported_once(self) -> None:
        self.assertEqual(
            len(problems(step(run="${{ secrets.A }} ${{ secrets.B }}"))), 1
        )

    def test_an_unknown_function_is_a_finding(self) -> None:
        self.assertEqual(
            [what for _, what in problems(step(run="${{ toYaml(inputs.a) }}"))],
            ["calls toYaml(), which is not a function GitHub provides here"],
        )

    def test_an_unterminated_or_empty_expression_is_a_finding(self) -> None:
        # The runner refuses both wherever they sit, evaluated or not.
        self.assertEqual(
            [what for _, what in problems(step(run="echo ${{ inputs.a"))],
            ["holds a ${{ with no }} after it"],
        )
        self.assertEqual(
            [what for _, what in problems(step(run="echo ${{  }}"))],
            ["holds an empty ${{ }}"],
        )

    def test_the_insert_directive_is_a_key_not_a_context(self) -> None:
        # As the whole key of a mapping with a context it splices in a
        # mapping, which loads; as a value it is no context at all.
        manifest = step(run="x", env={"${{ insert }}": "${{ fromJSON(inputs.e) }}"})
        self.assertEqual(problems(manifest), [])
        self.assertEqual(
            [what for _, what in problems(step(run="${{ insert }}"))],
            ["names insert, which is not a context GitHub provides here"],
        )


class BareConditions(unittest.TestCase):
    """A step `if:` without delimiters is one expression, which the runner
    checks against its own list of step condition names."""

    def test_a_bare_condition_naming_a_secret_is_a_finding(self) -> None:
        self.assertEqual(
            problems(step(run="x", **{"if": "secrets.T != ''"})),
            [
                (
                    "runs.steps[0].if",
                    "names secrets, which is not a context GitHub provides here",
                )
            ],
        )

    def test_the_bare_list_has_needs_and_vars_where_the_schema_does_not(
        self,
    ) -> None:
        # Both lists are the runner's; they differ, so `vars` loads bare and
        # fails inside delimiters.
        for condition in (
            "vars.V == 'a' && needs.b.result == 'success'",
            "success() && inputs.ok && hashFiles('a') != ''",
            "",
            "  ",
        ):
            with self.subTest(condition=condition):
                self.assertEqual(problems(step(run="x", **{"if": condition})), [])
        self.assertEqual(
            [what for _, what in problems(step(run="x", **{"if": "${{ vars.V }}"}))],
            ["names vars, which is not a context GitHub provides here"],
        )

    def test_an_escaped_literal_condition_is_read_as_a_bare_one(self) -> None:
        # The runner turns it into its text, then reads that text as the
        # condition.
        self.assertEqual(
            [
                what
                for _, what in problems(step(run="x", **{"if": "${{ 'secrets.T' }}"}))
            ],
            ["names secrets, which is not a context GitHub provides here"],
        )

    def test_a_bare_condition_elsewhere_is_not_read(self) -> None:
        # pre-if and post-if are read when the action runs, not when it loads.
        manifest = {"runs": {"using": "node24", "main": "a.js", "pre-if": "secrets.T"}}
        self.assertEqual(problems(manifest), [])


if __name__ == "__main__":
    unittest.main()
