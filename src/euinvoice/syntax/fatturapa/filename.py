"""SdI file name and size: the checks on the transmitted file that ``validate()`` cannot make (#119, D8).

``validate()`` receives XML bytes, not the file SdI receives, so it reports neither 00001 (file name) nor 00003
(file size); see ``euinvoice.validation.sdi``. These pure helpers do, for the file a sender transmits.

File name, Allegato A 1.9.1 ("Specifiche tecniche"), §1.2.2 "Nomenclatura dei file da trasmettere": country code
(ISO 3166-1 alpha-2), the "identificativo univoco" (a tax identifier of 11 to 16 characters for ``IT``, 2 to 28
otherwise), an underscore, a "progressivo univoco del file" of at most 5 characters from ``[a-z]``, ``[A-Z]``,
``[0-9]``, and the extension ``.xml`` (unsigned or XAdES), ``.xml.p7m`` (CAdES) or ``.zip`` (an archive of such
files). Example: ``IT99999999999_00002.xml.p7m``. Allegato A names no character set for the identifier; it is read
here as letters and digits, the characters of an Italian codice fiscale or partita IVA, so that the underscore stays
the only separator. 00002 (a name SdI received before) needs SdI's state and is not checked.

Size: Allegato A §1.3.1 "Il singolo file fattura non può superare la dimensione di 5MB". It does not say whether a
megabyte is 10^6 or 2^20 bytes (#130, item 9). :data:`MAX_FILE_SIZE` takes the smaller, 5 000 000 bytes, so a file
this accepts is within the limit on either reading.
"""

import re
import typing as t

from euinvoice.model.codes import ISO_3166_1_COUNTRY
from euinvoice.report import Finding, Severity

__all__ = ["EXTENSIONS", "FILE_NAME", "FILE_SIZE", "MAX_FILE_SIZE", "SOURCE", "check_file", "file_name"]

SOURCE: t.Final = "sdi"
"""``source`` of the findings, the one of the SdI checks of ``validate()`` (``euinvoice.validation.sdi.SOURCE``;
``syntax`` may not import ``validation``, plan §4)."""

MAX_FILE_SIZE: t.Final = 5_000_000
"""The largest file accepted, in bytes: "5MB" read as 5 x 10^6 (see the module docstring)."""
EXTENSIONS: t.Final = (".xml", ".xml.p7m", ".zip")
"""The extensions of Allegato A 1.9.1 §1.2.2."""
FILE_NAME: t.Final = "00001"
"""SdI error code "Nome file non valido" (Allegato A 1.9.1, Appendix 1)."""
FILE_SIZE: t.Final = "00003"
"""SdI error code "Le dimensioni del file superano quelle ammesse" (Allegato A 1.9.1, Appendix 1)."""

_ITALY: t.Final = "IT"
_NAME: t.Final = re.compile(r"([A-Z]{2})([A-Za-z0-9]+)_([A-Za-z0-9]{1,5})(\.xml|\.xml\.p7m|\.zip)")


def _problem(country: str, identifier: str, file_number: str, extension: str) -> str | None:
    """What makes the parts of a file name invalid, or ``None``."""
    if country not in ISO_3166_1_COUNTRY or not re.fullmatch(r"[A-Z]{2}", country):
        return f"the country code {country!r} is not ISO 3166-1 alpha-2"
    low, high = (11, 16) if country == _ITALY else (2, 28)
    if not low <= len(identifier) <= high or not re.fullmatch(r"[A-Za-z0-9]+", identifier):
        return f"the identifier {identifier!r} is not {low} to {high} letters or digits for country {country}"
    if not re.fullmatch(r"[A-Za-z0-9]{1,5}", file_number):
        return f"the file number {file_number!r} is not 1 to 5 letters or digits"
    if extension not in EXTENSIONS:
        return f"the extension {extension!r} is not one of {', '.join(EXTENSIONS)}"
    return None


def file_name(country: str, identifier: str, file_number: str, *, extension: str = ".xml") -> str:
    """Build an SdI file name (Allegato A 1.9.1 §1.2.2), e.g. ``IT01234567890_00001.xml``.

    The name must also differ from every name sent to SdI before (00002), which only the sender can ensure.

    Args:
        country: The ISO 3166-1 alpha-2 code of the identifier, e.g. ``"IT"``.
        identifier: The tax identifier of the transmitter or another subject (11 to 16 characters for ``IT``, 2 to
            28 otherwise; letters and digits).
        file_number: The "progressivo univoco del file", 1 to 5 letters or digits. Not ``Transmission``'s
            ``transmission_number`` (1.1.2 ProgressivoInvio), which follows other rules.
        extension: One of :data:`EXTENSIONS`: ``.xml``, ``.xml.p7m`` or ``.zip``.

    Returns:
        The file name.

    Raises:
        ValueError: A part does not follow §1.2.2; the message says which.
    """
    if problem := _problem(country, identifier, file_number, extension):
        raise ValueError(f"invalid SdI file name (Allegato A 1.9.1 §1.2.2, SdI {FILE_NAME}): {problem}")
    return f"{country}{identifier}_{file_number}{extension}"


def check_file(name: str, size: int) -> tuple[Finding, ...]:
    """Check a file about to be sent to SdI: its name (SdI 00001) and size (SdI 00003).

    Args:
        name: The file name, without a directory.
        size: The size of the transmitted file in bytes (the signed ``.xml.p7m`` or the ``.zip`` when that is what
            is sent).

    Returns:
        An ``error`` finding per failed check, with the SdI code as ``rule_id``, the file name as location and
        source ``"sdi"``; empty when both pass.
    """
    findings: list[Finding] = []
    match = _NAME.fullmatch(name)
    problem = (
        "it does not have the form <country><identifier>_<file number><extension>"
        if match is None
        else (_problem(*match.groups()))
    )
    if problem is not None:
        findings.append(_finding(FILE_NAME, name, f"Nome file non valido (Allegato A 1.9.1 §1.2.2): {problem}."))
    if size > MAX_FILE_SIZE:
        findings.append(
            _finding(
                FILE_SIZE,
                name,
                "Le dimensioni del file superano quelle ammesse (Allegato A 1.9.1 §1.3.1: 5MB, read as "
                f"{MAX_FILE_SIZE} bytes): {size} bytes.",
            )
        )
    return tuple(findings)


def _finding(code: str, name: str, detail: str) -> Finding:
    return Finding(rule_id=code, severity=Severity.ERROR, location=name, message=f"SdI {code}: {detail}", source=SOURCE)
