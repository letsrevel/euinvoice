"""UBL parties: Seller BG-4, Buyer BG-7, Payee BG-10, Seller tax representative BG-11, Delivery BG-13.

Element order follows ``PartyType``, ``AddressType``, ``ContactType``, ``PartyTaxSchemeType``,
``PartyLegalEntityType``, ``DeliveryType`` and ``LocationType`` of the UBL 2.1 XSD
(``common/UBL-CommonAggregateComponents-2.1.xsd``). XPaths are those of ``docs/reference/bt-mapping.md``.
"""

import typing as t

from lxml import etree

from euinvoice.model import (
    Buyer,
    BuyerContact,
    BuyerPostalAddress,
    DeliverToAddress,
    Invoice,
    Payee,
    Seller,
    SellerContact,
    SellerPostalAddress,
    SellerTaxRepresentative,
    TaxRepresentativePostalAddress,
)
from euinvoice.syntax.ubl._build import VAT_SCHEME, aggregate, basic, date, identifier

__all__ = ["SEPA_SCHEME", "TAX_REGISTRATION_SCHEME", "write_delivery", "write_parties"]

SEPA_SCHEME: t.Final = "SEPA"
"""``schemeID`` of the bank assigned creditor identifier BT-90 in ``cac:PartyIdentification`` of the Seller
or the Payee (CEN UBL BR-CO-26 and UBL-SR-29, ``UBL/EN16931-UBL-{model,syntax}.sch``; Peppol upstream
structure docs, peppol-bis-invoice-3 commit 806866b, not a pinned artifact:
``structure/syntax/part/payee-party.xml``: "For bank assigned creditor identifier (BT-90), value MUST be
'SEPA'")."""

TAX_REGISTRATION_SCHEME: t.Final = "FC"
"""``cac:TaxScheme/cbc:ID`` of the Seller tax registration identifier BT-32.

The CEN binding only requires a value other than ``VAT`` (UBL-SR-13 counts
``PartyTaxScheme[cac:TaxScheme/upper-case(cbc:ID)!='VAT']``; Peppol upstream structure docs (commit
806866b) ``part/supplier-party.xml``: "for the
seller tax registration identifier (BT-32), use != 'VAT'"). ``FC`` is what the XRechnung test suite uses
(e.g. ``instances/technical-cases/cius/01.03_comprehensive_test_ubl.xml``) and matches the CII
``schemeID='FC'`` of BT-32."""

type _Address = SellerPostalAddress | BuyerPostalAddress | TaxRepresentativePostalAddress | DeliverToAddress
type _Contact = SellerContact | BuyerContact


def write_parties(root: etree._Element, invoice: Invoice) -> None:
    """Append the Seller, Buyer, Payee and Seller tax representative, in XSD order.

    The bank assigned creditor identifier BT-90 goes under the Payee when there is one, else under the
    Seller: both are bound to BT-90 (bt-mapping.md BT-90, KoSIT XRechnung BR-DE-30), and the creditor
    is whoever receives the payment.

    Args:
        root: The ``Invoice`` or ``CreditNote`` element.
        invoice: The invoice.
    """
    direct_debit = invoice.payment_instructions.direct_debit if invoice.payment_instructions else None
    creditor_id = direct_debit.bank_assigned_creditor_identifier if direct_debit else None
    _seller(
        aggregate(aggregate(root, "AccountingSupplierParty"), "Party"),
        invoice.seller,
        None if invoice.payee else creditor_id,
    )
    _buyer(aggregate(aggregate(root, "AccountingCustomerParty"), "Party"), invoice.buyer)
    if invoice.payee is not None:
        _payee(aggregate(root, "PayeeParty"), invoice.payee, creditor_id)
    if invoice.seller_tax_representative is not None:
        _tax_representative(aggregate(root, "TaxRepresentativeParty"), invoice.seller_tax_representative)


def write_delivery(root: etree._Element, invoice: Invoice) -> None:
    """Append ``cac:Delivery`` (BG-13) when it carries anything besides the invoicing period.

    The invoicing period BG-14 sits under BG-13 in the model but is written at document level
    (``cac:InvoicePeriod``) by the header writer.

    Args:
        root: The ``Invoice`` or ``CreditNote`` element.
        invoice: The invoice.
    """
    delivery = invoice.delivery
    if delivery is None or not (
        delivery.deliver_to_party_name is not None
        or delivery.deliver_to_location_identifier is not None
        or delivery.actual_delivery_date is not None
        or delivery.deliver_to_address is not None
    ):
        return
    element = aggregate(root, "Delivery")
    basic(element, "ActualDeliveryDate", date(delivery.actual_delivery_date))
    if delivery.deliver_to_location_identifier is not None or delivery.deliver_to_address is not None:
        location = aggregate(element, "DeliveryLocation")
        identifier(location, "ID", delivery.deliver_to_location_identifier)
        _address(location, "Address", delivery.deliver_to_address)
    if delivery.deliver_to_party_name is not None:
        _party_name(aggregate(element, "DeliveryParty"), delivery.deliver_to_party_name)


