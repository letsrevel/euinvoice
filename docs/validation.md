# Validation

euinvoice validates with the **official** artifacts: the XSD of the syntax, then the Schematron rule sets of the
profile (CEN EN 16931, Peppol BIS Billing 3.0, XRechnung). It does not reimplement the rules. When euinvoice's
own checks and the official Schematron disagree, the Schematron is right.

## 1. Install and fetch the artifacts

```bash
uv add 'euinvoice[validate]'            # SaxonC-HE runs the Schematron (XSLT 3.0)
python -m euinvoice artifacts fetch     # once; or: make artifacts in a checkout
```

The artifacts are not bundled, because of their licences ([Artifact licences](reference/artifacts.md)). `fetch`
downloads the pinned archives listed in `src/euinvoice/validate/manifest.toml`, checks each sha256, and
extracts them into `$EUINVOICE_ARTIFACTS_DIR` (default `~/.cache/euinvoice`). Rule sets that upstream ships as
`.sch` only (Peppol) are compiled to XSLT with SchXslt during the fetch.

`validate()` never downloads anything. If the cache is cold it raises `ArtifactsNotAvailableError`, whose
message is the command to run. Without the `[validate]` extra it raises the same error naming the extra.

!!! note "Command-line interface"
    `python -m euinvoice artifacts fetch` is the only CLI command so far. `validate`, `convert` and `info`
    subcommands are planned ([#28](https://github.com/letsrevel/euinvoice/issues/28)).

## 2. Validate a document

[`validate`](reference/api.md#euinvoice.validate) takes the XML bytes. Without a profile it reads BT-24 and
picks the registered profile for it; pass `profile=` to choose one. These examples continue the
[Quickstart](quickstart.md) (`ubl` and `cii` are its EN 16931 invoice).

<!-- doctest: needs-artifacts -->
```python
>>> from euinvoice import profiles, validate
>>> report = validate(ubl)  # BT-24 urn:cen.eu:en16931:2017: XSD + CEN rules
>>> report.ok, report.findings
(True, ())
```

`validate()` returns a [`ValidationReport`](reference/api.md#euinvoice.ValidationReport); rule failures are
findings, never exceptions. `report.ok` is `True` when no finding is `fatal` or `error`; `warning` and
`information` findings do not count. Each [`Finding`](reference/api.md#euinvoice.report.Finding) has:

| Attribute | Example |
|---|---|
| `rule_id` | `BR-CO-09`, `PEPPOL-EN16931-R010`, `BR-DE-15`, or `XSD` for a schema error |
| `severity` | `fatal`, `error`, `warning` or `information` (the Schematron `flag`) |
| `location` | an XPath for Schematron, line and element for XSD |
| `message` | the rule's text |
| `source` | the rule set: `cen-ubl`, `peppol-bis`, `xsd:ubl-2_1`, … |

Here a seller VAT identifier without its country prefix breaks the CEN rule BR-CO-09:

<!-- doctest: needs-artifacts -->
```python
>>> broken = ubl.replace(b"ATU00000000", b"00000000")
>>> report = validate(broken)
>>> report.ok
False
>>> [(f.rule_id, f.severity, f.source) for f in report.findings]
[('BR-CO-09', <Severity.FATAL: 'fatal'>, 'cen-ubl')]
>>> print(report.findings[0].message[:60])
[BR-CO-09]-The Seller VAT identifier (BT-31), the Seller tax
```

The same invoice is valid EN 16931, but it lacks terms a CIUS requires. Validating it under XRechnung reports
them:

<!-- doctest: needs-artifacts -->
```python
>>> report = validate(ubl, profiles.XRECHNUNG)
>>> sorted(f.rule_id for f in report.findings if f.severity == "fatal")
['BR-DE-15', 'BR-DE-2', 'PEPPOL-EN16931-R001', 'PEPPOL-EN16931-R010', 'PEPPOL-EN16931-R020']
```

If the document's BT-24 names no registered profile, `validate()` falls back to EN 16931 core and the report
starts with an `information` finding `EUINVOICE-PROFILE-FALLBACK` that says only the core rules ran. The
exception is a BT-24 that names a Factur-X / ZUGFeRD level without pinned rules (see [Factur-X](#factur-x)).

## 3. Catch problems before writing

`to_xml` runs the profile's pre-flight checks and [`calc.check`](reference/api.md#euinvoice.calc.check) before
it writes anything, and raises `PreflightError` when the official rules would reject the result. The findings
carry the official rule ids and point at the model field to fix. Writing the quickstart invoice for Peppol:

```python
>>> from euinvoice import to_xml
>>> from euinvoice.errors import PreflightError
>>> try:
...     to_xml(invoice, profile=profiles.PEPPOL, syntax="ubl")
... except PreflightError as error:
...     for finding in error.findings:
...         print(finding.rule_id, finding.location)
PEPPOL-EN16931-R003 buyer_reference
PEPPOL-EN16931-R010 buyer.electronic_address
PEPPOL-EN16931-R020 seller.electronic_address
```

Pre-flight is a convenience. It never replaces `validate()`, which gives the verdict.

## Factur-X

The Factur-X / ZUGFeRD Schematron is not pinned yet ([#42](https://github.com/letsrevel/euinvoice/issues/42)).
`validate()` therefore raises `ArtifactsNotAvailableError` for the levels that only that Schematron covers:
MINIMUM, BASIC WL, BASIC and EXTENDED. It also raises it, rather than falling back to EN 16931 core, for a CII
document whose BT-24 names one of these levels without being a profile's: the ZUGFeRD 2.0 MINIMUM, BASIC and
EXTENDED identifiers and the colon spellings of BASIC and EXTENDED
(`urn:cen.eu:en16931:2017:compliant:factur-x.eu:1p0:…`). Pass `profiles.EN16931` to run the core rules alone.
`profiles.FACTURX_EN16931` and `profiles.FACTURX_XRECHNUNG` validate the
CII XML against the D16B XSD and the CEN rules (plus the XRechnung rules for `FACTURX_XRECHNUNG`), so their `ok` is
the EN 16931 (or XRechnung) verdict, not a full Factur-X one. See [Factur-X](facturx.md).
