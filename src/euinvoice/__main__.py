"""Command-line interface: ``python -m euinvoice`` (plan §8, M8.3).

Subcommands (each registers its handler with ``set_defaults(run=...)``):

* ``validate FILE [--profile ID] [--json]``: :func:`euinvoice.validate` on a UBL / CII document or the invoice
  of a Factur-X / ZUGFeRD PDF; one line per finding, then a verdict line.
* ``convert FILE --to ubl|cii [--profile ID] [-o OUT]``: :func:`euinvoice.parse_detailed`, then
  :func:`euinvoice.to_xml`; the XML goes to ``OUT`` or stdout. Input that has no business term in the model is
  not converted, and each such XPath is reported on stderr (readers never drop input silently, plan §1).
* ``info FILE [--json]``: the detected syntax, root, BT-24 and profile, the Factur-X / ZUGFeRD container of a
  PDF, the invoice's BT-1, BT-2, BT-3, BT-5 and document totals (BG-22), and what was not mapped.
* ``artifacts fetch [--only NAME]``: download and verify the pinned official artifacts.

``FILE`` ``-`` reads stdin. ``--profile`` takes a :attr:`euinvoice.profiles.Profile.id`; without it the profile
comes from BT-24 (``validate`` falls back to EN 16931 core as :func:`euinvoice.validate` documents).

Exit codes:

* ``0``: success; ``validate`` found nothing ``fatal`` / ``error`` (warnings allowed).
* ``1``: the document was rejected: ``validate`` found a ``fatal`` / ``error`` finding, ``convert`` was refused
  by the pre-flight / calculation checks (the findings go to stderr), the input is not a readable invoice
  (malformed XML, unsupported root or profile, a PDF without one embedded invoice), or another euinvoice error
  (e.g. a failed artifact download).
* ``2``: no verdict, fix the command or the setup: a usage error (argparse, an unknown ``--profile``), ``FILE``
  cannot be read or ``OUT`` written, the artifacts are missing (the message names ``artifacts fetch``) or the
  profile's Schematron is not pinned, or an extra (``[pdf]``) is not installed.

JSON output (``--json``), one object on stdout:

* ``validate``: ``{"ok": bool, "findings": [{"rule_id", "severity", "location", "message", "source"}]}``, the
  fields of :class:`euinvoice.report.Finding` (``location`` may be ``null``).
* ``info``: ``{"syntax", "root", "specification_identifier", "profile", "pdf", "invoice", "unmapped"}``.
  ``profile`` is a profile id or ``null``; ``pdf`` is ``null`` for XML, else ``{"container",
  "conformance_level", "filename"}``; ``invoice`` maps the BT ids above to strings (dates ISO 8601, amounts as
  plain decimals) or ``null`` when absent; ``unmapped`` lists XPaths.

Errors are a single ``error: ...`` line on stderr in either mode.
"""

import argparse
import dataclasses
import datetime
import json
import sys
import typing as t
from decimal import Decimal
from pathlib import Path

from euinvoice import profiles
from euinvoice._api import parse_detailed, to_xml
from euinvoice.detect import detect, is_pdf
from euinvoice.errors import ArtifactsNotAvailableError, EuInvoiceError, PreflightError
from euinvoice.model.bt_index import path_of
from euinvoice.model.invoice import Invoice
from euinvoice.report import Finding, Severity, ValidationReport
from euinvoice.syntax import Syntax
from euinvoice.validate import artifacts, validate

if t.TYPE_CHECKING:
    from euinvoice.facturx import Extracted

PROFILES: t.Final[t.Mapping[str, profiles.Profile]] = {
    profile.id: profile for name in profiles.__all__ if isinstance(profile := getattr(profiles, name), profiles.Profile)
}
"""Every profile ``--profile`` accepts, by :attr:`~euinvoice.profiles.Profile.id`."""

# The terms ``info`` shows (EN 16931-1 §6.4; ids resolved to model paths by euinvoice.model.bt_index): invoice number,
# issue date, type code, currency, and the document totals BG-22 (BT-106 … BT-115).
_SUMMARY_TERMS: t.Final = ("BT-1", "BT-2", "BT-3", "BT-5", *(f"BT-{n}" for n in range(106, 116)))


def _read(file: str) -> bytes:
    """The bytes of ``file``, or of stdin for ``-``."""
    return sys.stdin.buffer.read() if file == "-" else Path(file).read_bytes()


def _xml_of(data: bytes) -> tuple[bytes, "Extracted | None"]:
    """The invoice XML of ``data`` and, for a Factur-X / ZUGFeRD PDF, what :func:`euinvoice.facturx.extract` found."""
    if not is_pdf(data):
        return data, None
    # Imported here so that XML input never needs pypdf (the ``[pdf]`` extra).
    from euinvoice import facturx

    found = facturx.extract(data)
    return found.xml, found


def _finding_line(finding: Finding) -> str:
    at = f" at {finding.location}" if finding.location else ""
    return f"{finding.severity} {finding.rule_id} [{finding.source}]{at}: {finding.message}\n"


