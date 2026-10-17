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
no business term. ModalitaPagamento comes from `it.payment.method` or, without it, from BT-81 through App. 5.6. App. 5.6
maps BT-81 to a code many to one and gives no BT-81 to MP07, MP09, MP10, MP11, MP14, MP16, MP20 and MP21, so for these
eight set `it.payment.method` and give BT-81 `1` (UNTDID 4461, "Instrument not defined"), which is what the reader
produces. `1` next to any other method is refused, because App. 5.6 maps `1` to MP01; so is any BT-81 whose App. 5.6
row is not the explicit method.

How the writer treats the terms that FatturaPA carries differently (maintainer decisions on #133, built in #149):

- **BT-153 and BT-154** become one `Descrizione` (row 2.2.1.4), `BT-153 - BT-154`. Above 1000 characters (the XSD's
  `String1000LatinType`) the pre-flight refuses. A reader gives the joined text back as BT-153.
- **BT-20** is carried when it is the CondizioniPagamento code, optionally followed by a space and the days
  (`TP02 30`, 0 to 999, the reader's form). The days go to `GiorniTerminiPagamento` (row 2.4.2.4). Any other BT-20
  text is refused.
- **BT-120** on a VAT breakdown split by Natura is written into every `DatiRiepilogo` that has no
  `legal_reference` (row 2.2.2.8). A `DatiRiepilogo` with a Natura and no `RiferimentoNormativo` at all gets a
  `warning` finding from the pre-flight (Allegato A 1.9.1, DatiRiepilogo: the element is mandatory for operations
  with a Natura, no SdI code checks it). A warning does not block `to_xml`.
- **BT-23 and BT-34** are accepted like BT-24 and not written; **BT-49** is accepted only when it equals the
  `CodiceDestinatario` of the `Transmission`, compared by value whatever its scheme id (pass it to `preflight(invoice, transmission)`), and otherwise refused.
  A Peppol-shaped invoice can therefore be written, and is read back without those terms.

A party is written as `Denominazione` = BT-27 / BT-44 by default. Allegato A 1.9.1 (pp. 33 and 38: seller and buyer) reserves `Denominazione`
for a "persona non fisica" and asks for `Nome` and `Cognome` for a natural person, so for a person (a consumer, a sole
trader) set the name split on `Invoice.it`: `seller_first_name` / `seller_last_name` (1.2.1.3.2-3) and
`buyer_first_name` / `buyer_last_name` (1.4.1.3.2-3), each pair together or not at all, each part 1 to 60 Latin-1
characters (`String60LatinType`). The writer then emits `Nome` and `Cognome` instead of `Denominazione`. BT-27 / BT-44
must stay `Nome Cognome` (the two parts joined by one space: App. 4.1 folds them into the BT with `&` or `#` and a CIUS-IT marker, and the single space is the reader's own form, #132 item 2a),
or the pre-flight reports `EUINVOICE-FATTURAPA-NAME`: a different BT would be read back as another name. Reading a
natural person fills the split, so FPR12 to model to FPR12 keeps `Nome` and `Cognome`. `Titolo`, if present, is still
listed as unmapped.

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

### Line allowances and charges

A line allowance (BG-27) is written as a `ScontoMaggiorazione` of `Tipo` SC and a line charge (BG-28) as one of `Tipo`
MG, with `Importo` the amount divided by the invoiced quantity BT-129 (App. 4.1 row 2.2.1.10.3: the amount per unit).
The item price discount BT-147 stays the first `ScontoMaggiorazione`, so that `PrezzoTotale` is
(`PrezzoUnitario` ± the `Importo` entries) × `Quantita`, the formula of SdI check 00423, whatever the number of
entries. `ScontoMaggiorazione` has no place for the reason that EN 16931 requires (BR-42, BR-44), so each reason is an
`AltriDatiGestionali` (row 2.2.1.16) written after `RiferimentoAmministrazione`:

| `TipoDato` | `RiferimentoTesto` | `RiferimentoNumero` |
|---|---|---|
| `BT-139` | the allowance reason | the position (from 1) of its `ScontoMaggiorazione` in the line |
| `BT-140` | the allowance reason code | the same |
| `BT-144` | the charge reason | the same |
| `BT-145` | the charge reason code | the same |

The reader maps them back: an `AltriDatiGestionali` with one of these `TipoDato` and a position that exists explains
that `ScontoMaggiorazione`, whose amount is `Importo` × `Quantita`; the one that nothing explains is BT-147. Any other
`AltriDatiGestionali` is still read as an item attribute (BG-32), so FPR12 → model → FPR12 loses nothing. The reader
refuses (`ParseError`) an entry that has such a `TipoDato` and a valid position but whose `ScontoMaggiorazione` is not
SC (or MG) with an `Importo` and no `Percentuale`, and any explained `ScontoMaggiorazione` on a line with a negative
`PrezzoUnitario` (the reader negates BT-129 there, and no source says how an allowance or charge follows that sign).

The writer refuses, with an `error` finding that names the term, what it cannot write exactly:

- an amount whose division by BT-129 has no `Amount8DecimalType` value that multiplies back to the amount (for example
  1.00 over a quantity of 3), or any amount on a line of quantity 0;
- a negative BT-129 (`Quantita` is unsigned);
- a reason longer than 60 characters or outside Latin-1 (`RiferimentoTesto`, `String60LatinType`);
- a base amount or a percentage (BT-137, BT-138, BT-142, BT-143): the writer emits `Importo` only (SdI check 00423 can
  check a `Percentuale` since the Elenco algorithm was adopted, so this is a possible follow-up, not a limit of the check);
- a BT-131 that SdI 00423 would refuse (`EUINVOICE-FATTURAPA-LINE-TOTAL`). EN 16931 itself only requires BT-131
  (BR-24, two decimals by BR-DEC-23); the formula BT-131 = BT-129 × BT-146 − Σ BT-136 + Σ BT-141 is Peppol BIS rule
  PEPPOL-EN16931-R120.

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

`report.ok` can be `True` for a file SdI still rejects. Allegato A 1.9.1 is the check list; where it is silent or
ambiguous, the pseudo-code of SdI's "Elenco dei controlli" v2.0 settles the check (00409, 00419, 00423, 00424;
[#130](https://github.com/letsrevel/euinvoice/issues/130)). Where Allegato A is explicit it wins, so `validate()` can
also report a code SdI does not raise: 00418 is checked on every document, while the Elenco checks it only on TD04,
and 00471 covers the 13 TipoDocumento of Allegato A, while the Elenco lists TD16-TD20 and TD29.
`validate()` does **not** check
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
- the parts of the prose that neither Allegato A nor the Elenco settle: parts of 00472 and 00473
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

## Reader decisions

Two readings settled by the maintainer ([#132](https://github.com/letsrevel/euinvoice/issues/132) items 1 and 21):

- **`PrezzoTotale` beyond two decimals.** The element is `Amount8DecimalType` (2 to 8 decimals), while BT-131 is an
  EN 16931 amount of at most two. BT-131 is the declared value rounded half up; the exact value is kept in
  `InvoiceLine.it.total_price` (2.2.1.11) and the element is listed as `…/PrezzoTotale/text()` in
  `ParseResult.unmapped`. The writer writes `total_price` back when it rounds to BT-131, so the round trip is lossless;
  otherwise it reports a pre-flight error. No other declared amount is changed, so a summary that sums the unrounded
  lines is judged by `validate()` as declared.
- **`Natura` with a rate, TD16 only.** The SdI accepts it only on a TD16 (Allegato A 1.9.1, checks 00401 and 00430).
  There, on a line or a `DatiCassaPrevidenziale`, it reads as VAT category S at that rate (no BT-120 or BT-121), with
  the Natura kept in `InvoiceLine.it.nature` and `Invoice.it.vat_summaries` (in BT-104 for a fund). Any other
  document type refuses it. The v1 writer does not emit TD16, so it refuses to write that reading with a pre-flight
  error.

## Addresses outside Italy

CAPType is five digits and the technical rules say nothing about foreign addresses. Agenzia delle Entrate's FAQ
compendium of 22 December 2022 does (FAQ n. 63 and n. 74): outside Italy the CAP is the generic `00000`. For an address
whose `Nazione` is not `IT`, the writer writes a post code of five digits as it is, and anything else (`SW1A 1AA`,
`1011 AB`, no post code at all) as `00000`. The real foreign post code is not carried in `Indirizzo`: the FAQ only
allows it ("si potrà"), and a suffix in that free-text line could not be told from the street on the way back. When a
post code is dropped this way, `preflight` reports a `warning` finding `EUINVOICE-FATTURAPA-POST-CODE`; it does not
block the write. The reader turns `00000` outside Italy into no post code. For an Italian address nothing changes: the
post code is required and must be five digits.

## Refusals and open questions

Where the sources do not settle a mapping, euinvoice does the most conservative thing: the writer refuses with an
`error` finding and the reader refuses with `ParseError` or lists the element as unmapped. Nothing is rounded or
guessed. The open questions wait for a maintainer decision (`needs-human`):

- [#133](https://github.com/letsrevel/euinvoice/issues/133), writer: for example document level allowances
  and charges (only a zero stamp duty is written; line ones are, see above), VAT categories O, L and M, and payment data without
  `Invoice.it.payment`.
- [#132](https://github.com/letsrevel/euinvoice/issues/132), reader: for example the generic Natura N2, N3 and N6,
  and the BT-81 of each ModalitaPagamento.
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
