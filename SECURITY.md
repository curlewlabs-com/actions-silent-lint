# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it
privately via
[GitHub's security advisory feature](https://github.com/curlewlabs-com/actions-silent-lint/security/advisories/new).

Do not open a public issue for security vulnerabilities.

## Scope

The lint reads workflow and action files and runs `git ls-files` and `yq`. It
never runs what it reads. The security surface is:

- **The `git` and `yq` it runs.** These are the first on `PATH`, trusted the way
  `python3` is. Each is given a file name, never file contents as arguments.
- **The files it reads.** These are the repository's tracked workflows and
  actions.
- **Its own modules.** The action runs with the judged repository as its
  working directory and sets Python's import path to its own package alone,
  replacing any inherited one, so a file in the repository cannot stand in for
  a module of the lint or of the standard library.