def _validate(args: argparse.Namespace) -> int:
    xml, _ = _xml_of(_read(args.file))
    report: ValidationReport = validate(xml, args.profile)
    if args.json:
        payload = {"ok": report.ok, "findings": [dataclasses.asdict(f) for f in report.findings]}
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        blocking = sum(f.severity in (Severity.FATAL, Severity.ERROR) for f in report.findings)
        for finding in report.findings:
            sys.stdout.write(_finding_line(finding))
        verdict = "ok" if report.ok else "invalid"
        sys.stdout.write(f"{verdict}: {blocking} fatal/error, {len(report.findings) - blocking} warning/information\n")
    return 0 if report.ok else 1


def _convert(args: argparse.Namespace) -> int:
    result = parse_detailed(_read(args.file))
    for path in result.unmapped:
        sys.stderr.write(f"warning: not converted, no business term: {path}\n")
    try:
        xml = to_xml(result.invoice, profile=args.profile, syntax=args.to)
    except PreflightError as exc:
        sys.stderr.write(
            f"error: invoice fails the {exc.profile_id} pre-flight and calculation checks for {exc.syntax}\n"
        )
        for finding in exc.findings:
            sys.stderr.write(_finding_line(finding))
        return 1
    if args.output is None:
        sys.stdout.buffer.write(xml)
        sys.stdout.buffer.flush()
    else:
        Path(args.output).write_bytes(xml)
    return 0


def _plain(value: object) -> str | None:
    """A business term's value as JSON-safe text: amounts via ``format(v, "f")`` (never exponent notation)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime.date):
        return value.isoformat()
    return str(value)


def _summary(invoice: Invoice) -> dict[str, str | None]:
    summary: dict[str, str | None] = {}
    for ident in _SUMMARY_TERMS:
        value: object = invoice
        for name in path_of(ident).split("."):
            value = getattr(value, name)
        summary[ident] = _plain(value)
    return summary


def _info(args: argparse.Namespace) -> int:
    xml, found = _xml_of(_read(args.file))
    detection = detect(xml)
    result = parse_detailed(xml)
    # For a PDF, extract() picks the profile: a Factur-X level shares its BT-24 with EN 16931 core or XRechnung.
    profile = detection.profile if found is None else found.profile
    container = (
        None
        if found is None
        else {"container": found.container, "conformance_level": found.conformance_level, "filename": found.filename}
    )
    summary = _summary(result.invoice)
    head = {
        "syntax": str(detection.syntax),
        "root": detection.root,
        "specification_identifier": detection.specification_identifier,
        "profile": profile.id if profile is not None else None,
    }
    if args.json:
        payload = {**head, "pdf": container, "invoice": summary, "unmapped": list(result.unmapped)}
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 0
    lines = [
        *(f"{key}: {value}" for key, value in head.items()),
        *(f"pdf {key}: {value}" for key, value in (container or {}).items()),
        *(f"{ident}: {term}" for ident, term in summary.items() if term is not None),
        *(f"unmapped: {path}" for path in result.unmapped),
    ]
    sys.stdout.write("".join(f"{line}\n" for line in lines))
    return 0


def _artifacts_fetch(args: argparse.Namespace) -> int:
    names = t.cast(list[artifacts.SourceName] | None, args.only)
    for name, path in artifacts.fetch(names).items():
        sys.stdout.write(f"{name}: {path}\n")
    return 0


def _profile_arg(value: str) -> profiles.Profile:
    try:
        return PROFILES[value]
    except KeyError:
        raise argparse.ArgumentTypeError(f"unknown profile {value!r}; choose from {', '.join(PROFILES)}") from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m euinvoice",
        description="EN 16931 e-invoicing toolkit (euinvoice).",
        epilog="exit codes: 0 ok, 1 document rejected (findings, refused, unreadable invoice), 2 usage or setup",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    profile_help = f"profile id (default: from BT-24): {', '.join(PROFILES)}"

    check = commands.add_parser("validate", help="validate a UBL / CII invoice or Factur-X / ZUGFeRD PDF")
    check.add_argument("file", metavar="FILE", help="the invoice; - reads stdin")
    check.add_argument("--profile", type=_profile_arg, metavar="ID", help=profile_help)
    check.add_argument("--json", action="store_true", help="print the report as JSON")
    check.set_defaults(run=_validate)

    convert = commands.add_parser("convert", help="convert an invoice to UBL or CII")
    convert.add_argument("file", metavar="FILE", help="the invoice (XML or Factur-X / ZUGFeRD PDF); - reads stdin")
    convert.add_argument("--to", required=True, choices=[str(s) for s in Syntax], help="target syntax")
    convert.add_argument("--profile", type=_profile_arg, metavar="ID", help=profile_help)
    convert.add_argument("-o", "--output", metavar="OUT", help="write here instead of stdout")
    convert.set_defaults(run=_convert)

    info = commands.add_parser("info", help="show what an invoice is: syntax, profile, number, totals")
    info.add_argument("file", metavar="FILE", help="the invoice (XML or Factur-X / ZUGFeRD PDF); - reads stdin")
    info.add_argument("--json", action="store_true", help="print as JSON")
    info.set_defaults(run=_info)

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
        The process exit code (see the module docstring). Usage errors found by argparse exit with 2 through
        ``SystemExit``.
    """
    args = _parser().parse_args(argv)
    run = t.cast(t.Callable[[argparse.Namespace], int], args.run)
    try:
        return run(args)
    except (ArtifactsNotAvailableError, OSError, ImportError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    except EuInvoiceError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
