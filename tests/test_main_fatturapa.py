"""The CLI on FatturaPA (#122): ``convert --to fatturapa``, ``convert --drop-extensions`` and a lotto in ``info``."""

from pathlib import Path

import pytest

from _fatturapa_read import body, document
from _fatturapa_write import TRANSMISSION, it_invoice
from _invoices import minimal_invoice
from euinvoice import __main__ as cli
from euinvoice import parse, parse_detailed, to_xml
from euinvoice.model import extension_paths, without_extensions
from euinvoice.syntax import Syntax, ubl
from euinvoice.syntax.fatturapa import Transmission

LOTTO = document(body(number="FT-1"), body(number="FT-2"))


def _write(tmp_path: Path, data: bytes) -> str:
    path = tmp_path / "a.xml"
    path.write_bytes(data)
    return str(path)


def _fatturapa() -> bytes:
    return to_xml(it_invoice(), syntax=Syntax.FATTURAPA, fatturapa_transmission=TRANSMISSION)


HEADER = ["--transmitter", "IT00000000009", "--transmission-number", "00002"]


# --- convert --to fatturapa -----------------------------------------------------------------------------------------


def test_convert_to_fatturapa_takes_the_header_from_the_flags(
    tmp_path: Path, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    source = _fatturapa()
    argv = ["convert", "--to", "fatturapa", *HEADER, "--recipient-code", "ABC1234", _write(tmp_path, source)]

    assert cli.main(argv) == 0

    expected = Transmission(
        transmitter_country="IT",
        transmitter_code="00000000009",
        transmission_number="00002",
        recipient_code="ABC1234",
    )
    captured = capsysbinary.readouterr()
    assert captured.out == to_xml(parse(source), syntax=Syntax.FATTURAPA, fatturapa_transmission=expected)
    # The source's own transmission header is not invoice data: reported, then replaced by the flags.
    assert captured.err == b"warning: not converted, no business term: " + parse_detailed(source).unmapped[
        0
    ].encode() + (b"\n")


def test_convert_to_fatturapa_with_a_pec_address(tmp_path: Path, capsysbinary: pytest.CaptureFixture[bytes]) -> None:
    out = tmp_path / "out.xml"
    argv = ["convert", "--to", "fatturapa", *HEADER, "--pec", "fatture@example.com", "-o", str(out)]

    assert cli.main([*argv, _write(tmp_path, _fatturapa())]) == 0

    assert b"<CodiceDestinatario>0000000</CodiceDestinatario>" in out.read_bytes()
    assert b"<PECDestinatario>fatture@example.com</PECDestinatario>" in out.read_bytes()


def test_convert_to_fatturapa_refuses_an_invoice_without_italian_data(
    tmp_path: Path, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    source = _write(tmp_path, ubl.write(minimal_invoice()))

    assert cli.main(["convert", "--to", "fatturapa", *HEADER, source]) == 1

    captured = capsysbinary.readouterr()
    assert captured.out == b""
    assert captured.err.startswith(b"error: invoice fails the FatturaPA pre-flight and SdI checks\n")
    assert b"error EUINVOICE-FATTURAPA-EXTENSION [fatturapa-preflight] at it: " in captured.err


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--to", "fatturapa", "--transmission-number", "1"], "--to fatturapa needs --transmitter"),
        (["--to", "fatturapa", "--transmitter", "IT00000000009"], "--to fatturapa needs --transmission-number"),
        (["--to", "fatturapa", *HEADER, "--profile", "en16931"], "FatturaPA is written without a profile"),
        (["--to", "fatturapa", *HEADER, "--drop-extensions"], "--drop-extensions applies to --to ubl or cii"),
        (["--to", "ubl", "--transmitter", "IT00000000009"], "--transmitter applies only to --to fatturapa"),
        (["--to", "cii", "--pec", "a@example.com"], "--pec applies only to --to fatturapa"),
        (["--to", "fatturapa", *HEADER, "--recipient-code", "ABC123"], "CodiceDestinatario of an FPR12 must be 7"),
        (["--to", "fatturapa", "--transmitter", "I", "--transmission-number", "1"], "IdPaese must be two capital"),
        (
            ["--to", "fatturapa", *HEADER, "--recipient-code", "ABC1234", "--pec", "a@example.com"],
            "PECDestinatario is used only with CodiceDestinatario 0000000",
        ),
    ],
    ids=[
        "no transmitter",
        "no transmission number",
        "profile",
        "drop extensions",
        "transmitter for ubl",
        "pec for cii",
        "6-character recipient code",
        "short transmitter",
        "pec with a recipient code",
    ],
)
def test_convert_flag_misuse_is_a_usage_error(
    argv: list[str], message: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Checked before reading FILE, so the missing file is never opened.
    assert cli.main(["convert", *argv, str(tmp_path / "nope.xml")]) == 2

    err = capsys.readouterr().err
    assert err.startswith("error: ")
    assert message in err
    assert err.count("\n") == 1


# --- convert from FatturaPA -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("target", [Syntax.UBL, Syntax.CII])
def test_convert_from_fatturapa_needs_drop_extensions(
    target: Syntax, tmp_path: Path, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    assert cli.main(["convert", "--to", str(target), _write(tmp_path, document())]) == 1

    captured = capsysbinary.readouterr()
    assert captured.out == b""
    assert captured.err.endswith(
        b"error: the invoice carries national extension data (it), which has no place in "
        + target.upper().encode()
        + b"; pass --drop-extensions to convert the EN 16931 content alone\n"
    )


@pytest.mark.parametrize("target", [Syntax.UBL, Syntax.CII])
def test_convert_drop_extensions_reports_each_dropped_path(
    target: Syntax, tmp_path: Path, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    source = _fatturapa()
    read = parse_detailed(source)
    dropped = extension_paths(read.invoice)
    assert "it" in dropped

    assert cli.main(["convert", "--to", str(target), "--drop-extensions", _write(tmp_path, source)]) == 0

    captured = capsysbinary.readouterr()
    assert captured.out == to_xml(without_extensions(read.invoice), syntax=target)
    warnings = [f"warning: not converted, no business term: {path}" for path in read.unmapped]
    warnings += [f"warning: not converted, national extension dropped: {path}" for path in dropped]
    assert captured.err.decode().splitlines() == warnings


def test_drop_extensions_without_extensions_changes_nothing(
    tmp_path: Path, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    invoice = minimal_invoice()
    source = _write(tmp_path, ubl.write(invoice))

    assert cli.main(["convert", "--to", "cii", "--drop-extensions", source]) == 0

    captured = capsysbinary.readouterr()
    assert (captured.out, captured.err) == (to_xml(invoice, syntax="cii"), b"")


# --- a lotto --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [["info"], ["info", "--json"], ["convert", "--to", "ubl"], ["convert", "--to", "fatturapa", *HEADER]],
    ids=["info", "info --json", "convert", "convert --to fatturapa"],
)
def test_a_lotto_is_refused_with_a_cli_message(
    argv: list[str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main([*argv, _write(tmp_path, LOTTO)]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        f"error: the file is a FatturaPA lotto of 2 invoices (one FatturaElettronicaBody each); {argv[0]} reads a file "
        "with one invoice, and validate checks the whole lotto\n"
    )
