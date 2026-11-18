"""`python3 -m actions_silent_lint`, the command-line entry point; cli.py owns it."""

from actions_silent_lint.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
