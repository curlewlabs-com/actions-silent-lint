"""Judge one parsed action manifest: is every `${{ }}` in a position GitHub
evaluates?

GitHub template-validates a whole `action.yml` before it runs any step of it,
and that validation reaches strings it never evaluates, an input's
`description:` among them. An expression written there is not inert text: if
it names a context the position does not have, and a description has none,
the manifest fails to load, on the first job that uses the action. Nothing
reports it before then.

WHICH POSITIONS ARE EVALUATED is transcribed from the runner's action metadata
schema, not reasoned out: a position accepts `${{ }}` where that schema gives
it a context, and every position it types as a plain string rejects one.
https://github.com/actions/runner/blob/main/src/Runner.Worker/action_yaml.json

    EVALUATED
    inputs.<id>.default
    outputs.<id>.value
    runs.args[*], runs.env.*                a docker action's argv and env
    runs.steps[*].name / if / run / shell
    runs.steps[*].working-directory
    runs.steps[*].continue-on-error
    runs.steps[*].env.*, with.*

    NOT EVALUATED, so an expression is a finding
    name, author, description
    inputs.<id>.description / deprecationMessage
    outputs.<id>.description
    branding.icon / color
    runs.using, image, entrypoint, pre-entrypoint, post-entrypoint
    runs.main, pre, post, plugin
    runs.pre-if / post-if                   a bare condition: no delimiters
    runs.steps[*].id / uses
    any position not named above

A composite step is either a run step or a uses step, and the evaluated set
unions their fields, so `with:` under a `run:` step reads as evaluated here.
GitHub rejects that step for the unexpected key anyway, and the union is the
direction that cannot fail a manifest GitHub accepts.

A mapping's KEYS are positions too: the runner reads a key as a template only
inside a mapping that has a context, and the only such mappings are the
`env:` and `with:` subtrees above. So a key is judged by the same table as a
value at its position.

An unnamed position counts as not evaluated, so the table fails closed: a
field GitHub starts evaluating shows up as a finding on a manifest that loads,
which is loud and is fixed by naming it above.

This decides where an expression may sit, not which contexts it may name
there: `${{ secrets.TOKEN }}` in a composite `run:` fails to load and passes
here, since knowing that means parsing the expression language. The same
limit runs the other way once: a string that is one expression holding only a
quoted string literal is turned into that text before its position is
checked, so GitHub accepts it anywhere, and this still reports it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

# The opener alone, not a whole expression: an unterminated `${{` fails to load
# too, and requiring the closer would pass it as plain text.
EXPRESSION_OPEN: Final = "${{"

# A manifest position, where None stands for one element the author names: an
# input or output id, or a step's index.
Pattern = tuple[str | None, ...]

ANY: Final[str | None] = None

# Single strings, matched at exactly their own depth: the same key nested
# anywhere else is a different position.
EVALUATED_FIELDS: Final[tuple[Pattern, ...]] = (
    ("inputs", ANY, "default"),
    ("outputs", ANY, "value"),
    ("runs", "steps", ANY, "name"),
    ("runs", "steps", ANY, "if"),
    ("runs", "steps", ANY, "run"),
    ("runs", "steps", ANY, "shell"),
    ("runs", "steps", ANY, "working-directory"),
    ("runs", "steps", ANY, "continue-on-error"),
)

# Mappings and sequence items whose context covers every string beneath them.
# For `args` the context is on each item, not on the list, so an expression
# standing in for the whole list is not evaluated.
EVALUATED_SUBTREES: Final[tuple[Pattern, ...]] = (
    ("runs", "args", ANY),
    ("runs", "env"),
    ("runs", "steps", ANY, "env"),
    ("runs", "steps", ANY, "with"),
)

Position = tuple[str | int, ...]


def _matches(position: Position, pattern: Pattern) -> bool:
    if len(position) != len(pattern):
        return False
    return all(
        expected is ANY or element == expected
        for element, expected in zip(position, pattern, strict=True)
    )


def is_evaluated(position: Position) -> bool:
    if any(_matches(position, pattern) for pattern in EVALUATED_FIELDS):
        return True
    return any(
        len(position) >= len(pattern) and _matches(position[: len(pattern)], pattern)
        for pattern in EVALUATED_SUBTREES
    )


def render(position: Position) -> str:
    """A position as an author searches for it: `inputs.token.description`."""
    rendered = ""
    for element in position:
        if isinstance(element, int):
            rendered += f"[{element}]"
        elif rendered:
            rendered += f".{element}"
        else:
            rendered = element
    return rendered


@dataclass(frozen=True)
class Finding:
    path: str
    position: str
    what: str

    def __str__(self) -> str:
        return f"{self.path}: {self.position}: {self.what}"


def judge(path: str, manifest: object) -> list[Finding]:
    """Every expression in a position GitHub does not evaluate, in document
    order, so one run reports all of them."""
    if not isinstance(manifest, Mapping):
        # Nothing is read from such a document, so passing it would be a pass
        # over nothing; GitHub cannot load it as an action either.
        return [Finding(path, "-", "the file is not an action mapping")]
    findings: list[Finding] = []

    def walk(node: object, position: Position) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                name = str(key)
                here = (*position, name)
                if EXPRESSION_OPEN in name and not is_evaluated(here):
                    findings.append(
                        Finding(path, render(here), "a key holds a ${{ }} expression")
                    )
                walk(value, here)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, (*position, index))
        elif (
            isinstance(node, str)
            and EXPRESSION_OPEN in node
            and not is_evaluated(position)
        ):
            findings.append(
                Finding(
                    path,
                    render(position),
                    "holds a ${{ }} expression where GitHub does not evaluate one",
                )
            )

    walk(manifest, ())
    return findings
