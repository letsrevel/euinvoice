# Compliance status

Status as of euinvoice **v0.2.1** (2026-10-27). This page is updated with every release; the issues linked below
show the work in between.

It says which countries' e-invoicing rules euinvoice covers, what it validates against, and what comes next.
The legal background (mandates, dates, delivery) and its sources are on [Germany, France, Austria](countries.md)
and [FatturaPA](fatturapa.md). This page is not tax advice.

| Mark | Meaning |
|---|---|
| ✅ | Supported: euinvoice writes and reads the format and validates it against the pinned official rules (limits in the linked pages) |
| 🟡 | Partial: usable, but some official rules are not checked or some variants are not supported |
| 🔵 | Planned, with an open issue |
| ⚪ | Not planned |

## At a glance

| Country or network | What the law asks | euinvoice | Validated against | Next |
|---|---|---|---|---|
| EU, EN 16931 core | The European standard every national format builds on | ✅ UBL 2.1 and CII D16B, since 0.1.0 | CEN Schematron 1.3.16 | EN 16931-1:2026 ([#180](https://github.com/letsrevel/euinvoice/issues/180)); CEN 1.3.17 ([#147](https://github.com/letsrevel/euinvoice/issues/147)) |
| Peppol network | Peppol BIS Billing 3.0 for public buyers across Europe and B2B where used | ✅ UBL and CII, since 0.1.0 | Peppol BIS 3.0.21, the rule files published on docs.peppol.eu | Re-pin to the OpenPeppol 3.0.21 tag once docs.peppol.eu publishes its rule files ([#176](https://github.com/letsrevel/euinvoice/issues/176)) |
| 🇩🇪 Germany | B2B between businesses established in Germany: receive since 2025; issue from 2027 (prior-year turnover above 800 000 EUR) or 2028. Federal B2G: normally XRechnung | ✅ XRechnung 3.0.2 (UBL, CII) since 0.1.0, KoSIT verdict since 0.2.0; 🟡 XRechnung Extension; ⚪ XRechnung CVD (see [README](https://github.com/letsrevel/euinvoice#readme)); 🟡 Factur-X / ZUGFeRD EN 16931 and XRECHNUNG levels | KoSIT XRechnung Schematron 2.6.0; Factur-X / ZUGFeRD against the CEN and XRechnung rules, not the Factur-X Schematron; BASIC, EXTENDED, MINIMUM and BASIC WL are not validated | Factur-X Schematron ([#42](https://github.com/letsrevel/euinvoice/issues/42)); XRechnung 4.0 ([#180](https://github.com/letsrevel/euinvoice/issues/180)) |
| 🇫🇷 France | Domestic B2B between companies established in France: receive since 2026-09-01; large and mid-sized companies issue since then, SMEs from 2027-09-01, through a Plateforme Agréée | 🟡 EN 16931 UBL, CII and Factur-X; 🔵 French profile (BR-FR rules) | CEN rules only | French rule set pin, which also brings the Factur-X Schematron ([#42](https://github.com/letsrevel/euinvoice/issues/42)), then the `fr` profile ([#178](https://github.com/letsrevel/euinvoice/issues/178)); CII version ([#179](https://github.com/letsrevel/euinvoice/issues/179)) |
| 🇦🇹 Austria | E-invoices to federal bodies since 2014 (IKTKonG §5); no B2B or B2C mandate found as of 2026-10-28 | ✅ UBL under Peppol BIS (the Peppol route of e-rechnung.gv.at); ⚪ ebInterface | Peppol BIS rules | None planned; ebInterface on demand ([#182](https://github.com/letsrevel/euinvoice/issues/182)) |
| 🇮🇹 Italy | E-invoicing through SdI in FatturaPA ([Agenzia delle Entrate](https://www.agenziaentrate.gov.it/portale/web/guest/aree-tematiche/fatturazione-elettronica)); scope not summarised here yet | 🟡 FatturaPA FPR12 write (TD01, TD04, TD24, TD17; unsigned) and read, since 0.2.0 | FatturaPA XSD 1.2.3 and 32 of SdI's offline checks (Allegato A 1.9.1); there is no official Schematron, so `ok` can be true for a file SdI rejects ([FatturaPA](fatturapa.md)) | Italian UBL profile ([#123](https://github.com/letsrevel/euinvoice/issues/123), not scheduled) |

Sending invoices (Peppol access points, Plateformes Agréées, SdI, OZG-RE) is outside the library for every
country ([#114](https://github.com/letsrevel/euinvoice/issues/114)).

## Next up

The current plan is tracked in [#182](https://github.com/letsrevel/euinvoice/issues/182) (target 0.3.0,
France first):

1. Pin the French rule set, which also brings the Factur-X Schematron ([#42](https://github.com/letsrevel/euinvoice/issues/42)).
2. The French `fr` profile, UBL first, with the BR-FR rules ([#178](https://github.com/letsrevel/euinvoice/issues/178)).
3. Decide which CII version French CII needs ([#179](https://github.com/letsrevel/euinvoice/issues/179)).
4. Re-pin Peppol BIS to the OpenPeppol 3.0.21 tag once docs.peppol.eu publishes its rule files ([#176](https://github.com/letsrevel/euinvoice/issues/176)).
5. Watch EN 16931-1:2026 and XRechnung 4.0, expected in spring 2027 ([#180](https://github.com/letsrevel/euinvoice/issues/180)).

## Your country is missing?

Open an issue with the country, the mandate and a link to the official specification. Countries are added when
their official rules can be pinned and tested; see [Validation](validation.md) for how that works.
