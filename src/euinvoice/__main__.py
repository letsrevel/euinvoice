"""Command-line interface: ``python -m euinvoice`` (plan §8, M8.3).

Subcommands (each registers its handler with ``set_defaults(run=...)``):

* ``validate FILE [--profile ID] [--json]``: :func:`euinvoice.validate` on a UBL / CII / FatturaPA document or the
  invoice of a Factur-X / ZUGFeRD PDF; one line per finding, then a verdict line. FatturaPA takes no ``--profile``.
* ``convert FILE --to ubl|cii|fatturapa [--profile ID] [-o OUT]``: :func:`euinvoice.parse_all` (one invoice), then
  :func:`euinvoice.to_xml`; the XML goes to ``OUT`` or stdout. Input that has no business term in the model is not
  converted, and each such XPath is reported on stderr (readers never drop input silently, plan §1).

  * ``--to fatturapa`` writes an FPR12 FatturaPA file (no ``--profile``). Its transmission header
    (:class:`euinvoice.syntax.fatturapa.Transmission`) comes from ``--transmitter ID`` (IdTrasmittente: country code
    then tax id, e.g. ``IT01234567890``) and ``--transmission-number N`` (ProgressivoInvio), both required, and
    ``--recipient-code CODE`` (CodiceDestinatario, default ``0000000``) and ``--pec ADDRESS`` (PECDestinatario). The
    invoice needs ``Invoice.it``, so in practice the input is FatturaPA.
  * ``--to ubl|cii`` refuses an invoice with national extension data (``Invoice.it`` of a read FatturaPA, D3 as
    amended) unless ``--drop-extensions`` is given; that applies :func:`euinvoice.model.without_extensions` and
    reports each dropped model path on stderr.
* ``info FILE [--json]``: the detected syntax, root, BT-24 and profile, the Factur-X / ZUGFeRD container of a
  PDF, the invoice's BT-1, BT-2, BT-3, BT-5 and document totals (BG-22), and what was not mapped.
* ``artifacts fetch [--only NAME]``: download and verify the pinned official artifacts.

``info`` and ``convert`` read one invoice: a FatturaPA lotto (several ``FatturaElettronicaBody``) is refused (exit 1);
``validate`` checks the whole lotto.

``FILE`` ``-`` reads stdin. ``--profile`` takes a :attr:`euinvoice.profiles.Profile.id`; without it the profile
comes from BT-24 (``validate`` falls back to EN 16931 core as :func:`euinvoice.validate` documents).

Exit codes:

* ``0``: success; ``validate`` found nothing ``fatal`` / ``error`` (warnings allowed).
* ``1``: the document was rejected: ``validate`` found a ``fatal`` / ``error`` finding (``validate --profile ID``
  on a document whose syntax the profile does not support included), ``convert`` was refused by the pre-flight /
  calculation checks or, for FatturaPA, the pre-flight / SdI checks (the findings go to stderr) or because of
  national extension data without ``--drop-extensions``, the input is not a readable invoice (malformed XML,
  unsupported root or profile, a PDF without one embedded invoice, a FatturaPA lotto for ``info`` / ``convert``), or
  an artifact fails its integrity check (``ArtifactIntegrityError``: sha256 mismatch, unsafe archive member).
* ``2``: no verdict, fix the command or the setup: a usage error (argparse, an unknown ``--profile``, ``convert
  --profile ID --to SYNTAX`` with a syntax the profile does not support, a ``convert`` flag that does not apply to
  ``--to``, a missing or invalid FatturaPA transmission flag), ``FILE`` cannot be read or ``OUT`` written, an
  artifact download fails (network / HTTP), the artifacts are missing (the message names ``artifacts fetch``) or the
  profile's Schematron is not pinned, or an extra (``[pdf]``) is not installed.

Text that the terminal's encoding cannot represent (e.g. German rule messages on an ASCII stdout) is written
with backslash escapes instead of failing.

JSON output (``--json``), one object on stdout:

* ``validate``: ``{"ok": bool, "findings": [{"rule_id", "severity", "location", "message", "source"}], "kosit"}``,
  the fields of :class:`euinvoice.report.Finding` (``location`` may be ``null``). ``kosit`` is ``null``, or the
  KoSIT verdict of an XRechnung report (:class:`euinvoice.report.KositAssessment`): ``{"scenario", "accepted",
  "overrides": [...], "blocking": [...]}``, each entry ``{"rule_id", "severity", "effective_severity"}`` with
  ``severity`` the official flag; ``blocking`` lists the findings that make KoSIT reject. The text
  output prints it as one ``kosit:`` line before the verdict line. The exit code follows ``ok`` only.
* ``info``: ``{"syntax", "root", "specification_identifier", "profile", "pdf", "invoice", "unmapped"}``.
  ``profile`` is a profile id or ``null``; ``pdf`` is ``null`` for XML, else ``{"container",
  "conformance_level", "filename"}``; ``invoice`` maps the BT ids above to strings (dates ISO 8601, amounts as
  plain decimals) or ``null`` when absent; ``unmapped`` lists XPaths.

Errors are a single ``error: ...`` line on stderr in either mode.
"""

