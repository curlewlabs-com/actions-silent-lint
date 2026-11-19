# actions-silent-lint

## What it is

A lint for two GitHub Actions mistakes that GitHub accepts on push and that
nothing reports until it is too late:

```text
.github/workflows/publish.yml: workflow_run names "Build", which is no workflow's name:, so the trigger never fires
notify/action.yml: inputs.status.description: holds a ${{ }} expression where GitHub does not evaluate one
```

- **A `workflow_run` trigger that names no workflow.** The trigger never fires.
  No run fails and nothing is reported, so the workflow stops without anyone
  noticing.
- **A `${{ }}` expression an action manifest cannot hold**: one in a field
  GitHub does not evaluate, such as an input's `description:`, or one naming a
  context the field does not have, such as `secrets` in a composite step's
  `run:`. The action fails to load, on the first job that uses it.

## Why it exists

`on.workflow_run.workflows` names the parent workflows by their `name:`.
Renaming a workflow is an ordinary edit, and it strands every trigger that
named the old name. GitHub shows nothing for a trigger that matches nothing,
because to GitHub that trigger is just one that never matched.

GitHub validates a whole `action.yml` before it runs any step of it, and that
validation reaches fields it never evaluates. So an input described as "the
caller's `${{ job.status }}`" is a manifest that fails to load: `job` is not
something a description can name. The prose reads naturally, and the failure
arrives in whichever workflow first uses the action, which may be after merge.
The same goes for an action that reaches for `${{ secrets.TOKEN }}` in a step:
an action cannot read its caller's secrets, so the manifest fails to load
rather than the step failing.

Neither is caught by the common linters. With actionlint 1.7.12 and zizmor
1.32.0 (its `pedantic` persona), a trigger naming two workflows that do not
exist passes, and so does a local action whose `name:` and input
`description:` hold expressions. GitHub's own action validator,
`@actions/languageservice` (0.3.61 was tried, which is what GitHub's VS Code
extension uses), does report the manifest case, but only in the editor: it is a
library with no command line, so nothing runs it in CI. It does not check
`workflow_run` names.

## How to use it

As a GitHub Action, after a checkout. Pin it by commit:

```yaml
- uses: actions/checkout@<sha> # vX.Y.Z
  with:
    persist-credentials: false
- uses: curlewlabs-com/actions-silent-lint@<sha> # vX.Y.Z
```

As a command, from inside a repository, with `git` and
[mikefarah's yq](https://github.com/mikefarah/yq) on `PATH` (GitHub's Linux and
macOS runner images ship both):

```sh
pip install git+https://github.com/curlewlabs-com/actions-silent-lint@v0.2.1
actions-silent-lint
```

It reads every tracked workflow and action of the repository, prints one line
per finding and exits 1 on any. It also exits 1, with the reason on stderr,
when it could not run (no `git` or `yq`, a file `yq` cannot parse), so a lint
that did not run never reads as clean. It has no options.

## What it checks

Every file is parsed by `yq` with anchors and aliases expanded, so a value is
judged as GitHub reads it, not as it is written.

**`workflow_run` triggers.** Each tracked `.github/workflows/*.yml` and
`*.yaml`, in that directory itself as GitHub reads it. Every entry of
`on.workflow_run.workflows`, as a list or as one string, must match the `name:`
of one of them. GitHub reads each entry as a
[filter pattern](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#filter-pattern-cheat-sheet),
and the lint matches it the same way: `Build*` matches `Build and test` but not
`Build / test`, `Build C\+\+` matches `Build C++`, and an entry with no
pattern syntax matches only the name it spells, exactly. Each entry is judged
on its own: a pattern that matches no workflow is a finding, and so is an entry
GitHub refuses as a pattern (an unclosed `[`, for one). A list holding `!`
entries is judged as a whole too, since its negations can remove every
workflow the others match; that is a finding, made only when every entry was
judged and every workflow name is printable ASCII, like the names measured. A
workflow without a `name:` cannot be named this way: add one. A
workflow file whose top level is not a mapping, or a `workflows:` value that is
not a string or a list of strings, is a finding, since reading it as naming
nothing would pass the mistake this lint is for.

**Action manifests.** Each tracked `action.yml` and `action.yaml`, at any
depth. The lint allows a `${{` only where GitHub's action metadata schema
evaluates one: an input's `default`, an output's `value`, each entry of a
docker action's `args` (not `args` as a whole) and its `env`, and a composite
step's `name`, `if`, `run`, `shell`, `working-directory`, `continue-on-error`,
`env` and `with`. Anywhere else, mapping keys included, it is a finding. The
one exception is a string that is a single expression holding only a quoted
string, such as `${{ 'Use ${{ inputs.token }} here' }}`: GitHub turns it into
that text before it checks the position, so it loads anywhere, and the lint
reads it the same way.

Where an expression may sit, it may name only the contexts and functions the
schema lists for that field, besides the expression language's own functions:
a composite step's `run:` has `inputs`, `steps`, `env` and the others but not
`secrets` or `vars`, an input's `default` has no `inputs`, and only a step's
`if` has `success()` and the other status functions. A composite step's `if`
written without delimiters is read as one expression too, and judged against
the runner's list for that form. An unterminated or empty `${{` is a finding
wherever it is. A position the schema adds later is treated as not evaluated until the table in
`src/actions_silent_lint/manifests.py` names it, so a change in GitHub shows up
as a finding on a manifest that loads, never as a silent pass.

## What it does not check

- **`workflows:` itself, directly.** Where GitHub's reference leaves the
  pattern grammar open, the answer was measured on GitHub, but through a push's
  `paths:` filter: a `workflow_run` trigger fires only from a repository's
  default branch, so measuring one needs a trigger per pattern there. That
  `workflows:` matches the same way rests on the reference, whose cheat sheet
  covers "path, branch, tag, and workflow name filters" alike.
  `src/actions_silent_lint/patterns.py` says what was found, and
  `tests/test_patterns.py` holds every case.
- **Pattern constructs that were not measured**: a `\` before a letter or
  digit, which GitHub hands to a regular expression engine (`\d` matches a
  digit), a `\` or anything outside ASCII inside `[...]`, a `]` with no `[`,
  and a run of four or more `*`. An entry using one is not judged. It never
  fails the run, and the lint prints how many entries were skipped and which
  ones.
- **`!` entries the list cannot be read with.** When an entry of the list was
  dead, refused or not modelled, or a workflow name holds a line break or
  anything outside printable ASCII, which the measurement did not cover, the
  list is not judged as a whole and its `!` entries are counted as not checked
  in the same way. A `!` entry that removes no workflow is not reported, since
  it stops no trigger from firing.
- **The rest of an expression's syntax.** The lint reads which contexts and
  functions an expression names, not whether the rest of it parses, so
  `${{ inputs.a == }}` passes and fails to load.
- **Triggers that stopped matching for another reason**, such as a `branches:`
  filter the parent's runs no longer match, or a `workflow_run:` block that
  was deleted.

## License

Licensed under either of

- Apache License, Version 2.0 ([LICENSE-APACHE](LICENSE-APACHE))
- MIT license ([LICENSE-MIT](LICENSE-MIT))

at your option.

### Contribution

By submitting a contribution for inclusion in this project, you agree that it
is dual licensed as above, without any additional terms or conditions.
