"""The `actions-silent-lint` command: judge a repository's workflow_run
triggers and action manifests.

    actions-silent-lint

It reads every tracked `.github/workflows/*.yml` and `*.yaml` of the current
directory's repository, and every tracked `action.yml` and `action.yaml` at any
depth, from the repository root wherever it is run. Each file is parsed by
mikefarah's `yq` from PATH, with anchors and aliases expanded, so the document
judged is the one GitHub reads, not its text. It prints one line per finding
and exits 1 on any; it also exits 1, with the reason on stderr, when it could
not judge, since a lint that did not run must not read as clean. A
`workflows:` entry that is a pattern is not judged and never fails the run;
how many there were is printed to stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from actions_silent_lint import manifests, parents

# Glob magic, so `*` stops at a `/`: GitHub reads workflows only from the
# directory itself, and a file under a subdirectory of it is not a workflow.
WORKFLOW_GLOBS = (
    ":(glob).github/workflows/*.yml",
    ":(glob).github/workflows/*.yaml",
)
# `**/` also matches no directory at all, so a manifest at the root is read.
MANIFEST_GLOBS = (":(glob)**/action.yml", ":(glob)**/action.yaml")


class CouldNotRun(Exception):
    pass


def _run(argv: list[str], cwd: Path, what: str) -> bytes:
    try:
        return subprocess.run(argv, cwd=cwd, capture_output=True, check=True).stdout
    except FileNotFoundError as error:
        raise CouldNotRun(f"{argv[0]} is not on PATH") from error
    except subprocess.CalledProcessError as error:
        stderr = error.stderr.decode(errors="replace").strip()
        raise CouldNotRun(f"{what} failed: {stderr}") from error


def repository_root(cwd: Path) -> Path:
    # Only git's terminating newline is removed: a path may end in whitespace,
    # and it is bytes in the filesystem's encoding, not necessarily UTF-8.
    out = _run(["git", "rev-parse", "--show-toplevel"], cwd, "git rev-parse")
    return Path(os.fsdecode(out.removesuffix(b"\n")))


def tracked(root: Path, globs: Sequence[str]) -> list[str]:
    listed = _run(["git", "ls-files", "-z", "--", *globs], root, "git ls-files")
    return [os.fsdecode(name) for name in listed.split(b"\0") if name]


def parse(root: Path, name: str) -> object:
    out = _run(
        ["yq", "--input-format=yaml", "--output-format=json", "explode(.)", name],
        root,
        f"parsing {name}",
    )
    try:
        return json.loads(out)
    except json.JSONDecodeError as error:
        # A file of several YAML documents prints one JSON document for each.
        raise CouldNotRun(
            f"parsing {name}: yq did not print exactly one JSON document"
        ) from error


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="actions-silent-lint",
        description="Check that every workflow_run trigger names a workflow that"
        " exists, and that no action manifest holds an expression where GitHub"
        " does not evaluate one.",
    )
    parser.parse_args(argv)
    try:
        root = repository_root(Path.cwd())
        workflows = {name: parse(root, name) for name in tracked(root, WORKFLOW_GLOBS)}
        actions = {name: parse(root, name) for name in tracked(root, MANIFEST_GLOBS)}
    except CouldNotRun as error:
        print(f"ERROR: actions-silent-lint could not run: {error}", file=sys.stderr)
        return 1
    verdict = parents.judge(workflows)
    findings: list[parents.Finding | manifests.Finding] = list(verdict.findings)
    for name, document in actions.items():
        findings.extend(manifests.judge(name, document))
    for finding in findings:
        print(finding)
    if verdict.unchecked:
        count = len(verdict.unchecked)
        are = (
            "entry is a pattern and was"
            if count == 1
            else "entries are patterns and were"
        )
        print(f"{count} workflow_run {are} not checked:", file=sys.stderr)
        for entry in verdict.unchecked:
            print(f"  {entry}", file=sys.stderr)
    return 1 if findings else 0