import argparse
import dataclasses
import datetime
import io
import json
import logging
import sys
import typing as t
from decimal import Decimal
from pathlib import Path

import pydantic

from euinvoice import profiles
from euinvoice._api import parse_all, to_xml
from euinvoice.detection import detect, is_pdf
from euinvoice.errors import (
    ArtifactsNotAvailableError,
    EuInvoiceError,
    ModelError,
    PreflightError,
    UnsupportedDocumentError,
)
from euinvoice.model import extension_paths, without_extensions
from euinvoice.model.bt_index import path_of
from euinvoice.model.invoice import Invoice
from euinvoice.report import Finding, KositAssessment, Severity, ValidationReport
from euinvoice.syntax import Syntax, fatturapa
from euinvoice.syntax.result import ParseResult
from euinvoice.validation import artifacts, validate

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


def _kosit_json(kosit: KositAssessment) -> dict[str, t.Any]:
    def entry(finding: Finding, effective: Severity) -> dict[str, str]:
        return {"rule_id": finding.rule_id, "severity": finding.severity, "effective_severity": effective}

    # A blocking finding's effective severity is its override if one applies, else its own (Finding is frozen and
    # hashable, so equal findings match even when a KositAssessment is built by hand).
    overridden = {o.finding: o.severity for o in kosit.overrides}
    return {
        "scenario": kosit.scenario,
        "accepted": kosit.accepted,
        "overrides": [entry(o.finding, o.severity) for o in kosit.overrides],
        "blocking": [entry(f, overridden.get(f, f.severity)) for f in kosit.blocking],
    }


