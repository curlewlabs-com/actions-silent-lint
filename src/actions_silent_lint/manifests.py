"""Judge one parsed action manifest: is every `${{ }}` in a position GitHub
evaluates, and does it name only what that position provides?

GitHub template-validates a whole `action.yml` before it runs any step of it,
and that validation reaches strings it never evaluates, an input's
`description:` among them. An expression written there is not inert text: if
it names a context the position does not have, and a description has none,
the manifest fails to load, on the first job that uses the action. Nothing
reports it before then. The same holds where an expression is evaluated: a
composite step's `run:` has no `secrets` context, since an action cannot read
the caller's secrets, so `${{ secrets.TOKEN }}` there fails to load too.

WHICH POSITIONS ARE EVALUATED, AND WITH WHAT, is transcribed from the runner's
action metadata schema, not reasoned out: a position accepts `${{ }}` where
that schema gives it a context, its expressions may name only the contexts
and functions listed there, and every position it types as a plain string
rejects an expression.
https://github.com/actions/runner/blob/main/src/Runner.Worker/action_yaml.json

    EVALUATED                               the schema's context list
    inputs.<id>.default                     input-default-context
    outputs.<id>.value                      output-value
    runs.args[*], runs.env.*                container-runs-context / -env
    runs.steps[*].name / run / shell        string-steps-context
    runs.steps[*].working-directory         string-steps-context
    runs.steps[*].continue-on-error         boolean-steps-context
    runs.steps[*].if                        step-if
    runs.steps[*].env.*, with.*             step-env / step-with

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

Besides the functions a position lists, every expression may call the
expression language's own (`contains`, `format`, `toJSON` and the rest), and
names and functions are compared ignoring case, as the runner's parser does.

A composite step's `if:` is also read without delimiters, as one expression
(`if: inputs.ok == 'true'`). The runner checks that form against its own list
of step condition names, which `PipelineTemplateConverter` keeps apart from
the schema and which adds `needs` and `vars`, so it is judged against that.

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

A string that is one expression holding only a quoted string literal,
`${{ 'Use ${{ inputs.token }} here' }}`, is not an expression to GitHub: the
runner turns it into the literal's text before it checks the position, so it
loads anywhere, and it is read here the same way (expressions.py).

This decides where an expression may sit and what it may name there, not
whether the rest of it parses: `${{ inputs.a == }}` passes here and fails to
load.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from actions_silent_lint.expressions import (
    NotClosed,
    literal_text,
    references,
    segments,
    trim,
)
from actions_silent_lint.shapes import is_list, is_mapping

# The opener alone, not a whole expression: an unterminated `${{` fails to load
# too, and requiring the closer would pass it as plain text.
EXPRESSION_OPEN: Final = "${{"

# A manifest position, where None stands for one element the author names: an
# input or output id, or a step's index.
Pattern = tuple[str | None, ...]

ANY: Final[str | None] = None


@dataclass(frozen=True)
class Context:
    """What the expressions at an evaluated position may name: its contexts,
    and the functions it adds to the ones every expression has."""

    named_values: frozenset[str]
    functions: frozenset[str] = frozenset()

    def provides_named_value(self, name: str) -> bool:
        return name.lower() in {value.lower() for value in self.named_values}

    def provides_function(self, name: str) -> bool:
        known = EVERY_EXPRESSIONS_FUNCTIONS | self.functions
        return name.lower() in {function.lower() for function in known}


# The expression language's own functions (ExpressionConstants in the runner).
EVERY_EXPRESSIONS_FUNCTIONS: Final = frozenset(
    {
        "case",
        "contains",
        "endsWith",
        "format",
        "fromJson",
        "join",
        "startsWith",
        "toJson",
    }
)

# The schema's context lists, by its definition names.
_STEPS: Final = frozenset(
    {"github", "inputs", "strategy", "matrix", "steps", "job", "runner", "env"}
)
STRING_STEPS_CONTEXT: Final = Context(_STEPS, frozenset({"hashFiles"}))
STEP_IF: Final = Context(
    _STEPS,
    frozenset({"always", "failure", "cancelled", "success", "hashFiles"}),
)
INPUT_DEFAULT_CONTEXT: Final = Context(
    frozenset({"github", "strategy", "matrix", "job", "runner"}),
    frozenset({"hashFiles"}),
)
OUTPUT_VALUE: Final = Context(_STEPS)
CONTAINER_RUNS_CONTEXT: Final = Context(frozenset({"inputs"}))

# A step `if:` written without delimiters, which the schema does not read as
# an expression; the runner's PipelineTemplateConverter checks it against
# these (s_stepNamedValues and s_stepConditionFunctions).
BARE_STEP_IF: Final = Context(_STEPS | {"needs", "vars"}, STEP_IF.functions)

STEP_IF_POSITION: Final[Pattern] = ("runs", "steps", ANY, "if")

# Single strings, matched at exactly their own depth: the same key nested
# anywhere else is a different position.
EVALUATED_FIELDS: Final[tuple[tuple[Pattern, Context], ...]] = (
    (("inputs", ANY, "default"), INPUT_DEFAULT_CONTEXT),
    (("outputs", ANY, "value"), OUTPUT_VALUE),
    (("runs", "steps", ANY, "name"), STRING_STEPS_CONTEXT),
    (STEP_IF_POSITION, STEP_IF),
    (("runs", "steps", ANY, "run"), STRING_STEPS_CONTEXT),
    (("runs", "steps", ANY, "shell"), STRING_STEPS_CONTEXT),
    (("runs", "steps", ANY, "working-directory"), STRING_STEPS_CONTEXT),
    (("runs", "steps", ANY, "continue-on-error"), STRING_STEPS_CONTEXT),
)

# Mappings and sequence items whose context covers every string beneath them.
# For `args` the context is on each item, not on the list, so an expression
# standing in for the whole list is not evaluated.
EVALUATED_SUBTREES: Final[tuple[tuple[Pattern, Context], ...]] = (
    (("runs", "args", ANY), CONTAINER_RUNS_CONTEXT),
    (("runs", "env"), CONTAINER_RUNS_CONTEXT),
    (("runs", "steps", ANY, "env"), STRING_STEPS_CONTEXT),
    (("runs", "steps", ANY, "with"), STRING_STEPS_CONTEXT),
)

Position = tuple[str | int, ...]


def _matches(position: Position, pattern: Pattern) -> bool:
    if len(position) != len(pattern):
        return False
    return all(
        expected is ANY or element == expected
        for element, expected in zip(position, pattern, strict=True)
    )


def context(position: Position) -> Context | None:
    """The context of an evaluated position, or None where GitHub evaluates
    no expression."""
    for pattern, found in EVALUATED_FIELDS:
        if _matches(position, pattern):
            return found
    for pattern, found in EVALUATED_SUBTREES:
        if len(position) >= len(pattern) and _matches(
            position[: len(pattern)], pattern
        ):
            return found
    return None


def is_evaluated(position: Position) -> bool:
    return context(position) is not None


def holds_expression(text: str) -> bool:
    """Whether GitHub reads `text` as holding an expression, not as plain
    text: an unterminated `${{` counts, an escaped literal does not."""
    return EXPRESSION_OPEN in text and literal_text(text) is None


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


NOT_EVALUATED: Final = "holds a ${{ }} expression where GitHub does not evaluate one"

# The runner's one directive, legal as the whole key of a mapping that has a
# context, where it splices in a mapping the expression evaluates to.
INSERT_DIRECTIVE: Final = "insert"


def _named(expression: str, provided: Context) -> list[str]:
    """What an expression names that `provided` does not, each said once."""
    named, functions = references(expression)
    problems: list[str] = []
    for name in dict.fromkeys(named):
        if not provided.provides_named_value(name):
            problems.append(
                f"names {name}, which is not a context GitHub provides here"
            )
    for name in dict.fromkeys(functions):
        if not provided.provides_function(name):
            problems.append(
                f"calls {name}(), which is not a function GitHub provides here"
            )
    return problems


def evaluated(text: str, provided: Context, *, key: bool = False) -> list[str]:
    """What is wrong with the expressions in `text` at a position whose
    context is `provided`; an empty list when GitHub loads it."""
    try:
        parts = segments(text)
    except NotClosed:
        return ["holds a ${{ with no }} after it"]
    problems: list[str] = []
    for is_expression, inner in parts:
        if not is_expression:
            continue
        expression = trim(inner)
        if not expression:
            problems.append("holds an empty ${{ }}")
        elif not (key and len(parts) == 1 and expression == INSERT_DIRECTIVE):
            problems.extend(_named(expression, provided))
    return list(dict.fromkeys(problems))


def bare_condition(text: str) -> list[str]:
    """What is wrong with a step `if:` the runner reads as one expression
    without delimiters, which is every one holding no `${{` and the text of
    an escaped literal."""
    read = literal_text(text)
    condition = text if read is None else read
    if not condition.strip():
        return []
    return _named(trim(condition), BARE_STEP_IF)


def judge(path: str, manifest: object) -> list[Finding]:
    """Every expression GitHub would refuse, by its position and by what it
    names, in document order, so one run reports all of them."""
    if not is_mapping(manifest):
        # Nothing is read from such a document, so passing it would be a pass
        # over nothing; GitHub cannot load it as an action either.
        return [Finding(path, "-", "the file is not an action mapping")]
    findings: list[Finding] = []

    def text(value: str, position: Position, *, key: bool) -> list[str]:
        provided = context(position)
        if provided is None:
            if not holds_expression(value):
                return []
            return ["a key holds a ${{ }} expression" if key else NOT_EVALUATED]
        if (
            not key
            and _matches(position, STEP_IF_POSITION)
            and (EXPRESSION_OPEN not in value or literal_text(value) is not None)
        ):
            return bare_condition(value)
        return evaluated(value, provided, key=key)

    # `position` is what GitHub matches against its schema, with each key it
    # reads as an escaped literal turned into that literal's text; `written`
    # is the same position as the author spelled it, which is what a finding
    # names.
    def walk(node: object, position: Position, written: Position) -> None:
        if is_mapping(node):
            for key, value in node.items():
                name = str(key)
                read = literal_text(name)
                here = (*position, name if read is None else read)
                shown = (*written, name)
                for what in text(name, here, key=True):
                    findings.append(Finding(path, render(shown), what))
                walk(value, here, shown)
        elif is_list(node):
            for index, value in enumerate(node):
                walk(value, (*position, index), (*written, index))
        elif isinstance(node, str):
            for what in text(node, position, key=False):
                findings.append(Finding(path, render(written), what))

    walk(manifest, (), ())
    return findings
