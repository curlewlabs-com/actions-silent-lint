"""Match a `workflows:` entry against workflow names the way GitHub does.

GitHub reads every entry of `on.workflow_run.workflows` as a filter pattern,
with the grammar its workflow syntax reference documents for path, branch, tag
and workflow name filters alike:
https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#filter-pattern-cheat-sheet

Where that reference leaves a case open, the answer here was measured, not
reasoned out, but not on `workflows:` itself: the matching runs on GitHub's
servers, and a `workflow_run` trigger fires only from a repository's default
branch, so a measurement of it would need one trigger per pattern on a default
branch. The filter was measured through `on.push.paths` instead: one workflow
per pattern on a scratch branch, one commit per name, and the runs GitHub
started recorded which pattern it matched against which name, and which
patterns it refused. That `workflows:` uses the same matcher is the inference
this module rests on, and the reference's own words are its support: "You can
use special characters in path, branch, tag, and workflow name filters", the
cheat sheet's opening line, and "The `workflows` filters accept glob
patterns", which points to that cheat sheet. tests/test_patterns.py holds every case and checks
this module against each one. What came out:

    *          any run of characters but `/`
    **         any run of characters; `**/` is the same, the `/` included
    ? and +    zero or one, and one or more, of the character, escaped
               character or [...] before; after `*`, `**`, `?` or `+` they are
               refused, and `***` is refused
    leading ?  the pattern is not anchored at its start, so it matches any
               name that ends the way the rest of it does; a leading + does
               nothing
    [...]      one letter or digit listed, or in a range of letters or of
               digits (A-z included); a leading ^ negates it, and the negated
               form also matches any other character; empty, unclosed, or
               holding anything else is refused
    \\c        c itself, for any punctuation or space; a trailing \\ is refused
    leading !  the entry removes the names it matches from those the entries
               before it selected; entries are applied in order (what that
               does to a list is not judged: parents.py counts a ! entry as
               not checked)
    else       the character itself: . ( ) | ^ $ { } # and the rest are
               literal, and case is significant

Some constructs are not modelled, and an entry using one is reported as not
checked rather than judged: a backslash before a letter or digit, which
GitHub hands to a regular expression engine (`\\d` matched a digit, `\\x75` a
`u`, `\\B` nothing at all, `\\i` was refused), so that engine's whole escape
grammar would need reproducing; and, none of them measured, a backslash or
anything outside ASCII inside a [...], a `]` with no `[` before it, and a run
of four or more `*`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

NEGATION: Final = "!"


class Invalid(Exception):
    """An entry GitHub refuses as a pattern; the message says why."""


class Unmodelled(Exception):
    """An entry using a construct whose meaning was not established."""


@dataclass(frozen=True)
class _Characters:
    """The characters one element of a pattern accepts: those in `ranges`,
    each inclusive, or with `negated` every other one."""

    ranges: tuple[tuple[str, str], ...]
    negated: bool = False

    def accepts(self, character: str) -> bool:
        inside = any(low <= character <= high for low, high in self.ranges)
        return inside != self.negated


def _only(character: str) -> _Characters:
    return _Characters(((character, character),))


# What `*` stands for, a run of anything but `/`, and what `**` and a leading
# `?` stand for, a run of anything. Whether `**` crosses a line break in a name
# was not measured; reading it as crossing one can only pass an entry, never
# report one.
_NOT_SLASH: Final = _Characters((("/", "/"),), negated=True)
_ANYTHING: Final = _Characters((), negated=True)

# One element in order: exactly one character ("one"), at most one ("opt"),
# or any number of them ("many"), each from a set.
_Element = tuple[str, _Characters]


@dataclass(frozen=True)
class Pattern:
    """One `workflows:` entry, compiled."""

    entry: str
    negated: bool
    # True when the entry holds no pattern syntax at all, so it matches only
    # the name it spells.
    literal: bool
    elements: tuple[_Element, ...]

    def matches(self, name: str) -> bool:
        """Whether the whole name matches, by walking every element the name
        could have reached at once rather than backtracking, so the work is
        bounded by the name's length times the pattern's, whatever either
        holds."""
        states = self._skipping({0})
        for character in name:
            reached: set[int] = set()
            for state in states:
                if state < len(self.elements):
                    kind, characters = self.elements[state]
                    if characters.accepts(character):
                        reached.add(state if kind == "many" else state + 1)
            if not reached:
                return False
            states = self._skipping(reached)
        return len(self.elements) in states

    def _skipping(self, states: set[int]) -> set[int]:
        """`states` and every element after one that may match nothing."""
        found = set(states)
        pending = list(states)
        while pending:
            state = pending.pop()
            if (
                state < len(self.elements)
                and self.elements[state][0] != "one"
                and state + 1 not in found
            ):
                found.add(state + 1)
                pending.append(state + 1)
        return found


def _is_letter(character: str) -> bool:
    return "a" <= character <= "z" or "A" <= character <= "Z"


def _is_digit(character: str) -> bool:
    return "0" <= character <= "9"


def _is_alphanumeric(character: str) -> bool:
    return _is_letter(character) or _is_digit(character)


def _bracket(text: str, start: int) -> tuple[_Characters, int]:
    """The characters the [...] opening at `start` accepts, and the index
    after its `]`."""
    i = start + 1
    negate = i < len(text) and text[i] == "^"
    if negate:
        i += 1
    members: list[tuple[str, str]] = []
    while i < len(text) and text[i] != "]":
        c = text[i]
        if not c.isascii() or c == "\\":
            raise Unmodelled(f"{c!r} inside [...]")
        if not _is_alphanumeric(c):
            raise Invalid(f"[...] may hold only letters, digits and ranges, not {c!r}")
        if i + 1 < len(text) and text[i + 1] == "-":
            if i + 2 >= len(text) or text[i + 2] == "]":
                raise Invalid("a range in [...] needs a character after its -")
            high = text[i + 2]
            if not high.isascii() or high == "\\":
                raise Unmodelled(f"{high!r} inside [...]")
            same_kind = (_is_letter(c) and _is_letter(high)) or (
                _is_digit(c) and _is_digit(high)
            )
            if not same_kind or c > high:
                raise Invalid(f"{c}-{high} is not a range of letters or of digits")
            members.append((c, high))
            i += 3
        else:
            members.append((c, c))
            i += 1
    if i >= len(text):
        raise Invalid("a [ is never closed")
    if not members:
        raise Invalid("[] holds nothing")
    return _Characters(tuple(members), negate), i + 1


def compile_entry(entry: str) -> Pattern:
    """Compile one entry, or raise Invalid or Unmodelled."""
    negated = entry.startswith(NEGATION)
    text = entry[len(NEGATION) :] if negated else entry
    elements: list[_Element] = []
    literal = not negated
    # What the last element was: None at the start, "atom" after a character
    # or a [...], "star" after * or **, "quantifier" after ? or +.
    last: str | None = None
    anchored = True
    i = 0
    while i < len(text):
        c = text[i]
        if c == "*":
            run = len(text) - i - len(text[i:].lstrip("*"))
            if run >= 4:
                raise Unmodelled("a run of four or more *")
            if run == 3:
                raise Invalid("*** is not a pattern")
            literal = False
            if run == 1:
                elements.append(("many", _NOT_SLASH))
                i += 1
            else:
                elements.append(("many", _ANYTHING))
                i += 2
                if i < len(text) and text[i] == "/":
                    i += 1
            last = "star"
        elif c in "?+":
            literal = False
            if last in ("star", "quantifier"):
                raise Invalid(f"{c} after {text[i - 1]} is not a pattern")
            if last is None:
                anchored = anchored and c == "+"
            elif c == "?":
                elements[-1] = ("opt", elements[-1][1])
            else:
                elements.append(("many", elements[-1][1]))
            last = "quantifier"
            i += 1
        elif c == "[":
            literal = False
            characters, i = _bracket(text, i)
            elements.append(("one", characters))
            last = "atom"
        elif c == "]":
            raise Unmodelled("a ] with no [ before it")
        elif c == "\\":
            literal = False
            if i + 1 >= len(text):
                raise Invalid("a pattern cannot end in \\")
            escaped = text[i + 1]
            if not escaped.isascii() or _is_alphanumeric(escaped):
                raise Unmodelled(f"\\{escaped}")
            elements.append(("one", _only(escaped)))
            last = "atom"
            i += 2
        else:
            elements.append(("one", _only(c)))
            last = "atom"
            i += 1
    if not anchored:
        elements.insert(0, ("many", _ANYTHING))
    return Pattern(entry, negated, literal, tuple(elements))
