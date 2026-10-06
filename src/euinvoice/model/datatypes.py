r"""EN 16931 semantic data types other than the numbers of :mod:`euinvoice.model.amounts`.

The data types and their properties are listed in the XRechnung 3.0.2 specification, chapter 8
("Semantische Datentypen"), which restates EN 16931-1: Text, Date, Code, Identifier (content plus
optional scheme identifier and scheme version identifier, whose cardinality is set per business
term), Document reference, Binary object (content, mime code, filename).

Which business term may or must carry a scheme, and which code list each code is checked against, is
decided where the type is used (``invoice.py``, ``parties.py``, …) with the validators built here.
Every check mirrors a ``fatal`` rule of the pinned CEN Schematron (validation-1.3.16) that holds in
both syntaxes, and each error message names that rule.

Code values are normalised when stored: upstream compares codes with XPath ``normalize-space`` (and
VATEX codes, BR-CL-22, also with ``upper-case``), so the model strips the XML whitespace
``" \t\r\n"`` (exactly what ``normalize-space`` strips, unlike :meth:`str.strip`) and upper-cases
VATEX codes, then checks membership. The stored value is the canonical code that every syntax writes;
it compares equal to the input whenever upstream treats the two as equal. MIME codes (BR-CL-24) are
compared exactly upstream, so they are neither stripped nor changed.
"""

import datetime
import re
import typing as t
from collections.abc import Callable
from decimal import Decimal

import pydantic

from euinvoice.errors import ModelError
from euinvoice.model._base import EuInvoiceModel
from euinvoice.model.codes import (
    CEF_EAS,
    ISO_3166_1_COUNTRY,
    ISO_4217_CURRENCY,
    ISO_6523_ICD,
    MIME_CODE,
    UNECE_REC20_REC21_UNIT,
    UNTDID_1001_DOCUMENT_TYPE,
    UNTDID_1153_REFERENCE_QUALIFIER,
    UNTDID_2005_VAT_POINT_DATE_UBL,
    UNTDID_4451_TEXT_SUBJECT,
    UNTDID_4461_PAYMENT_MEANS,
    UNTDID_5189_ALLOWANCE_REASON,
    UNTDID_5305_VAT_CATEGORY,
    UNTDID_7143_ITEM_CLASSIFICATION,
    UNTDID_7161_CHARGE_REASON,
    VATEX_EXEMPTION_REASON,
)

__all__ = [
    "AllowanceReasonCode",
    "BinaryObject",
    "ChargeReasonCode",
    "CountryCode",
    "CurrencyCode",
    "Date",
    "DocumentTypeCode",
    "Identifier",
    "ItemClassificationIdentifier",
    "NonBlankText",
    "PaymentMeansCode",
    "Text",
    "TextSubjectCode",
    "UnitCode",
    "VatCategoryCode",
    "VatExemptionReasonCode",
    "VatPointDateCode",
]

_XPATH_SPACE: t.Final = " \t\r\n"
"""The characters XPath ``normalize-space`` strips (#x20, #x9, #xD, #xA)."""

_NOT_XML_CHAR: t.Final = re.compile(r"[^\t\n\r\x20-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]")
"""Any character outside the XML 1.0 ``Char`` production (W3C XML 1.0 5th edition, §2.2):
``#x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD] | [#x10000-#x10FFFF]``."""


def _xml_chars(value: str) -> str:
    """Refuse text that holds a character XML 1.0 cannot carry.

    UBL and CII instances are XML 1.0 documents, so such a character (NUL and the other C0 controls
    except tab, LF and CR, a lone surrogate, U+FFFE, U+FFFF) can never be written in any syntax.

    Args:
        value: The text.

    Returns:
        ``value`` unchanged.

    Raises:
        ModelError: ``value`` holds a character outside the XML 1.0 ``Char`` production.
    """
    bad = _NOT_XML_CHAR.search(value)
    if bad is not None:
        raise ModelError(
            f"character U+{ord(bad.group()):04X} at index {bad.start()} is not allowed in XML 1.0 "
            "(W3C XML 1.0 5th edition §2.2, Char), so no syntax can carry it"
        )
    return value


