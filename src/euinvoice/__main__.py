"""Command-line interface: ``python -m euinvoice``.

Only ``artifacts fetch`` exists so far; ``validate``, ``convert`` and ``info`` follow (plan M8.3).
Each subcommand registers its handler with ``set_defaults(run=...)``.
Exit codes: 0 success, 1 failure, 2 usage error (argparse).
"""

import argparse
import sys
import typing as t

from euinvoice.errors import EuInvoiceError
from euinvoice.validate import artifacts


def _artifacts_fetch(args: argparse.Namespace) -> int:
    names = t.cast(list[artifacts.SourceName] | None, args.only)
    for name, path in artifacts.fetch(names).items():
        sys.stdout.write(f"{name}: {path}\n")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m euinvoice", description="EN 16931 e-invoicing toolkit (euinvoice)."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    group = commands.add_parser("artifacts", help="manage the official validation artifacts")
    actions = group.add_subparsers(dest="action", required=True)
    fetch = actions.add_parser(
        "fetch",
        help=f"download and verify the pinned artifacts into ${artifacts.ENV_VAR} "
        f"(default {artifacts.DEFAULT_CACHE_DIR})",
    )
    fetch.add_argument(
        "--only",
        action="append",
        metavar="NAME",
        choices=t.get_args(artifacts.SourceName),
        help="fetch only this source (repeatable); choices: %(choices)s",
    )
    fetch.set_defaults(run=_artifacts_fetch)
    return parser


def main(argv: t.Sequence[str] | None = None) -> int:
    """Run the CLI.

    Args:
        argv: Arguments without the program name; defaults to ``sys.argv[1:]``.

    Returns:
        The process exit code.
    """
    args = _parser().parse_args(argv)
    run = t.cast(t.Callable[[argparse.Namespace], int], args.run)
    try:
        return run(args)
    except EuInvoiceError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
