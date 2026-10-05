"""Command-line interface: ``python -m euinvoice``.

Only ``artifacts fetch`` exists so far; ``validate``, ``convert`` and ``info`` follow (plan M8.3).
Exit codes: 0 success, 1 failure, 2 usage error (argparse).
"""

import argparse
import sys
import typing as t

from euinvoice.errors import EuInvoiceError
from euinvoice.validate import artifacts


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m euinvoice", description=__doc__.splitlines()[0])
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
        choices=list(artifacts.load_manifest()),
        help="fetch only this source (repeatable); choices: %(choices)s",
    )
    return parser


def main(argv: t.Sequence[str] | None = None) -> int:
    """Run the CLI.

    Args:
        argv: Arguments without the program name; defaults to ``sys.argv[1:]``.

    Returns:
        The process exit code.
    """
    args = _parser().parse_args(argv)
    try:
        fetched = artifacts.fetch(args.only)
    except EuInvoiceError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    for name, path in fetched.items():
        sys.stdout.write(f"{name}: {path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
