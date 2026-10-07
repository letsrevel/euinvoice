"""The FPR12 writer options: the transmission header, checked against XSD 1.2.3 and Allegato A 1.9.1 (#119)."""

import typing as t

import pydantic
import pytest

from euinvoice.errors import ModelError
from euinvoice.model.it import fatturapa_id
from euinvoice.syntax.fatturapa import RECIPIENT_FOREIGN, RECIPIENT_UNKNOWN, WriterOptions

_VALID: t.Final = {"transmitter_country": "IT", "transmitter_code": "00000000001", "progressive": "00001"}


def test_defaults_to_the_unknown_recipient() -> None:
    options = WriterOptions(**_VALID)

    assert (options.recipient_code, options.recipient_pec) == (RECIPIENT_UNKNOWN, None)
    assert RECIPIENT_UNKNOWN == "0000000"
    assert RECIPIENT_FOREIGN == "XXXXXXX"


def test_options_are_frozen() -> None:
    options = WriterOptions(**_VALID)

    with pytest.raises(pydantic.ValidationError):
        options.progressive = "2"  # type: ignore[misc] # frozen model: the assignment is the test


@pytest.mark.parametrize(
    ("field", "element"),
    [
        ("transmitter_country", "1.1.1.1"),
        ("transmitter_code", "1.1.1.2"),
        ("progressive", "1.1.2"),
        ("recipient_code", "1.1.4"),
        ("recipient_pec", "1.1.6"),
    ],
)
def test_each_option_cites_its_element(field: str, element: str) -> None:
    assert fatturapa_id(WriterOptions, field) == element


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"transmitter_country": "it"}, "IdPaese"),
        ({"transmitter_code": ""}, "IdCodice"),
        ({"transmitter_code": "0" * 29}, "IdCodice"),
        ({"progressive": "12345678901"}, "ProgressivoInvio"),
        ({"progressive": "è"}, "ProgressivoInvio"),
        ({"progressive": "a\tb"}, "ProgressivoInvio"),
        ({"recipient_code": "ABC123"}, "6 characters are FPA12 only"),
        ({"recipient_code": "abcdef1"}, "CodiceDestinatario"),
        ({"recipient_pec": "not-an-address"}, "PECDestinatario must be"),
        ({"recipient_pec": "a@" + "b" * 255}, "PECDestinatario must be"),
        ({"recipient_pec": "a@example.com", "recipient_code": "ABCDEF1"}, "only with CodiceDestinatario 0000000"),
    ],
)
def test_invalid_options_are_refused(changes: dict[str, str], match: str) -> None:
    with pytest.raises(pydantic.ValidationError, match=match) as raised:
        WriterOptions(**{**_VALID, **changes})

    assert isinstance(raised.value.errors()[0]["ctx"]["error"], ModelError)


@pytest.mark.parametrize("code", [RECIPIENT_FOREIGN, "ABCDEF1", "0000000"])
def test_recipient_codes(code: str) -> None:
    assert WriterOptions(**_VALID, recipient_code=code).recipient_code == code
