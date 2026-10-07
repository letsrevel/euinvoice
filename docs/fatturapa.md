# FatturaPA (Italy)

FatturaPA is the XML format of the Italian Sistema di Interscambio (SdI). It is not an EN 16931 syntax: many of its
elements have no business term (App. 4.1 marks them `EXT`, e.g. RegimeFiscale, TipoDocumento, DatiRitenuta), and others
map onto one only in part (Natura, EsigibilitaIVA). euinvoice maps the rest to the semantic model per App. 4.1 and the
App. 5 code tables of the SdI "Regole tecniche fatture europee" v2.6, and keeps the Italian data in an optional
extension, `Invoice.it` ([ADR 0001](adr/0001-fatturapa-d3-d8.md)).

## Scope

| | FPR12 (to private parties) | FPA12 (to public administrations) |
|---|---|---|
| Write | TipoDocumento TD01, TD04, TD24 and TD17; one invoice (`FatturaElettronicaBody`) per file; unsigned | no |
| Read | 1..n bodies, into `Invoice` with `Invoice.it` | same |
| Validate | XSD 1.2.3 + the offline SdI checks | same, after an `information` finding |

Everything the reader cannot map is listed in `ParseResult.unmapped`, and everything the writer cannot write is an
`error` finding. Neither drops data silently. Writing a lotto (several bodies in one file), writing FPA12 and
signing are deferred.

## 1. Build an invoice

