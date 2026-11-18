"""Judge the `workflow_run` triggers of a repository's parsed workflows: does
every parent a trigger names exist?

`on.workflow_run.workflows` names the workflows whose runs start this one, by
the parent's `name:`. An entry that names no workflow is not an error anywhere:
the trigger never fires, no run fails, and nothing reports it. Renaming a
workflow is an ordinary edit that strands every trigger naming its old name.

Only literal entries are judged. GitHub reads each entry as a pattern, in which
`*`, `?`, `+`, `[`, `]`, `!` and `\\` have meanings, and that matching is done
by GitHub's servers, where it cannot be checked against its documentation. So
an entry holding any of those characters is counted and reported as not
checked, rather than judged by a matcher that could be wrong in either
direction. A literal entry matches a `name:` exactly.

The whole set of workflows is judged together, since a trigger's parent can be
any workflow in the repository, and GitHub fires `workflow_run` only for
workflows of the same repository. A document whose shape this module does not
read is a finding, never a pass: a trigger that reads as naming nothing is the
silent failure this exists to catch.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field

# The characters GitHub's filter pattern syntax gives a meaning to, the escape
# among them, since an escaped character is a pattern GitHub decodes.
PATTERN_CHARACTERS = frozenset("*?+[]!\\")


@dataclass(frozen=True)
class Finding:
    path: str
    what: str

    def __str__(self) -> str:
        return f"{self.path}: {self.what}"


@dataclass(frozen=True)
class Unchecked:
    """A `workflows:` entry that is a pattern, so it was not judged."""

    path: str
    entry: str

    def __str__(self) -> str:
        return f"{self.path}: {json.dumps(self.entry)}"


@dataclass(frozen=True)
class Verdict:
    findings: list[Finding] = field(default_factory=list)
    unchecked: list[Unchecked] = field(default_factory=list)


class Unreadable(Exception):
    """A document or value in a shape this module does not read."""


def workflow_name(document: object) -> str | None:
    """The top-level `name:`, or None for a workflow that has none.

    A name YAML reads as another type (`name: 1.0`) is still shown by GitHub as
    text, so it is turned into text rather than dropped, which would strand
    every entry naming it.
    """
    if not isinstance(document, Mapping):
        raise Unreadable("the document's top level is not a mapping")
    if "name" not in document:
        return None
    value = document["name"]
    return value if isinstance(value, str) else json.dumps(value)


def declared_parents(document: object) -> list[str]:
    """The entries of `on.workflow_run.workflows`, in the order written.

    The list form and a bare string (`workflows: CI`) are both read. The `on:`
    forms that cannot carry a `workflows:` key (`on: push`, `on: [push]`) and a
    `workflow_run:` without one declare nothing; any other value raises.
    """
    if not isinstance(document, Mapping):
        raise Unreadable("the document's top level is not a mapping")
    triggers = document.get("on")
    if not isinstance(triggers, Mapping):
        return []
    chain = triggers.get("workflow_run")
    if not isinstance(chain, Mapping) or "workflows" not in chain:
        return []
    value = chain["workflows"]
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        for entry in value:
            if not isinstance(entry, str):
                raise Unreadable(
                    f"workflows: holds an entry that is not a string: {entry!r}"
                )
        return list(value)
    raise Unreadable(f"workflows: is neither a list nor a string: {value!r}")


def is_pattern(entry: str) -> bool:
    return not PATTERN_CHARACTERS.isdisjoint(entry)


def judge(workflows: Mapping[str, object]) -> Verdict:
    """Judge every trigger in `workflows`, a map of each workflow's path to its
    parsed document, which must hold every workflow of the repository."""
    verdict = Verdict()
    names: set[str] = set()
    for path, document in workflows.items():
        try:
            name = workflow_name(document)
        except Unreadable as error:
            verdict.findings.append(Finding(path, str(error)))
            continue
        if name is not None:
            names.add(name)
    # A parent whose name could not be read would make every trigger naming it
    # look stranded, burying the one real finding under false ones.
    if verdict.findings:
        return verdict

    for path, document in workflows.items():
        try:
            entries = declared_parents(document)
        except Unreadable as error:
            verdict.findings.append(Finding(path, str(error)))
            continue
        for entry in entries:
            if is_pattern(entry):
                verdict.unchecked.append(Unchecked(path, entry))
            elif entry not in names:
                verdict.findings.append(
                    Finding(
                        path,
                        f"workflow_run names {json.dumps(entry)}, which is no"
                        " workflow's name:, so the trigger never fires",
                    )
                )
    return verdict