def _validate(args: argparse.Namespace) -> int:
    xml, found = _xml_of(_read(args.file))
    # For a PDF, the Factur-X level in the XMP selects the profile (a level shares its BT-24 with EN 16931 core or
    # XRechnung), as in ``info``. A level whose Factur-X Schematron is not pinned (MINIMUM, BASIC WL, BASIC,
    # EXTENDED; issue #42) then makes validate() raise ArtifactsNotAvailableError (exit 2) instead of a verdict. A
    # ZUGFeRD 2.0 PDF selects no profile; validate() refuses its MINIMUM, BASIC and EXTENDED BT-24s the same way (#98).
    profile = args.profile if args.profile is not None or found is None else found.profile
    try:
        report: ValidationReport = validate(xml, profile)
    except ArtifactsNotAvailableError as exc:  # the unpinned Factur-X Schematron (#42): spell the fallback as a flag
        if exc.fallback_profile_id is None:
            raise
        raise ArtifactsNotAvailableError(
            f"{exc.reason}. To run only the EN 16931 core rules, pass --profile {exc.fallback_profile_id}"
        ) from exc
    kosit = report.kosit
    if args.json:
        payload = {
            "ok": report.ok,
            "findings": [dataclasses.asdict(f) for f in report.findings],
            "kosit": None if kosit is None else _kosit_json(kosit),
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        blocking = sum(f.severity in (Severity.FATAL, Severity.ERROR) for f in report.findings)
        for finding in report.findings:
            sys.stdout.write(_finding_line(finding))
        if kosit is not None:
            outcome = "accepted" if kosit.accepted else "rejected"
            count = len(kosit.overrides)
            overrides = f"{count} severity override{'' if count == 1 else 's'}"
            sys.stdout.write(f"kosit: {outcome} under scenario {kosit.scenario!r} ({overrides})\n")
        verdict = "ok" if report.ok else "invalid"
        sys.stdout.write(f"{verdict}: {blocking} fatal/error, {len(report.findings) - blocking} warning/information\n")
    return 0 if report.ok else 1


_TRANSMISSION_FLAGS: t.Final = (
    ("--transmitter", "transmitter"),
    ("--transmission-number", "transmission_number"),
    ("--recipient-code", "recipient_code"),
    ("--pec", "pec"),
)
"""The ``convert`` flags of the FatturaPA transmission header (:class:`euinvoice.syntax.fatturapa.Transmission`)."""

_FLAG_OF_FIELD: t.Final = {
    "transmitter_country": "--transmitter",
    "transmitter_code": "--transmitter",
    "transmission_number": "--transmission-number",
    "recipient_code": "--recipient-code",
    "recipient_pec": "--pec",
}
"""The flag that sets each :class:`~euinvoice.syntax.fatturapa.Transmission` field, to name it in a usage error."""


class _UsageError(Exception):
    """A command-line usage error that argparse cannot detect: ``main`` prints it and exits with 2."""


def _transmission(args: argparse.Namespace) -> fatturapa.Transmission:
    """The FatturaPA transmission header from the ``convert`` flags."""
    for flag, name in _TRANSMISSION_FLAGS[:2]:
        if getattr(args, name) is None:
            raise _UsageError(f"--to fatturapa needs {flag}")
    fields = {
        "transmitter_country": args.transmitter[:2],
        "transmitter_code": args.transmitter[2:],
        "transmission_number": args.transmission_number,
        "recipient_pec": args.pec,
    }
    if args.recipient_code is not None:
        fields["recipient_code"] = args.recipient_code
    try:
        return fatturapa.Transmission(**fields)
    except pydantic.ValidationError as exc:
        # The model raises ModelError (a ValueError) with the XSD / Allegato A rule; pydantic keeps it in ``ctx``. The
        # only model-level check (empty ``loc``) is PECDestinatario against CodiceDestinatario.
        raise _UsageError(
            "; ".join(
                f"{_FLAG_OF_FIELD[str(e['loc'][0]) if e['loc'] else 'recipient_pec']}: "
                f"{e.get('ctx', {}).get('error', e['msg'])}"
                for e in exc.errors()
            )
        ) from None


def _convert_flags(args: argparse.Namespace, target: Syntax) -> fatturapa.Transmission | None:
    """Check the ``convert`` flags against ``--to`` before FILE is read; the FatturaPA header for ``fatturapa``."""
    if target is Syntax.FATTURAPA:
        if args.profile is not None:
            raise _UsageError("FatturaPA is written without a profile (it has no BT-24); omit --profile")
        if args.drop_extensions:
            raise _UsageError("--drop-extensions applies to --to ubl or cii; FatturaPA keeps Invoice.it")
        return _transmission(args)
    if given := [flag for flag, name in _TRANSMISSION_FLAGS if getattr(args, name) is not None]:
        raise _UsageError(f"{given[0]} applies only to --to fatturapa")
    if args.profile is not None and target not in args.profile.syntaxes:
        supported = ", ".join(sorted(args.profile.syntaxes))
        raise _UsageError(f"profile {args.profile.id!r} does not support --to {args.to}; it supports {supported}")
    return None


def _drop_extensions(invoice: Invoice, target: Syntax, drop: bool) -> Invoice:
    """``invoice`` without national extension data for UBL / CII (each dropped path on stderr), or refused."""
    dropped = extension_paths(invoice)
    if target is Syntax.FATTURAPA or not dropped:
        return invoice
    if not drop:
        raise ModelError(
            f"the invoice carries national extension data ({', '.join(dropped)}), which has no place in "
            f"{target.upper()}; pass --drop-extensions to convert the EN 16931 content alone"
        )
    for path in dropped:
        sys.stderr.write(f"warning: not converted, national extension dropped: {path}\n")
    return without_extensions(invoice)


def _convert(args: argparse.Namespace) -> int:
    target = Syntax(args.to)
    transmission = _convert_flags(args, target)
    result = _one_invoice(parse_all(_read(args.file)), "convert")
    for path in result.unmapped:
        sys.stderr.write(f"warning: not converted, no business term: {path}\n")
    invoice = _drop_extensions(result.invoice, target, args.drop_extensions)
    try:
        xml = to_xml(invoice, profile=args.profile, syntax=target, fatturapa_transmission=transmission)
    except PreflightError as exc:
        checks = (
            "FatturaPA pre-flight and SdI checks"
            if target is Syntax.FATTURAPA
            else f"{exc.profile_id} pre-flight and calculation checks for {exc.syntax}"
        )
        sys.stderr.write(f"error: invoice fails the {checks}\n")
        for finding in exc.findings:
            sys.stderr.write(_finding_line(finding))
        return 1
    if args.output is None:
        sys.stdout.buffer.write(xml)
        sys.stdout.buffer.flush()
    else:
        # Written only after to_xml succeeded, so a refusal never touches OUT.
        # ponytail: a write error midway (e.g. disk full) can leave OUT truncated; the upgrade path is a temp file in
        # the same directory + os.replace that keeps OUT's mode and does not replace a symlink.
        Path(args.output).write_bytes(xml)
    return 0


def _one_invoice(results: tuple[ParseResult, ...], command: str) -> ParseResult:
    """The only invoice of a file; a FatturaPA lotto (several bodies) is refused with a CLI message."""
    if len(results) != 1:
        raise UnsupportedDocumentError(
            f"the file is a FatturaPA lotto of {len(results)} invoices (one FatturaElettronicaBody each); {command} "
            "reads a file with one invoice, and validate checks the whole lotto"
        )
    return results[0]


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
    result = _one_invoice(parse_all(xml), "info")
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


_EPILOG: t.Final = "exit codes: 0 ok, 1 document rejected (findings, refused, unreadable invoice), 2 usage or setup"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m euinvoice",
        description="EN 16931 e-invoicing toolkit (euinvoice).",
        epilog=_EPILOG,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    profile_help = f"profile id (default: from BT-24): {', '.join(PROFILES)}"

    check = commands.add_parser(
        "validate", help="validate a UBL / CII / FatturaPA invoice or Factur-X / ZUGFeRD PDF", epilog=_EPILOG
    )
    check.add_argument("file", metavar="FILE", help="the invoice; - reads stdin")
    check.add_argument("--profile", type=_profile_arg, metavar="ID", help=profile_help)
    check.add_argument("--json", action="store_true", help="print the report as JSON")
    check.set_defaults(run=_validate)

    convert = commands.add_parser("convert", help="convert an invoice to UBL, CII or FatturaPA", epilog=_EPILOG)
    convert.add_argument("file", metavar="FILE", help="the invoice (XML or Factur-X / ZUGFeRD PDF); - reads stdin")
    convert.add_argument("--to", required=True, choices=[str(s) for s in Syntax], help="target syntax")
    convert.add_argument("--profile", type=_profile_arg, metavar="ID", help=f"{profile_help}; not with fatturapa")
    convert.add_argument("-o", "--output", metavar="OUT", help="write here instead of stdout")
    convert.add_argument(
        "--drop-extensions",
        action="store_true",
        help="--to ubl|cii: drop national extension data (FatturaPA's Invoice.it), each dropped path on stderr",
    )
    header = convert.add_argument_group("FatturaPA transmission header (--to fatturapa)")
    header.add_argument(
        "--transmitter",
        metavar="ID",
        help="IdTrasmittente: country code and tax id of the transmitter, e.g. IT01234567890 (required)",
    )
    header.add_argument("--transmission-number", metavar="N", help="ProgressivoInvio, 1-10 characters (required)")
    header.add_argument(
        "--recipient-code",
        metavar="CODE",
        help=f"CodiceDestinatario, 7 characters (default {fatturapa.RECIPIENT_UNKNOWN}; "
        f"{fatturapa.RECIPIENT_FOREIGN} for a buyer outside Italy)",
    )
    header.add_argument(
        "--pec", metavar="ADDRESS", help=f"PECDestinatario, with CodiceDestinatario {fatturapa.RECIPIENT_UNKNOWN}"
    )
    convert.set_defaults(run=_convert)

    info = commands.add_parser("info", help="show what an invoice is: syntax, profile, number, totals", epilog=_EPILOG)
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
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="backslashreplace")
    args = _parser().parse_args(argv)
    run = t.cast(t.Callable[[argparse.Namespace], int], args.run)
    # pypdf logs recoverable damage (e.g. "EOF marker not found") as warnings; the CLI reports a PdfError as one
    # ``error:`` line instead, so the pypdf logger is quieted for the run and restored afterwards.
    pypdf_logger = logging.getLogger("pypdf")
    level = pypdf_logger.level
    pypdf_logger.setLevel(logging.ERROR)
    try:
        return run(args)
    except (_UsageError, ArtifactsNotAvailableError, OSError, ImportError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    except EuInvoiceError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    finally:
        pypdf_logger.setLevel(level)


if __name__ == "__main__":
    sys.exit(main())
