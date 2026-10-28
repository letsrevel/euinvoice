# Compliance status

Status as of euinvoice **v0.2.1** (2026-10-27). This page is updated with every release; the issues linked below
show the work in between.

It says which countries' e-invoicing rules euinvoice covers, what it validates against, and what comes next.
The legal background (mandates, dates, delivery) and its sources are on [Germany, France, Austria](countries.md)
and [FatturaPA](fatturapa.md). This page is not tax advice.

| Mark | Meaning |
|---|---|
| ✅ | Supported: euinvoice writes and reads the format and validates it against the pinned official rules |
| 🟡 | Partial: usable, but some official rules are not yet checked |
| 🔵 | Planned, with an open issue |
| ⚪ | Not planned |

## At a glance

| Country or network | What the law asks | euinvoice | Validated against | Next |
|---|---|---|---|---|
| EU, EN 16931 core | The European standard every national format builds on | ✅ UBL 2.1 and CII D16B, since 0.1.0 | CEN Schematron 1.3.16 | EN 16931-1:2026 ([#180](https://github.com/letsrevel/euinvoice/issues/180)); CEN 1.3.17 ([#147](https://github.com/letsrevel/euinvoice/issues/147)) |
| Peppol network | Peppol BIS Billing 3.0 for public buyers across Europe and B2B where used | ✅ UBL and CII, since 0.1.0 | Peppol BIS 3.0.21 rules | Re-pin to the 3.0.21 tag ([#176](https://github.com/letsrevel/euinvoice/issues/176)) |
| 🇩🇪 Germany | B2B: receive since 2025; issue from 2027 (turnover above 800 000 EUR) or 2028. B2G: XRechnung | ✅ XRechnung 3.0.2 (UBL, CII) since 0.1.0, KoSIT verdict since 0.2.0; 🟡 ZUGFeRD / Factur-X | KoSIT XRechnung Schematron 2.6.0; ZUGFeRD against the CEN rules only | ZUGFeRD Schematron ([#42](https://github.com/letsrevel/euinvoice/issues/42)); XRechnung 4.0 ([#180](https://github.com/letsrevel/euinvoice/issues/180)) |
| 🇫🇷 France | Receive since 2026-09-01; large and mid-sized companies issue since then, SMEs from 2027-09-01, through a Plateforme Agréée | 🟡 EN 16931 UBL, CII and Factur-X; 🔵 French profile (BR-FR rules) | CEN rules only | French rule files ([#42](https://github.com/letsrevel/euinvoice/issues/42)), then the `fr` profile ([#178](https://github.com/letsrevel/euinvoice/issues/178)); CII version ([#179](https://github.com/letsrevel/euinvoice/issues/179)) |
| 🇦🇹 Austria | Federal public buyers only (since 2014); no B2B mandate | ✅ UBL under Peppol BIS (the Peppol route of e-rechnung.gv.at); ⚪ ebInterface | Peppol BIS rules | None planned; ebInterface on demand ([#182](https://github.com/letsrevel/euinvoice/issues/182)) |
| 🇮🇹 Italy | All B2B and B2C invoices through SdI, in FatturaPA | ✅ FatturaPA FPR12 write and read, since 0.2.0 | FatturaPA XSD 1.2.3 and 34 offline SdI checks | Italian UBL profile ([#123](https://github.com/letsrevel/euinvoice/issues/123), not scheduled) |

Sending invoices (Peppol access points, Plateformes Agréées, SdI, OZG-RE) is outside the library for every
country ([#114](https://github.com/letsrevel/euinvoice/issues/114)).

## Next up

The current plan is tracked in [#182](https://github.com/letsrevel/euinvoice/issues/182) (target 0.3.0,
France first):

1. Pin the French rule set, which also brings the Factur-X Schematron ([#42](https://github.com/letsrevel/euinvoice/issues/42)).
2. The French `fr` profile, UBL first, with the BR-FR rules ([#178](https://github.com/letsrevel/euinvoice/issues/178)).
3. Decide which CII version French CII needs ([#179](https://github.com/letsrevel/euinvoice/issues/179)).
4. Re-pin Peppol BIS to the OpenPeppol 3.0.21 tag once docs.peppol.eu publishes it ([#176](https://github.com/letsrevel/euinvoice/issues/176)).
5. Watch EN 16931-1:2026 and XRechnung 4.0, expected in spring 2027 ([#180](https://github.com/letsrevel/euinvoice/issues/180)).

## Your country is missing?

Open an issue with the country, the mandate and a link to the official specification. Countries are added when
their official rules can be pinned and tested; see [Validation](validation.md) for how that works.