An Italian invoice is an ordinary `Invoice` plus `Invoice.it`
([`ItalianExtension`](reference/api.md#euinvoice.model.it.ItalianExtension)), which holds RegimeFiscale and
TipoDocumento, both required. `InvoiceLine.it`
([`ItalianLineExtension`](reference/api.md#euinvoice.model.it.ItalianLineExtension)) holds the Natura of a line
that carries no VAT. Each field cites its FatturaPA element id. Here, a ticket at 22 % and an exempt service
(Natura N4, VAT category E per App. 5.1), sold to a consumer known by codice fiscale:

```python
>>> import datetime
>>> from decimal import Decimal
>>> from euinvoice import calc
>>> from euinvoice.model import (
...     Buyer, BuyerPostalAddress, Identifier, InvoiceDraft, ItemInformation, LineDraft, LineVatInformation,
...     PriceDetails, ProcessControl, Seller, SellerPostalAddress,
... )
>>> from euinvoice.model.it import ItalianExtension, ItalianLineExtension, Natura, RegimeFiscale, TipoDocumento
>>> def line(identifier, name, price, category, rate, nature=None):
...     return LineDraft(
...         identifier=identifier,
...         invoiced_quantity=Decimal("1"),
...         invoiced_quantity_unit_code="C62",
...         price_details=PriceDetails(item_net_price=Decimal(price)),
...         vat_information=LineVatInformation(category_code=category, rate=Decimal(rate)),
...         item=ItemInformation(name=name),
...         it=None if nature is None else ItalianLineExtension(nature=nature),
...     )
>>> draft = InvoiceDraft(
...     number="FT-2026-1",
...     issue_date=datetime.date(2026, 1, 15),
...     type_code="380",
...     currency_code="EUR",
...     process_control=ProcessControl(specification_identifier="urn:cen.eu:en16931:2017"),
...     seller=Seller(
...         name="Esempio Eventi S.r.l.",
...         vat_identifier="IT00000000001",
...         postal_address=SellerPostalAddress(
...             address_line_1="Via Esempio 1", city="Roma", post_code="00100", country_subdivision="RM",
...             country_code="IT",
...         ),
...     ),
...     buyer=Buyer(
...         name="Mario Rossi",
...         legal_registration_identifier=Identifier(value="AAAAAA00A00A000A", scheme_id="0210"),
...         postal_address=BuyerPostalAddress(
...             address_line_1="Via Prova 2", city="Milano", post_code="20100", country_code="IT"
...         ),
...     ),
...     lines=(
...         line("1", "Biglietto evento", "50", "S", "22"),
...         line("2", "Visita guidata", "20", "E", "0", nature=Natura.N4),
...     ),
...     it=ItalianExtension(tax_regime=RegimeFiscale.RF01, document_type=TipoDocumento.TD01),
... )
>>> invoice = calc.complete(draft, exemption_reasons={"E": calc.ExemptionReason(code="VATEX-EU-132")})
>>> invoice.totals.amount_due
Decimal('81.00')
```

The VAT summaries (`DatiRiepilogo`) are derived from the lines. Set `Invoice.it.vat_summaries` only where the business
terms do not determine a summary: an EsigibilitaIVA that BT-8 and the VAT category do not give (App. 4.1 row 2.2.2.7:
BT-8 3 or 35 gives I, 432 gives D, category B gives S), or a RiferimentoNormativo the writer cannot take from BT-120
(row 2.2.2.8), because the VAT breakdown has several DatiRiepilogo. Set `Invoice.it.payment` when the invoice has
payment instructions (BG-16), a due date (BT-9) or a payee (BG-10): FatturaPA then needs CondizioniPagamento, which has
no business term.

## 2. Write FPR12

The transmission header (`DatiTrasmissione`) describes one transmission to SdI, not the invoice, so it is a writer
option: [`Transmission`](reference/api.md#euinvoice.syntax.fatturapa.Transmission). `recipient_code`
(CodiceDestinatario) defaults to `0000000`, the value for an unknown channel or a delivery by PEC
(`recipient_pec`).

```python
>>> from euinvoice import Syntax, detect, to_xml
>>> from euinvoice.syntax import fatturapa
>>> transmission = fatturapa.Transmission(
...     transmitter_country="IT", transmitter_code="00000000001", transmission_number="00001"
... )
>>> xml = to_xml(invoice, syntax=Syntax.FATTURAPA, fatturapa_transmission=transmission)
>>> found = detect(xml)
>>> found.syntax, found.fatturapa_version
(<Syntax.FATTURAPA: 'fatturapa'>, 'FPR12')
```

`to_xml` takes no profile for FatturaPA. It runs
[`fatturapa.preflight`](reference/api.md#euinvoice.syntax.fatturapa.preflight) first (what the invoice lacks, what
FPR12 cannot carry, totals against the summaries), writes the file, then runs the offline SdI checks on it. An
`error` from either raises `PreflightError` with the findings:

```python
>>> from euinvoice.errors import PreflightError
>>> try:
...     to_xml(invoice.model_copy(update={"it": None}), syntax="fatturapa", fatturapa_transmission=transmission)
... except PreflightError as error:
...     for finding in error.findings:
...         print(finding.rule_id, finding.location)
EUINVOICE-FATTURAPA-EXTENSION it
```

SdI also checks the name and size of the file it receives (codes 00001 and 00003), which `validate()` cannot see.
[`file_name`](reference/api.md#euinvoice.syntax.fatturapa.file_name) builds a name per Allegato A 1.9.1 §1.2.2, and
[`check_file`](reference/api.md#euinvoice.syntax.fatturapa.check_file) checks a name and a size:

```python
>>> name = fatturapa.file_name("IT", "00000000001", "00001")
>>> name
'IT00000000001_00001.xml'
>>> fatturapa.check_file(name, len(xml))
()
>>> [f.rule_id for f in fatturapa.check_file("invoice.xml", len(xml))]
['00001']
```

## 3. Read it back

[`parse`](reference/api.md#euinvoice.parse) and [`parse_detailed`](reference/api.md#euinvoice.parse_detailed) read
a FatturaPA file with one body. The transmission header has no business term, so it is listed as unmapped. The
invoice reads back as written, up to what App. 4.1 derives: here BT-120 of the exempt VAT breakdown is the Natura
("In BT-120 vengono concatenati 2.2.2.2 <Natura> e 2.2.2.8 <RiferimentoNormativo>"), and `Invoice.it.vat_summaries`
holds the summary's Natura. Writing the read invoice gives the same file:

```python
>>> from euinvoice import parse, parse_all, parse_detailed
>>> result = parse_detailed(xml)
>>> result.unmapped
('/p:FatturaElettronica/FatturaElettronicaHeader/DatiTrasmissione',)
>>> result.invoice.vat_breakdown[1].exemption_reason
'N4'
>>> to_xml(result.invoice, syntax="fatturapa", fatturapa_transmission=transmission) == xml
True
```

A batch file (lotto) holds several bodies that share the header. `parse` and `parse_detailed` refuse it with
`UnsupportedDocumentError`; [`parse_all`](reference/api.md#euinvoice.parse_all) returns one `ParseResult` per body
(and a single one for UBL, CII and Factur-X):

```python
>>> [r.invoice.number for r in parse_all(xml)]
['FT-2026-1']
```

## 4. Convert to UBL or CII

The UBL and CII writers have no place for `Invoice.it`, so they refuse an invoice that sets it. To convert the
EN 16931 content alone, drop the extensions on purpose.
[`extension_paths`](reference/api.md#euinvoice.model.extension_paths) lists what goes and
[`without_extensions`](reference/api.md#euinvoice.model.without_extensions) drops it:

```python
>>> from euinvoice.model import extension_paths, without_extensions
>>> extension_paths(invoice)
('it', 'lines[1].it')
>>> ubl = to_xml(without_extensions(invoice), syntax="ubl")
>>> parse(ubl) == without_extensions(invoice)
True
```

## 5. Validate

FatturaPA has no official Schematron and no public validator. [`validate`](reference/api.md#euinvoice.validate)
validates it by syntax (it has no BT-24, so it takes no profile): the pinned FatturaPA XSD 1.2.3, then, if the XSD
passes, the offline SdI checks of Allegato A 1.9.1, Appendix 1. These are euinvoice's encoding of official prose,
not an official rule set. Each failed check is an `error` finding whose `rule_id` is the SdI error code (such as
`00421`), whose message quotes Allegato A and whose `source` is `sdi`. A schema error is an `XSD` finding. An FPA12
document gets the same checks, after an `information` finding `EUINVOICE-FATTURAPA-FPA12`.

<!-- doctest: needs-artifacts -->
```python
>>> from euinvoice import validate
>>> report = validate(xml)
>>> report.ok, report.findings
(True, ())
```

Here the tax of the 22 % summary (`Imposta`) is off by more than a cent, which SdI rejects with code 00421:

<!-- doctest: needs-artifacts -->
```python
>>> broken = xml.replace(b"<Imposta>11.00</Imposta>", b"<Imposta>11.10</Imposta>")
>>> [(f.rule_id, f.severity, f.source) for f in validate(broken).findings]
[('00421', <Severity.ERROR: 'error'>, 'sdi')]
```

`report.ok` can be `True` for a file SdI still rejects. Where Allegato A and SdI's "Elenco dei controlli" v2.0 disagree,
it can also report a code SdI does not raise: 00418 is checked on every document, while the Elenco checks it only on
TD04 ([#130](https://github.com/letsrevel/euinvoice/issues/130)). `validate()` does **not** check
(IMPLEMENTATION_PLAN.md D8; the module docstring of `euinvoice.validation.sdi` lists every code with its reason):

- the tax register and SdI's state: identifiers and VAT groups (00300-00306, 00320-00327), whether the
  CodiceDestinatario exists and is active (00311, 00312), a PEC address that is one of SdI's own (00330), the IPA
  registry checks for public administrations (00398, 00399), the receipt date (00403), a duplicate of an invoice
  sent earlier (00404) and an invalidated declaration of intent (00477);
- the transmitted file: its name (00001, 00002), its size (00003) and an empty or unreadable compressed
  file (00106). Use
  `fatturapa.check_file` for 00001 and 00003;
- the signature (00100-00105, 00107): v1 is unsigned. `parse()`, `detect()`, `validate()` and the CLI refuse a
  signed `.p7m` with `UnsupportedDocumentError`; extract its XML first;
- the parts of the prose that are ambiguous: 00424 and parts of 00409, 00423 and 00471-00473
  ([#130](https://github.com/letsrevel/euinvoice/issues/130));
- simplified invoices (FSM10, 00460), which are not detected as FatturaPA.

## Command line

```bash
python -m euinvoice validate IT00000000001_00001.xml              # XSD 1.2.3 + SdI checks; also a lotto
python -m euinvoice info IT00000000001_00001.xml                  # one invoice per file
python -m euinvoice convert IT00000000001_00001.xml --to ubl --drop-extensions
python -m euinvoice convert IT00000000001_00001.xml --to fatturapa \
    --transmitter IT00000000001 --transmission-number 00002 [--recipient-code CODE] [--pec ADDRESS]
```

`convert --to ubl|cii` refuses an invoice with `Invoice.it` unless `--drop-extensions` is given, and then reports
each dropped path on stderr. `convert --to fatturapa` takes the transmission header from `--transmitter` (country
code and tax id), `--transmission-number` (ProgressivoInvio), `--recipient-code` (CodiceDestinatario, default
`0000000`) and `--pec` (PECDestinatario); the invoice needs `Invoice.it`, so the input is in practice a FatturaPA
file. `info` and `convert` read one invoice and refuse a lotto (exit 1); `validate` checks all its bodies.

## Refusals and open questions

Where the sources do not settle a mapping, euinvoice does the most conservative thing: the writer refuses with an
`error` finding and the reader refuses with `ParseError` or lists the element as unmapped. Nothing is rounded or
guessed. The open questions wait for a maintainer decision (`needs-human`):

- [#133](https://github.com/letsrevel/euinvoice/issues/133), writer: for example generic document level allowances
  and charges (only a zero stamp duty is written), VAT categories O, L and M, BT-154, and payment data without
  `Invoice.it.payment`.
- [#132](https://github.com/letsrevel/euinvoice/issues/132), reader: for example `PrezzoTotale` with more than two
  decimals, the generic Natura N2, N3 and N6, and the BT-81 of each ModalitaPagamento.
- [#136](https://github.com/letsrevel/euinvoice/issues/136): the ModalitaPagamento codes App. 5.6 gives no BT-81
  (MP07, MP09-MP11, MP14, MP16, MP20, MP21) read, but the writer refuses the read invoice.
- [#130](https://github.com/letsrevel/euinvoice/issues/130): the SdI checks Allegato A leaves partly open (see
  above).

## Outside euinvoice

euinvoice builds, reads and checks the document. Italian compliance needs more, and these are out of scope:

- **Signing** the file (CAdES `.p7m` or XAdES) is deferred.
- **Sending** it through SdI, directly or via an intermediary, needs network access and credentials, which the core
  never has. Delivery belongs in separate packages ([#114](https://github.com/letsrevel/euinvoice/issues/114)). Fatture
  in Cloud cannot send externally generated XML: it sends only documents created in Fatture in Cloud (e.g. through its
  API), so it would need an adapter from `Invoice` to its JSON
  ([#124](https://github.com/letsrevel/euinvoice/issues/124)).
- **Ticket sales**: shows may need SIAE-approved ticketing systems rather than invoices, and retail-type sales to
  consumers the corrispettivi telematici. Which regime applies is a question for a commercialista
  ([#125](https://github.com/letsrevel/euinvoice/issues/125)).
- The Italian UBL profile (Peppol BIS Italia, CIUS-IT) is a possible later addition
  ([#123](https://github.com/letsrevel/euinvoice/issues/123)).