Text = t.Annotated[str, pydantic.Strict(), pydantic.AfterValidator(_xml_chars)]
"""EN 16931 Text (also used for Document reference and for identifiers without a scheme).

Strict: a ``bytes`` or number is refused instead of being converted. Only characters of the XML 1.0
``Char`` production are accepted. Every model string type (codes, identifiers and their schemes,
binary object filename and mime code) builds on this type. Empty text is accepted: the CEN rules only
test non-emptiness for the mandatory terms that use :data:`NonBlankText`.
"""


def _non_blank(value: str) -> str:
    """Refuse text that ``normalize-space`` reduces to the empty string.

    Args:
        value: The text.

    Returns:
        ``value`` unchanged.

    Raises:
        ModelError: ``value`` is empty or XML whitespace only.
    """
    if not value.strip(_XPATH_SPACE):
        raise ModelError(
            "this mandatory business term must not be empty or whitespace only: the CEN rules require "
            "normalize-space(.) != '' in both UBL and CII (see the field's BR id in bt-mapping.md)"
        )
    return value


NonBlankText = t.Annotated[Text, pydantic.AfterValidator(_non_blank)]
"""Text of a mandatory term whose CEN rule tests ``normalize-space(.) != ''`` in **both** syntaxes.

Used for BT-1 (BR-02), BT-24 (BR-01), BT-27 (BR-06), BT-44 (BR-07), BT-62 (BR-18), BT-84 (BR-50),
BT-122 (BR-52), BT-126 (BR-21) and BT-153 (BR-25). Terms whose rule only tests existence in one of
the syntaxes (e.g. BT-25, BR-55 in UBL) stay plain :data:`Text`, so the model never refuses an
invoice the official Schematron accepts (D8).
"""


_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _date_input(value: object) -> object:
    """Let a ``date`` or a ``YYYY-MM-DD`` string through; refuse what lax mode would silently convert.

    Pydantic's lax date parsing also takes Unix timestamps (``"1767225600"``), zero-time datetimes
    (offsets dropped) and numbers. UBL ``xs:date`` and CII format 102 accept none of these in the model's
    form, so only the ISO calendar date is accepted (CII ``YYYYMMDD`` is converted by the CII reader).

    Args:
        value: The raw input.

    Returns:
        ``value`` unchanged, for pydantic's date parsing.

    Raises:
        ModelError: ``value`` is a ``datetime``, a number, or a string other than ``YYYY-MM-DD``.
    """
    if isinstance(value, str) and _ISO_DATE.fullmatch(value):
        return value
    if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        return value
    raise ModelError(f"expected a datetime.date or an ISO 8601 'YYYY-MM-DD' string, got {value!r}")


Date = t.Annotated[datetime.date, pydantic.BeforeValidator(_date_input)]
"""EN 16931 Date.

A ``datetime.date`` (not a ``datetime``: no silent truncation of a time) or a ``YYYY-MM-DD`` string, so a
``model_dump(mode="json")`` dict validates back. Numbers, timestamp strings, ``YYYYMMDD`` and
datetime strings are refused.
"""


def _code(codes: frozenset[str], name: str, rule: str, *, upper: bool = False) -> Callable[[str], str]:
    """Build the check of a code against its generated list.

    Args:
        codes: The accepted codes.
        name: The list's name for the error message.
        rule: The CEN rule id(s) for the error message.
        upper: Upper-case before the lookup (BR-CL-22).

    Returns:
        A validator returning the normalised code.
    """

    def check(value: str) -> str:
        normal = value.strip(_XPATH_SPACE)
        if upper:
            normal = normal.upper()
        if normal not in codes:
            raise ModelError(f"{value!r} is not in the {name} list ({rule})")
        return normal

    return check


