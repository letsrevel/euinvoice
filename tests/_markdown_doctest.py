"""Runs the ``python`` code blocks of a Markdown file (README.md, docs/*.md) as tests, in one namespace per file.

A block whose first line starts with ``>>>`` is a doctest (its output is checked); any other block is a script,
executed with :func:`exec` (its ``assert`` statements are the checks). Blocks run in file order and share one
namespace, so a later block sees the names an earlier one defined.

An HTML comment on the line right before a block marks it:

* ``<!-- <prefix>: needs-artifacts -->``: needs the official artifacts (``validate``); it runs only with
  ``with_artifacts=True`` (the conformance suite).
* ``<!-- <prefix>: illustration -->``: shows code that needs software euinvoice does not depend on (e.g.
  WeasyPrint). It is compiled, so it stays valid Python, but never run.
"""

import dataclasses
import doctest
import pathlib
import re
import typing as t

Kind = t.Literal["run", "needs-artifacts", "illustration"]


@dataclasses.dataclass(frozen=True, slots=True)
class Block:
    """One ``python`` block: its marker, its source and where it starts (``file:line``)."""

    kind: Kind
    body: str
    name: str
    line: int

    @property
    def is_doctest(self) -> bool:
        """Whether the block is written as a doctest (``>>>`` prompts)."""
        return self.body.lstrip().startswith(">>>")


def blocks(path: pathlib.Path, *, prefix: str) -> list[Block]:
    """The ``python`` blocks of ``path``, with the marker each carries (``prefix`` is the comment's prefix)."""
    pattern = re.compile(
        r"(?:<!-- " + re.escape(prefix) + r": (?P<marker>needs-artifacts|illustration) -->\n)?"
        r"```python\n(?P<body>.*?)^```",
        re.M | re.S,
    )
    text = path.read_text(encoding="utf-8")
    found = []
    for match in pattern.finditer(text):
        line = text.count("\n", 0, match.start("body"))
        kind = t.cast(Kind, match["marker"] or "run")
        found.append(Block(kind, match["body"], f"{path.name}:{line + 1}", line))
    return found


def run(
    path: pathlib.Path, globs: dict[str, t.Any], *, prefix: str, with_artifacts: bool
) -> tuple[int, dict[str, t.Any]]:
    """Run the blocks of ``path`` in ``globs``; skip the ``needs-artifacts`` ones unless ``with_artifacts``.

    Returns:
        The number of doctest examples plus script blocks that ran, and the namespace afterwards.

    Raises:
        AssertionError: A doctest example failed; the message is doctest's report.
    """
    runner = doctest.DocTestRunner(optionflags=doctest.ELLIPSIS)
    parser = doctest.DocTestParser()
    report: list[str] = []
    ran = 0
    for block in blocks(path, prefix=prefix):
        if block.kind == "illustration":
            compile(block.body, block.name, "exec")
            continue
        if block.kind == "needs-artifacts" and not with_artifacts:
            continue
        if not block.is_doctest:
            # Docs examples are trusted, committed code; exec runs them like a reader would.
            exec(compile(block.body, block.name, "exec"), globs)  # ruff: ignore[exec-builtin]
            ran += 1
            continue
        # DocTest copies the globals it is given, so the shared namespace is set afterwards.
        test = parser.get_doctest(block.body, globs, block.name, str(path), block.line)
        test.globs = globs
        result = runner.run(test, out=report.append, clear_globs=False)
        assert result.failed == 0, "".join(report)
        ran += result.attempted
    return ran, globs
