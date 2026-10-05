"""Hand-written enums for the few EN 16931 codes the library reasons about.

Each enum is a subset of (or equal to) its generated list in :mod:`euinvoice.model.codes._generated`;
``tests/model/test_codes.py`` checks this.
"""

import enum

__all__ = ["DocumentType", "VatCategory"]


class VatCategory(enum.StrEnum):
    """VAT category code (BT-95, BT-102, BT-118, BT-151): UNTDID 5305 as restricted by EN 16931.

    Equals :data:`UNTDID_5305_VAT_CATEGORY` (BR-CL-17 / BR-CL-18). The meanings are the names the
    CEN rules use for each code: the ``BR-<x>-01`` asserts of ``schematron/UBL/EN16931-UBL-model.sch``
    (validation-1.3.16) test ``cbc:ID = '<code>'`` and name the category in their message.
    """

    STANDARD_RATED = "S"
    """"Standard rated" (BR-S-01)."""
    ZERO_RATED = "Z"
    """"Zero rated" (BR-Z-01)."""
    EXEMPT = "E"
    """"Exempt from VAT" (BR-E-01)."""
    REVERSE_CHARGE = "AE"
    """"Reverse charge", "VAT reverse charge" (BR-AE-01)."""
    INTRA_COMMUNITY_SUPPLY = "K"
    """"Intra-community supply" (BR-IC-01)."""
    EXPORT_OUTSIDE_EU = "G"
    """"Export outside the EU" (BR-G-01)."""
    NOT_SUBJECT_TO_VAT = "O"
    """"Not subject to VAT" (BR-O-01)."""
    IGIC = "L"
    """"IGIC" (BR-AF-01)."""
    IPSI = "M"
    """"IPSI" (BR-AG-01)."""
    SPLIT_PAYMENT = "B"
    """"Split payment", domestic Italian invoices only (BR-B-01)."""


class DocumentType(enum.StrEnum):
    """Common invoice type codes (BT-3), a named subset of :data:`UNTDID_1001_DOCUMENT_TYPE`.

    BT-3 accepts every code of :data:`UNTDID_1001_DOCUMENT_TYPE`; these members only give names to the
    codes whose meaning the pinned artifacts state: XRechnung Schematron 2.6.0 rule BR-DE-17
    (``schematron/ubl/XRechnung-UBL-validation.sch``) and Peppol BIS 3.0.21 rule DE-R-017 list them
    as "326 (Partial invoice), 380 (Commercial invoice), 384 (Corrected invoice), 389 (Self-billed
    invoice) und 381 (Credit note), 875 (Partial construction invoice), 876 (Partial final
    construction invoice), 877 (Final construction invoice)".

    Which UBL root a code needs is given by :data:`UNTDID_1001_INVOICE_TYPE_UBL` and
    :data:`UNTDID_1001_CREDIT_NOTE_TYPE_UBL` (CEN BR-CL-01, UBL): of these members only
    ``CREDIT_NOTE`` is a ``CreditNote`` code.
    """

    # ponytail: only the eight codes named in the pinned artifacts. Add a member when another code
    # needs a name, citing where the artifacts (or the EC code-list publication) state its meaning.

    PARTIAL_INVOICE = "326"
    COMMERCIAL_INVOICE = "380"
    CREDIT_NOTE = "381"
    CORRECTED_INVOICE = "384"
    SELF_BILLED_INVOICE = "389"
    PARTIAL_CONSTRUCTION_INVOICE = "875"
    PARTIAL_FINAL_CONSTRUCTION_INVOICE = "876"
    FINAL_CONSTRUCTION_INVOICE = "877"
