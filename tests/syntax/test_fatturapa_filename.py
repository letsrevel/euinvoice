"""SdI file name (00001) and size (00003) helpers, Allegato A 1.9.1 §1.2.2 and §1.3.1 (#119)."""

import pytest

from euinvoice.report import Severity
from euinvoice.syntax.fatturapa import MAX_FILE_SIZE, check_file, file_name
from euinvoice.syntax.fatturapa.filename import FILE_NAME, FILE_SIZE, SOURCE
from euinvoice.validation import sdi


@pytest.mark.parametrize(
    ("parts", "extension", "expected"),
    [
        (("IT", "01234567890", "00001"), ".xml", "IT01234567890_00001.xml"),
        (("IT", "AAABBB99T99X999W", "00001"), ".xml", "ITAAABBB99T99X999W_00001.xml"),  # Allegato A's example
        (("IT", "99999999999", "00002"), ".xml.p7m", "IT99999999999_00002.xml.p7m"),  # Allegato A's example
        (("DE", "12", "a"), ".zip", "DE12_a.zip"),
        (("FR", "1" * 28, "Zz9"), ".xml", f"FR{'1' * 28}_Zz9.xml"),
    ],
)
def test_file_name(parts: tuple[str, str, str], extension: str, expected: str) -> None:
    assert file_name(*parts, extension=extension) == expected
    assert check_file(expected, 1) == ()


@pytest.mark.parametrize(
    ("parts", "extension", "match"),
    [
        (("it", "01234567890", "1"), ".xml", "country code"),
        (("XX", "01234567890", "1"), ".xml", "country code"),
        (("IT", "0123456789", "1"), ".xml", "11 to 16"),
        (("IT", "0" * 17, "1"), ".xml", "11 to 16"),
        (("DE", "1", "1"), ".xml", "2 to 28"),
        (("DE", "1" * 29, "1"), ".xml", "2 to 28"),
        (("DE", "12_3", "1"), ".xml", "letters or digits"),
        (("IT", "01234567890", "123456"), ".xml", "file number"),
        (("IT", "01234567890", "1-2"), ".xml", "file number"),
        (("IT", "01234567890", ""), ".xml", "file number"),
        (("IT", "01234567890", "1"), ".p7m", "extension"),
        (("IT", "01234567890", "1"), ".XML", "extension"),
    ],
)
def test_file_name_refuses_invalid_parts(parts: tuple[str, str, str], extension: str, match: str) -> None:
    with pytest.raises(ValueError, match=f"SdI 00001.*{match}"):
        file_name(*parts, extension=extension)


@pytest.mark.parametrize(
    "name",
    [
        "IT0123456789_00001.xml",
        "IT01234567890-00001.xml",
        "IT01234567890_00001.xml.zip",
        "IT01234567890_00001",
        "XX12_1.xml",
        "it01234567890_1.xml",
        "IT01234567890_123456.xml",
        "dir/IT01234567890_1.xml",
    ],
)
def test_check_file_reports_00001(name: str) -> None:
    (finding,) = check_file(name, 100)

    assert (finding.rule_id, finding.severity, finding.location, finding.source) == (
        FILE_NAME,
        Severity.ERROR,
        name,
        SOURCE,
    )
    assert finding.message.startswith("SdI 00001: Nome file non valido")


def test_check_file_reports_00003_above_five_million_bytes() -> None:
    name = "IT01234567890_00001.xml"

    assert check_file(name, MAX_FILE_SIZE) == ()
    (finding,) = check_file(name, MAX_FILE_SIZE + 1)
    assert (finding.rule_id, finding.severity) == (FILE_SIZE, Severity.ERROR)
    assert "5000001 bytes" in finding.message


def test_both_findings_together() -> None:
    assert [f.rule_id for f in check_file("bad.xml", 6 * 2**20)] == [FILE_NAME, FILE_SIZE]


def test_size_reads_5mb_as_the_smaller_megabyte() -> None:
    assert MAX_FILE_SIZE == 5 * 10**6 < 5 * 2**20


def test_source_is_the_sdi_checks_one() -> None:
    assert SOURCE == sdi.SOURCE
