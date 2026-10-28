# Germany, France, Austria

What each country requires of an invoice issuer, and what euinvoice does and does not cover. Checked 2026-10-28.
This page is not tax advice. It records what the cited sources say, so you can check them; confirm your own case
with a tax adviser.

Fact markers: unmarked facts were read in the official source linked next to them. Facts marked **(secondary)**
were read in a tax-firm or vendor page, not in an official text. Facts the sources did not settle are listed as
unconfirmed.

## Germany

**Mandate and dates.**

- An E-Rechnung is a structured invoice that conforms to EN 16931, or to an agreed format that can be converted
  into it ([§14 Abs. 1 UStG](https://www.gesetze-im-internet.de/ustg_1980/__14.html)).
- The E-Rechnung duty applies to supplies between businesses that are both established in Germany
  ([§14 Abs. 2 S. 2 Nr. 1 UStG](https://www.gesetze-im-internet.de/ustg_1980/__14.html)), except supplies exempt
  under §4 Nr. 8 to 29. Supplies to non-business legal persons need an invoice, not an E-Rechnung. Apart from
  land-related work (Nr. 3), there is no invoice duty towards private consumers.
- Receiving E-Rechnungen has been required since 2025-01-01. Issuing is required from 2027-01-01 for issuers with
  prior-year turnover above 800 000 EUR, and from 2028-01-01 for everyone else. Until then paper, or other
  electronic formats with the recipient's consent, are allowed ([§27 Abs. 38 UStG](https://www.gesetze-im-internet.de/ustg_1980/__27.html)).
- Invoices up to 250 EUR gross may stay "sonstige Rechnungen". The test applies to the whole invoice total
  ([§33 UStDV](https://www.gesetze-im-internet.de/ustdv_1980/__33.html)).
- Federal public buyers: e-invoices are required, normally XRechnung (other EN 16931-conformant standards are
  allowed, §4 Abs. 1 ERechV) with a Leitweg-ID (§5); direct orders up to 1 000 EUR are exempt (§3 Abs. 3)
  ([ERechV](https://www.gesetze-im-internet.de/erechv/ERechV.pdf)). The Leitweg-ID goes in BT-10, Buyer reference
  ([e-rechnung-bund.de](https://e-rechnung-bund.de/en/e-invoicing-for-invoice-issuers)). ZRE was merged into OZG-RE
  (final migration 2025-09-19, [platform consolidation](https://e-rechnung-bund.de/en/platform-consolidation/));
  OZG-RE is the federal portal, though indirect federal bodies may run their own
  ([e-rechnung-bund.de](https://e-rechnung-bund.de/en/e-invoicing-for-invoice-issuers)).

**Accepted formats.**

- Per the BMF letter of 2025-10-15 (secondary; the BMF site was not reachable on 2026-10-28; summaries:
  [taxpunk synopsis](https://taxpunk.de/media/e-rechnung-synopse-bmf-schreiben.pdf),
  [Haufe](https://www.haufe.de/steuern/finanzverwaltung/weiteres-bmf-schreiben-zur-e-rechnung_164_655070.html)):
  for example XRechnung, and ZUGFeRD 2.0.1 or later except MINIMUM and BASIC-WL; any EN 16931-conformant format
  qualifies (secondary). In a hybrid PDF the XML prevails.
- XRechnung 3.0.2 is the current version. A 4.0 final is expected in spring 2027, driven by EN 16931-1:2026
  ([xeinkauf.de](https://xeinkauf.de/xrechnung/versionen-und-bundles/),
  [outlook](https://xeinkauf.de/aktuelles/xse/en-16931-aktueller-stand-und-ausblick-auf-die-einfuehrung-der-xrechnung-4-0/)).

**Delivery.**

- B2B: per the BMF letter (secondary), e-mail is enough. There is no clearance step.
- B2G: OZG-RE web form, upload, Peppol or e-mail
  ([e-rechnung-bund.de](https://e-rechnung-bund.de/en/e-invoicing-for-invoice-issuers)). The Peppol recipient id
  is `0204:<Leitweg-ID>` ([Peppol guide](https://e-rechnung-bund.de/fileadmin/pdf/Leitfaden-Uebertragungskanal-Peppol_092025.pdf)).

**euinvoice today.** XRechnung 3.0.2 in UBL and CII, validated against the KoSIT rules; Factur-X EN 16931 and
XRECHNUNG levels (both qualify under the BMF letter, secondary); the BT-10 Leitweg-ID pre-flight check for
XRechnung. Not covered: sending (e-mail, OZG-RE, Peppol; see [#114](https://github.com/letsrevel/euinvoice/issues/114));
Factur-X-level Schematron rules ([#42](https://github.com/letsrevel/euinvoice/issues/42)); XRechnung 4.0 and
EN 16931-1:2026 ([#180](https://github.com/letsrevel/euinvoice/issues/180)).

Unconfirmed: the primary text of the BMF letter, and the rules of the individual Länder portals.

## France

**Mandate and dates.** The reform is in force since 2026-09-01: every company in scope of the reform (taxable
persons established in France) must be able to receive e-invoices, and large companies and mid-sized companies
(ETI) must issue e-invoices and e-report. SMEs and micro-enterprises follow on 2027-09-01
([DGFiP guide, July 2026](https://www.impots.gouv.fr/sites/default/files/media/1_metier/2_professionnel/EV/2_gestion/290_facturation_electronique/guide_pratique_facturation_electronique.pdf)).
The guide mentions a start-up tolerance without sanctions; the official text gives no end date.

**Scope.**

- E-invoicing covers domestic B2B between taxable persons established in France. A foreign company with no French
  permanent establishment is not subject to e-invoicing; only e-reporting may apply
  ([impots.gouv.fr](https://www.impots.gouv.fr/international-professionnel/le-reporting-pour-les-entreprises-etrangeres-sans-etablissement-stable)).
- E-reporting for such a company covers transactions in France subject to French VAT. It does not apply to
  transactions with non-taxable persons if the seller is registered in the EU VAT One Stop Shop
  ([impots.gouv.fr](https://www.impots.gouv.fr/internationalenbusiness/e-reporting-requirements-foreign-companies-without-permanent-establishment)).
- A third party may issue invoices on the supplier's behalf (mandat de facturation, CGI 289 I-2). The invoice
  stays the supplier's and goes through the platform under the supplier's SIREN (secondary:
  [guide-plateforme-agreee.fr](https://guide-plateforme-agreee.fr/mandat-de-facturation-facturation-electronique/)).

**Accepted formats.** Factur-X, UBL (EN 16931 France CIUS) and UN/CEFACT CII (EN 16931 France CIUS)
([peppol.org](https://peppol.org/learn-more/country-profiles/france/)). The profiles are defined by AFNOR
XP Z12-012, the platform APIs by XP Z12-013 and use cases by XP Z12-014
([AIFE](https://aife.economie.gouv.fr/nos-applications/facturation-electronique-b2b/)). The current external
specifications are v3.2 of 2026-04-30
([impots.gouv.fr](https://www.impots.gouv.fr/specifications-externes-b2b)). The French business rules (BR-FR) come
on top of EN 16931 ([France_RFE](https://github.com/fnfempe/France_RFE), [#178](https://github.com/letsrevel/euinvoice/issues/178)).

**Delivery.** Issuing goes through a Plateforme Agréée (PA); the list is linked from
[impots.gouv.fr](https://www.impots.gouv.fr/facturation-electronique-et-plateformes-agreees). The public portal
(PPF) is the directory and concentrator
([AIFE](https://aife.economie.gouv.fr/nos-applications/facturation-electronique-b2b/)). DGFiP has been the French
Peppol Authority since 2025-07-08, and Peppol can carry B2B flows between platforms
([peppol.org](https://peppol.org/learn-more/country-profiles/france/)).

**euinvoice today.** UBL, CII and Factur-X output under EN 16931, and a Peppol profile that already accepts the
two French process ids in BT-23. Not covered:

- a French profile with the BR-FR rules (SIREN and endpoint identifiers, the restricted BT-3 list, the
  BT-23 frame codes, the payment-recovery note): planned, see
  [#178](https://github.com/letsrevel/euinvoice/issues/178);
- the Factur-X Schematron, which the French rule set pin also delivers:
  [#42](https://github.com/letsrevel/euinvoice/issues/42);
- French CII: which CII version (D16B or D22B) XP Z12-012 requires is not yet confirmed, see
  [#179](https://github.com/letsrevel/euinvoice/issues/179). Our CII writer is D16B;
- e-reporting, lifecycle statuses and the platform API client. These are outside the library.

Unconfirmed: the Légifrance texts (CGI 289 bis and 290, décret 2026-677), the application dates of the four new
invoice mentions, the penalty amounts, and per-platform adoption of the XP Z12-013 API.

## Austria

**Mandate and dates.** Electronic invoices (IKTKonG §5 Abs. 1) to federal bodies, in the structured formats of the
e-rechnung.gv.at [guide](https://www.erechnung.gv.at/go/leitfaden), have been required since 2014-01-01
([IKTKonG §5](https://www.ris.bka.gv.at/eli/bgbl/i/2012/35/P5/NOR40211767),
[e-rechnung.gv.at guide](https://www.erechnung.gv.at/go/leitfaden)). No B2B or B2C mandate and no date were
found. Under [§11 Abs. 2 UStG](https://www.ris.bka.gv.at/NormDokument.wxe?Abfrage=Bundesnormen&Gesetzesnummer=10004873&Paragraf=11),
an electronic invoice needs the recipient's consent. Invoices up to 400 EUR gross may be simplified
(Kleinbetragsrechnung, §11 Abs. 6 UStG, same source).

**Accepted formats.** The federal portal accepts ebInterface 4.3, 5.0, 6.0, 6.1 and UBL 2.1. The Peppol route
takes UBL only ([e-rechnung.gv.at](https://www.erechnung.gv.at/erb/tec_formats)). Federal invoices must carry
an order reference and a supplier number. In UBL these are BT-13 (`/Invoice/OrderReference/ID`) and BT-29
(`/Invoice/AccountingSupplierParty/Party/PartyIdentification[1]/ID`)
([e-rechnung.gv.at](https://www.erechnung.gv.at/erb/de_AT/tec_formats_ubl)).

**Delivery.** Portal form, upload, web service, or Peppol. E-mailed PDFs are not e-invoices for the federal
government. Over Peppol all federal recipients share the id `9915:b`, and the invoice is routed by the order
reference, BT-13 ([e-rechnung.gv.at](https://www.erechnung.gv.at/erb/de_AT/tec_delivery_peppol)).

**euinvoice today.** UBL 2.1 under the Peppol BIS Billing 3.0 profile covers the Peppol route. BT-13 and the other
terms are plain EN 16931 fields. Not covered: ebInterface. It is not planned, because the federal portal accepts UBL 2.1; it would be revisited on
demand ([#182](https://github.com/letsrevel/euinvoice/issues/182)). Sending is outside
the library ([#114](https://github.com/letsrevel/euinvoice/issues/114)).

Unconfirmed: which BT carries the order position for the federal service, and whether the government plans a B2B
mandate.

## Simplified and small invoices

EN 16931 has no simplified profile. The German 250 EUR and Austrian 400 EUR thresholds, and any French rule for
low-value consumer receipts, are the caller's concern. euinvoice always writes full EN 16931 invoices; whether a
simplified document is allowed is outside the library.

Sources were last checked on the date at the top; open an issue if something has changed.