DocumentTypeCode = t.Annotated[
    Text, pydantic.AfterValidator(_code(UNTDID_1001_DOCUMENT_TYPE, "UNTDID 1001 document type", "BR-CL-01"))
]
"""Invoice type code (BT-3): the CEN union of the UBL invoice and credit note lists (BR-CL-01)."""
CurrencyCode = t.Annotated[
    Text, pydantic.AfterValidator(_code(ISO_4217_CURRENCY, "ISO 4217 currency", "BR-CL-04/BR-CL-05"))
]
"""Currency code (BT-5, BT-6)."""
VatPointDateCode = t.Annotated[
    Text, pydantic.AfterValidator(_code(UNTDID_2005_VAT_POINT_DATE_UBL, "UNTDID 2005 VAT point date", "BR-CL-06"))
]
"""Value added tax point date code (BT-8).

The semantic model codes BT-8 with UNTDID 2005: 3, 35 and 432 (XRechnung 3.0.2 spec §11.1, BT-8), which is
the UBL list of BR-CL-06. CII writes UNTDID 2475 codes instead (CII BR-CL-06: 5, 29, 72); translating
between them belongs to the CII mapper.
"""
TextSubjectCode = t.Annotated[
    Text, pydantic.AfterValidator(_code(UNTDID_4451_TEXT_SUBJECT, "UNTDID 4451 text subject", "BR-CL-08"))
]
"""Invoice note subject code (BT-21)."""
CountryCode = t.Annotated[
    Text, pydantic.AfterValidator(_code(ISO_3166_1_COUNTRY, "ISO 3166-1 alpha-2 country", "BR-CL-14/BR-CL-15"))
]
"""Country code (BT-40, BT-55, BT-69, BT-80, BT-159): the union of the UBL and CII lists."""
PaymentMeansCode = t.Annotated[
    Text, pydantic.AfterValidator(_code(UNTDID_4461_PAYMENT_MEANS, "UNTDID 4461 payment means", "BR-CL-16"))
]
"""Payment means type code (BT-81)."""
VatCategoryCode = t.Annotated[
    Text, pydantic.AfterValidator(_code(UNTDID_5305_VAT_CATEGORY, "UNTDID 5305 VAT category", "BR-CL-17/BR-CL-18"))
]
"""VAT category code (BT-95, BT-102, BT-118, BT-151); ``VatCategory`` members are accepted as is."""
AllowanceReasonCode = t.Annotated[
    Text, pydantic.AfterValidator(_code(UNTDID_5189_ALLOWANCE_REASON, "UNTDID 5189 allowance reason", "BR-CL-19"))
]
"""Allowance reason code (BT-98, BT-140)."""
ChargeReasonCode = t.Annotated[
    Text, pydantic.AfterValidator(_code(UNTDID_7161_CHARGE_REASON, "UNTDID 7161 charge reason", "BR-CL-20"))
]
"""Charge reason code (BT-105, BT-145)."""
VatExemptionReasonCode = t.Annotated[
    Text, pydantic.AfterValidator(_code(VATEX_EXEMPTION_REASON, "CEF VATEX", "BR-CL-22", upper=True))
]
"""VAT exemption reason code (BT-121), stored upper-cased as BR-CL-22 compares it."""
UnitCode = t.Annotated[
    Text, pydantic.AfterValidator(_code(UNECE_REC20_REC21_UNIT, "UN/ECE Rec 20/21 unit", "BR-CL-23"))
]
"""Unit of measure code (BT-130, BT-150)."""


class Identifier(EuInvoiceModel):
    """EN 16931 Identifier with an optional scheme identifier.

    Used for the business terms that may carry a scheme (XRechnung 3.0.2 spec chapter 11, rows
    "<term>/Scheme identifier"): BT-18, BT-29, BT-30, BT-34, BT-46, BT-47, BT-49, BT-60, BT-61, BT-71,
    BT-128 and BT-157. Identifiers without a scheme are plain :data:`Text`. Which scheme list applies,
    and whether the scheme is mandatory, is checked on the field with :func:`scheme`.
    """

    value: Text
    """The identifier itself (content)."""
    scheme_id: Text | None = None
    """The identification scheme (e.g. an ISO 6523 ICD or CEF EAS code). Stripped of XML whitespace
    when the field checks a scheme list."""


class ItemClassificationIdentifier(EuInvoiceModel):
    """Item classification identifier (BT-158) with its mandatory scheme and optional scheme version.

    The scheme identifier is required (BR-65) and is a UNTDID 7143 code (BR-CL-13). BT-158 is the only
    business term with a "Scheme version identifier" (XRechnung 3.0.2 spec §11.20).
    """

    value: Text
    """The classification code (content)."""
    scheme_id: t.Annotated[
        Text,
        pydantic.AfterValidator(_code(UNTDID_7143_ITEM_CLASSIFICATION, "UNTDID 7143 item classification", "BR-CL-13")),
    ]
    """UNTDID 7143 list identifier (BR-65, BR-CL-13), stored stripped of XML whitespace."""
    scheme_version_id: Text | None = None
    """Version of the classification scheme."""


