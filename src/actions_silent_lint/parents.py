"""Judge the `workflow_run` triggers of a repository's parsed workflows: does
every parent a trigger names exist?

`on.workflow_run.workflows` names the workflows whose runs start this one, by
the parent's `name:`. An entry that names no workflow is not an error anywhere:
the trigger never fires, no run fails, and nothing reports it. Renaming a
workflow is an ordinary edit that strands every trigger naming its old name.

GitHub reads each entry as a filter pattern, and patterns.py matches them as
GitHub was measured to: an entry with no pattern syntax matches the one name
it spells, exactly. Each entry is judged on its own: one that matches no
workflow's name is a finding, and so is one GitHub refuses as a pattern. An
entry using a construct patterns.py does not model is counted and reported as
not checked rather than judged by a reading that could be wrong in either
direction.

A list holding `!` entries is also judged as a whole, since its negations can
remove every workflow the other entries match, and that trigger never fires
either. The whole-list reading is only as good as every part of it, so it is
made only when each entry was judged, none was dead, and every workflow name
is the kind the measurement used, printable ASCII; otherwise the `!` entries
are counted as not checked, as an unmodelled entry is.

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

from actions_silent_lint.patterns import (
    NEGATION,
    Invalid,
    Pattern,
    Unmodelled,
    compile_entry,
    selected,
)


@dataclass(frozen=True)
class Finding:
    path: str
    what: str

    def __str__(self) -> str:
        return f"{self.path}: {self.what}"


@dataclass(frozen=True)
class Unchecked:
    """A `workflows:` entry using a construct patterns.py does not model, so
    it was not judged."""

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
        verdict.findings.extend(_judge_trigger(path, entries, names, verdict))
    return verdict


def _measured_like(name: str) -> bool:
    """Whether a workflow name holds only the characters the measured names
    did: printable ASCII, the space included."""
    return all(" " <= character <= "~" for character in name)


def _judge_trigger(
    path: str, entries: list[str], names: set[str], verdict: Verdict
) -> list[Finding]:
    findings: list[Finding] = []
    patterns: list[Pattern] = []
    negations: list[str] = []
    judged_all = True
    for entry in entries:
        negated = entry.startswith(NEGATION)
        if negated:
            negations.append(entry)
        shown = json.dumps(entry)
        try:
            pattern = compile_entry(entry)
        except Invalid as reason:
            judged_all = False
            # Whether GitHub refuses a negation of an invalid pattern was not
            # measured, so only a positive entry is reported as refused.
            if negated:
                continue
            findings.append(
                Finding(
                    path,
                    f"workflow_run entry {shown} is not a pattern GitHub"
                    f" accepts: {reason}",
                )
            )
            continue
        except Unmodelled:
            judged_all = False
            if not negated:
                verdict.unchecked.append(Unchecked(path, entry))
            continue
        patterns.append(pattern)
        if negated or any(pattern.matches(name) for name in names):
            continue
        if pattern.literal:
            what = (
                f"workflow_run names {shown}, which is no workflow's name:,"
                " so the trigger never fires"
            )
        else:
            what = (
                f"workflow_run pattern {shown} matches no workflow's name:,"
                " so it never fires"
            )
            if entry in names:
                what += (
                    "; a workflow is named that, and matching it takes a \\"
                    " before each pattern character"
                )
        findings.append(Finding(path, what))
    if not negations:
        return findings
    if not judged_all or findings or not all(_measured_like(name) for name in names):
        verdict.unchecked.extend(Unchecked(path, entry) for entry in negations)
        return findings
    if not selected(patterns, names):
        findings.append(
            Finding(
                path,
                "workflow_run selects no workflow: a ! entry removes only names"
                " an entry before it matched, and these remove them all, so the"
                " trigger never fires",
            )
        )
    return findings
