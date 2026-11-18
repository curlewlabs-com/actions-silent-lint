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
- **A `${{ }}` expression in an action manifest field GitHub does not
  evaluate**, such as an input's `description:`. The action fails to load, on
  the first job that uses it.

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
pip install git+https://github.com/curlewlabs-com/actions-silent-lint@v0.1.0
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
`on.workflow_run.workflows`, as a list or as one string, must equal the `name:`
of one of them exactly. A workflow without a `name:` cannot be named this way:
add one. A workflow file whose top level is not a mapping, or a `workflows:`
value that is not a string or a list of strings, is a finding, since reading it
as naming nothing would pass the mistake this lint is for.

**Action manifests.** Each tracked `action.yml` and `action.yaml`, at any
depth. The lint allows a `${{` only where GitHub's action metadata schema
evaluates one: an input's `default`, an output's `value`, each entry of a
docker action's `args` (not `args` as a whole) and its `env`, and a composite
step's `name`, `if`, `run`, `shell`, `working-directory`, `continue-on-error`,
`env` and `with`. Anywhere else, mapping keys included, it is a finding (GitHub
accepts one form there that the lint still reports; see Known issues). A
position the schema adds later is treated as not evaluated until the table in
`src/actions_silent_lint/manifests.py` names it, so a change in GitHub shows up
as a finding on a manifest that loads, never as a silent pass.

## What it does not check

- **Pattern entries.** GitHub reads a `workflows:` entry as a pattern, where
  `*`, `?`, `+`, `[`, `]`, `!` and `\` have meanings. That matching happens on
  GitHub's servers, so an entry holding any of those characters is not judged.
  It never fails the run, and the lint prints how many entries were skipped and
  which ones. This also means a literal name holding one of those characters,
  such as `CI [x]`, is skipped, not passed as resolved: GitHub would read it as
  a pattern.
- **Which contexts an expression names.** The lint checks where an expression
  sits, not what it says. `${{ secrets.TOKEN }}` in a composite step's `run:`
  sits in an evaluated position, so it passes, but an action cannot read
  `secrets` and fails to load. GitHub's validator above reports it.
- **Triggers that stopped matching for another reason**, such as a `branches:`
  filter the parent's runs no longer match, or a `workflow_run:` block that
  was deleted.

## Known issues

- **An escaped literal is reported.** GitHub turns a string that is one
  expression holding only a quoted string, such as
  `description: "${{ 'Use ${{ inputs.token }} here' }}"`, into that literal
  text before it checks the position, so the manifest loads. The lint reports
  it anyway, as it reports any `${{` outside an evaluated position. Write the
  reference without the delimiters instead (`inputs.token`).

## License

Licensed under either of

- Apache License, Version 2.0 ([LICENSE-APACHE](LICENSE-APACHE))
- MIT license ([LICENSE-MIT](LICENSE-MIT))

at your option. Releases published under the MIT license alone may also be used
under either license.

### Contribution

By submitting a contribution for inclusion in this project, you agree that it
is dual licensed as above, without any additional terms or conditions.