def _seller(party: etree._Element, seller: Seller, creditor_id: str | None) -> None:
    identifier(party, "EndpointID", seller.electronic_address)
    for seller_id in seller.identifiers:
        identifier(aggregate(party, "PartyIdentification"), "ID", seller_id)
    _creditor_id(party, creditor_id)
    _party_name(party, seller.trading_name)
    _address(party, "PostalAddress", seller.postal_address)
    _party_tax_scheme(party, seller.vat_identifier, VAT_SCHEME)
    _party_tax_scheme(party, seller.tax_registration_identifier, TAX_REGISTRATION_SCHEME)
    legal = aggregate(party, "PartyLegalEntity")
    basic(legal, "RegistrationName", seller.name)
    identifier(legal, "CompanyID", seller.legal_registration_identifier)
    basic(legal, "CompanyLegalForm", seller.additional_legal_information)
    _contact(party, seller.contact)


def _buyer(party: etree._Element, buyer: Buyer) -> None:
    identifier(party, "EndpointID", buyer.electronic_address)
    if buyer.identifier is not None:
        identifier(aggregate(party, "PartyIdentification"), "ID", buyer.identifier)
    _party_name(party, buyer.trading_name)
    _address(party, "PostalAddress", buyer.postal_address)
    _party_tax_scheme(party, buyer.vat_identifier, VAT_SCHEME)
    legal = aggregate(party, "PartyLegalEntity")
    basic(legal, "RegistrationName", buyer.name)
    identifier(legal, "CompanyID", buyer.legal_registration_identifier)
    _contact(party, buyer.contact)


def _payee(party: etree._Element, payee: Payee, creditor_id: str | None) -> None:
    if payee.identifier is not None:
        identifier(aggregate(party, "PartyIdentification"), "ID", payee.identifier)
    _creditor_id(party, creditor_id)
    _party_name(party, payee.name)
    if payee.legal_registration_identifier is not None:
        identifier(aggregate(party, "PartyLegalEntity"), "CompanyID", payee.legal_registration_identifier)


def _tax_representative(party: etree._Element, representative: SellerTaxRepresentative) -> None:
    _party_name(party, representative.name)
    _address(party, "PostalAddress", representative.postal_address)
    _party_tax_scheme(party, representative.vat_identifier, VAT_SCHEME)


def _creditor_id(party: etree._Element, creditor_id: str | None) -> None:
    if creditor_id is not None:
        basic(aggregate(party, "PartyIdentification"), "ID", creditor_id, schemeID=SEPA_SCHEME)


def _party_name(party: etree._Element, name: str | None) -> None:
    if name is not None:
        basic(aggregate(party, "PartyName"), "Name", name)


def _party_tax_scheme(party: etree._Element, company_id: str | None, scheme: str) -> None:
    if company_id is not None:
        tax_scheme = aggregate(party, "PartyTaxScheme")
        basic(tax_scheme, "CompanyID", company_id)
        basic(aggregate(tax_scheme, "TaxScheme"), "ID", scheme)


def _address(parent: etree._Element, name: str, address: _Address | None) -> None:
    if address is None:
        return
    element = aggregate(parent, name)
    basic(element, "StreetName", address.address_line_1)
    basic(element, "AdditionalStreetName", address.address_line_2)
    basic(element, "CityName", address.city)
    basic(element, "PostalZone", address.post_code)
    basic(element, "CountrySubentity", address.country_subdivision)
    if address.address_line_3 is not None:
        basic(aggregate(element, "AddressLine"), "Line", address.address_line_3)
    basic(aggregate(element, "Country"), "IdentificationCode", address.country_code)


def _contact(party: etree._Element, contact: _Contact | None) -> None:
    if contact is not None:
        element = aggregate(party, "Contact")
        basic(element, "Name", contact.contact_point)
        basic(element, "Telephone", contact.telephone)
        basic(element, "ElectronicMail", contact.email)