def scheme(codes: frozenset[str], rule: str, *, required: str | None = None) -> pydantic.AfterValidator:
    """Build the field check of an :class:`Identifier`'s scheme.

    Args:
        codes: The accepted scheme codes.
        rule: The CEN code-list rule id for the error message (e.g. ``"BR-CL-10"``).
        required: The CEN rule id that makes the scheme mandatory (e.g. ``"BR-62"``), or ``None``.

    Returns:
        The validator to put in the field's ``Annotated`` metadata. It returns the identifier with its
        scheme stripped of XML whitespace.
    """
    check = _code(codes, "scheme", rule)

    def validate(identifier: Identifier) -> Identifier:
        if identifier.scheme_id is None:
            if required is not None:
                raise ModelError(f"this identifier needs a scheme identifier ({required})")
            return identifier
        normal = check(identifier.scheme_id)
        return identifier if normal == identifier.scheme_id else identifier.model_copy(update={"scheme_id": normal})

    return pydantic.AfterValidator(validate)


ICD_SCHEME: t.Final = scheme(ISO_6523_ICD, "BR-CL-10/BR-CL-11/BR-CL-26")
"""Optional ISO 6523 ICD scheme (party, legal registration and delivery location identifiers)."""
OBJECT_SCHEME: t.Final = scheme(UNTDID_1153_REFERENCE_QUALIFIER, "BR-CL-07")
"""Optional UNTDID 1153 scheme (invoiced object identifiers BT-18, BT-128)."""
EAS_SCHEME: t.Final = scheme(CEF_EAS, "BR-CL-25", required="BR-62/BR-63")
"""Mandatory CEF EAS scheme (electronic addresses BT-34, BT-49)."""
STANDARD_ITEM_SCHEME: t.Final = scheme(ISO_6523_ICD, "BR-CL-21", required="BR-64")
"""Mandatory ISO 6523 ICD scheme (item standard identifier BT-157)."""


def _mime(value: str) -> str:
    if value not in MIME_CODE:
        raise ModelError(f"{value!r} is not an accepted MIME code (BR-CL-24)")
    return value


class BinaryObject(EuInvoiceModel):
    """EN 16931 Binary object: the attached document BT-125 with its mime code and filename.

    In JSON the content is base64 text. The content field is strict (``bytes`` only), so a dict from
    ``model_dump(mode="json")`` that holds an attachment must be reloaded from JSON text with
    ``model_validate_json``, which decodes the base64. The XRechnung 3.0.2 spec (§8.2, §11.2) gives mime code and
    filename cardinality 1, and UBL enforces both (UBL-DT-06/07, fatal), but the CEN CII rules and the
    CII XSD do not. The syntax-neutral model therefore keeps both optional, so a CEN-valid CII invoice
    always loads (D8); see "Decisions" (M3) in ``docs/reference/bt-mapping.md``.
    """

    model_config = pydantic.ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")

    content: t.Annotated[bytes, pydantic.Strict()]
    """The attached document's bytes."""
    mime_code: t.Annotated[Text, pydantic.AfterValidator(_mime)] | None = None
    """MIME type, compared exactly as BR-CL-24 does (no whitespace stripping)."""
    filename: Text | None = None
    """The attached document's file name."""


def not_negative(rule: str) -> pydantic.AfterValidator:
    """Build a check that a unit price is not negative (BR-27, BR-28).

    Args:
        rule: The CEN rule id for the error message.

    Returns:
        The validator.
    """

    def check(value: Decimal) -> Decimal:
        if value < 0:
            raise ModelError(f"must not be negative, got {format(value, 'f')} ({rule})")
        return value

    return pydantic.AfterValidator(check)


def at_least_one(rule: str) -> pydantic.AfterValidator:
    """Build the check of a ``1..n`` cardinality on a tuple field.

    Args:
        rule: The CEN rule id that makes the term mandatory, for the error message.

    Returns:
        The validator.
    """

    def check(value: tuple[t.Any, ...]) -> tuple[t.Any, ...]:
        if not value:
            raise ModelError(f"at least one entry is required ({rule})")
        return value

    return pydantic.AfterValidator(check)
