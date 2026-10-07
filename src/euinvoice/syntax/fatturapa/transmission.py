"""The FPR12 transmission header (1.1 ``<DatiTrasmissione>``), which is not invoice data (#118, #119).

Plan M11.3 keeps IdTrasmittente, ProgressivoInvio, CodiceDestinatario and PECDestinatario out of the model: they
describe one transmission to the Sistema di Interscambio (SdI), not the invoice. App. 4.1 of the SdI "Regole
tecniche fatture europee" v2.6 has the mapper generate ProgressivoInvio (row 1.1.2) and, for UBL/CII input, takes
IdTrasmittente from the seller and CodiceDestinatario from BT-49 (rows 1.1.1, 1.1.4); here the caller states them.
Each field is checked against its type in the pinned FatturaPA XSD 1.2.3 (``Schema_VFPR12_v1.2.3.xsd``) and, where
Allegato A 1.9.1 ("Specifiche tecniche", §2.1.1, DatiTrasmissione) says more, against that.
"""

import re
import typing as t

import pydantic

from euinvoice.errors import ModelError
from euinvoice.model._base import EuInvoiceModel
from euinvoice.model.datatypes import Text
from euinvoice.model.it.extension import fatturapa

__all__ = ["RECIPIENT_FOREIGN", "RECIPIENT_UNKNOWN", "Transmission"]

RECIPIENT_UNKNOWN: t.Final = "0000000"
"""``CodiceDestinatario`` when the recipient's channel is unknown or is the PEC address in ``PECDestinatario``
(Allegato A 1.9.1, §2.1.1, CodiceDestinatario)."""
RECIPIENT_FOREIGN: t.Final = "XXXXXXX"
"""``CodiceDestinatario`` of an invoice to a party not established in Italy, sent to report its data (Allegato A
1.9.1, §2.1.1; SdI check 00313 requires the cessionario's IdPaese to differ from ``IT``)."""

_COUNTRY = re.compile(r"[A-Z]{2}")  # NazioneType
_CODE = re.compile(r".{1,28}", re.DOTALL)  # CodiceType: xs:string, minLength 1, maxLength 28
_NUMBER = re.compile(r"[\x00-\x7f]{1,10}")  # String10Type: xs:normalizedString, (\p{IsBasicLatin}{1,10})
_RECIPIENT = re.compile(r"[A-Z0-9]{7}")  # CodiceDestinatarioType [A-Z0-9]{6,7}; 6 is FPA12 only (SdI 00427)
# EmailType (xs:token, maxLength 256) allows a dot-atom or a quoted local part and a dot-atom or a domain literal.
# Only its dot-atom@dot-atom alternative is accepted here, a subset of the XSD pattern: an address this accepts is
# valid against it.
_ATOM = r"[!#-'*+/-9=?A-Z^-~-]+"
_PEC = re.compile(rf"{_ATOM}(?:\.{_ATOM})*@{_ATOM}(?:\.{_ATOM})*")
_PEC_MAX = 256


def _match(pattern: re.Pattern[str], what: str) -> t.Callable[[str], str]:
    def check(value: str) -> str:
        if not pattern.fullmatch(value) or any(c in value for c in "\t\n\r"):
            raise ModelError(f"{what}; got {value!r}")
        return value

    return check


class Transmission(EuInvoiceModel):
    """The transmission header of an FPR12 file: who sends it and to which SdI channel.

    ``FormatoTrasmissione`` (1.1.3) is always ``FPR12`` and is not a field.
    """

    transmitter_country: t.Annotated[
        Text,
        pydantic.AfterValidator(_match(_COUNTRY, "IdPaese must be two capital letters (NazioneType)")),
        fatturapa("1.1.1.1"),
    ]
    """``IdTrasmittente/IdPaese``: the country code of the transmitter's tax identifier, e.g. ``IT``."""
    transmitter_code: t.Annotated[
        Text,
        pydantic.AfterValidator(_match(_CODE, "IdCodice must be 1 to 28 characters (CodiceType)")),
        fatturapa("1.1.1.2"),
    ]
    """``IdTrasmittente/IdCodice``: the transmitter's tax identifier (for Italy the codice fiscale)."""
    transmission_number: t.Annotated[
        Text,
        pydantic.AfterValidator(
            _match(
                _NUMBER,
                "ProgressivoInvio must be 1 to 10 Basic Latin characters, no tab or line break (String10Type)",
            )
        ),
        fatturapa("1.1.2"),
    ]
    """``ProgressivoInvio``: the transmitter's own identifier of this transmission (Allegato A: "progressivo che il
    soggetto trasmittente attribuisce al file"). Not the 1-5 character ``file_number`` of the SdI file name
    (:func:`~euinvoice.syntax.fatturapa.file_name`), which follows other rules."""
    recipient_code: t.Annotated[
        Text,
        pydantic.AfterValidator(
            _match(
                _RECIPIENT,
                "CodiceDestinatario of an FPR12 must be 7 capital letters or digits "
                "(CodiceDestinatarioType; 6 characters are FPA12 only, SdI 00427)",
            )
        ),
        fatturapa("1.1.4"),
    ] = RECIPIENT_UNKNOWN
    """``CodiceDestinatario``: the recipient's SdI channel code, :data:`RECIPIENT_UNKNOWN` (the default) or
    :data:`RECIPIENT_FOREIGN`."""
    recipient_pec: t.Annotated[Text | None, fatturapa("1.1.6")] = None
    """``PECDestinatario``: the recipient's certified e-mail address. Allegato A uses it only with
    ``CodiceDestinatario`` :data:`RECIPIENT_UNKNOWN`, so it is refused with any other code."""

    @pydantic.field_validator("recipient_pec")
    @classmethod
    def _pec(cls, value: str | None) -> str | None:
        if value is not None and (len(value) > _PEC_MAX or not _PEC.fullmatch(value)):
            raise ModelError(
                f"PECDestinatario must be an address of the form local@domain of at most {_PEC_MAX} characters "
                f"(EmailType); got {value!r}"
            )
        return value

    @pydantic.model_validator(mode="after")
    def _pec_needs_unknown_recipient(self) -> t.Self:
        # Allegato A 1.9.1, §2.1.1: PECDestinatario is where SdI delivers "nei casi in cui il valore di
        # CodiceDestinatario sia uguale a '0000000'"; with any other code it would be ignored.
        if self.recipient_pec is not None and self.recipient_code != RECIPIENT_UNKNOWN:
            raise ModelError(
                f"PECDestinatario is used only with CodiceDestinatario {RECIPIENT_UNKNOWN} (Allegato A 1.9.1, "
                f"§2.1.1); got CodiceDestinatario {self.recipient_code!r}"
            )
        return self
