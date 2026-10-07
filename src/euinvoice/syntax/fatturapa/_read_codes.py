"""The code tables the FatturaPA reader applies (#120), from the SdI "Regole tecniche fatture europee" v2.6, App. 5.

Each table cites its appendix. Where App. 5 maps EN codes to FatturaPA codes many-to-one, the reverse direction is a
choice the sources do not make; such choices are marked and listed in the mapping-policy issue
(https://github.com/letsrevel/euinvoice/issues/132).
"""

import typing as t

from euinvoice.model.it import ModalitaPagamento, Natura, TipoDocumento

__all__ = ["NATURE_CATEGORY", "PAYMENT_MEANS", "PAYMENT_MEANS_WITHOUT_ACCOUNT", "POLICY_ISSUE", "TYPE_CODE"]

POLICY_ISSUE: t.Final = "https://github.com/letsrevel/euinvoice/issues/132"
"""The ``needs-human`` issue listing the reader's mapping-policy questions (#115 decision 5)."""

TYPE_CODE: t.Final[t.Mapping[TipoDocumento, str]] = {
    TipoDocumento.TD01: "380",
    TipoDocumento.TD02: "386",
    TipoDocumento.TD03: "386",
    TipoDocumento.TD04: "381",
    TipoDocumento.TD05: "383",
    TipoDocumento.TD06: "380",
    TipoDocumento.TD16: "380",
    TipoDocumento.TD17: "380",
    TipoDocumento.TD18: "380",
    TipoDocumento.TD19: "380",
    TipoDocumento.TD20: "380",
    TipoDocumento.TD21: "380",
    TipoDocumento.TD22: "380",
    TipoDocumento.TD23: "380",
    TipoDocumento.TD24: "380",
    TipoDocumento.TD25: "380",
    TipoDocumento.TD26: "380",
    TipoDocumento.TD27: "380",
    TipoDocumento.TD28: "380",
    TipoDocumento.TD29: "380",
}
"""2.1.1.1 ``TipoDocumento`` → invoice type code BT-3, App. 5.4 (every code of XSD 1.2.3 has a row)."""

NATURE_CATEGORY: t.Final[t.Mapping[Natura, tuple[str, str | None]]] = {
    Natura.N1: ("Z", None),
    Natura.N2_1: ("E", "VATEX-EU-132"),
    Natura.N2_2: ("E", "VATEX-EU-132"),
    Natura.N3_1: ("G", "VATEX-EU-G"),
    Natura.N3_2: ("K", "VATEX-EU-IC"),
    Natura.N3_3: ("G", "VATEX-EU-G"),
    Natura.N3_4: ("G", "VATEX-EU-G"),
    Natura.N3_5: ("G", "VATEX-EU-G"),
    Natura.N3_6: ("K", "VATEX-EU-IC"),
    Natura.N4: ("E", "VATEX-EU-132"),
    Natura.N5: ("E", "VATEX-EU-132"),
    Natura.N6_1: ("AE", "VATEX-EU-AE"),
    Natura.N6_2: ("AE", "VATEX-EU-AE"),
    Natura.N6_3: ("AE", "VATEX-EU-AE"),
    Natura.N6_4: ("AE", "VATEX-EU-AE"),
    Natura.N6_5: ("AE", "VATEX-EU-AE"),
    Natura.N6_6: ("AE", "VATEX-EU-AE"),
    Natura.N6_7: ("AE", "VATEX-EU-AE"),
    Natura.N6_8: ("AE", "VATEX-EU-AE"),
    Natura.N6_9: ("AE", "VATEX-EU-AE"),
    Natura.N7: ("K", "VATEX-EU-151"),
}
"""``Natura`` → (VAT category code BT-118 / BT-151, VAT exemption reason code BT-121), App. 5.1 (first table,
"Fatture Domestiche"; the cross-border table agrees on every code it lists). N1 has no BT-121 ("Viene utilizzata VAT
category code Z"). The generic N2, N3 and N6, refused by the SdI since 2021 (check 00445), have no row, so they are not
here: the reader refuses them."""

# The reverse of App. 5.6 (BT-81 → ModalitaPagamento) is many-to-one, so a FatturaPA code has no single BT-81. The
# exact code is kept in Invoice.it.payment.method; BT-81 gets the App. 5.6 row whose description is the code's
# English equivalent (the only row where one code has just one), and UNTDID 4461 "1" (Instrument not defined) for the
# codes App. 5.6 never produces. A mapping-policy choice: see POLICY_ISSUE.
PAYMENT_MEANS: t.Final[t.Mapping[ModalitaPagamento, str]] = {
    ModalitaPagamento.MP01: "10",  # In cash
    ModalitaPagamento.MP02: "20",  # Cheque
    ModalitaPagamento.MP03: "21",  # Banker's draft
    ModalitaPagamento.MP04: "ZZZ",  # Mutually defined (the only row)
    ModalitaPagamento.MP05: "30",  # Credit transfer, with an IBAN (BR-61; see PAYMENT_MEANS_WITHOUT_ACCOUNT)
    ModalitaPagamento.MP06: "60",  # Promissory note
    ModalitaPagamento.MP08: "48",  # Bank card
    ModalitaPagamento.MP12: "70",  # Bill drawn by the creditor on the debtor
    ModalitaPagamento.MP13: "31",  # Debit transfer
    ModalitaPagamento.MP15: "57",  # Standing agreement (the only row)
    ModalitaPagamento.MP17: "42",  # Payment to bank account (the only row)
    ModalitaPagamento.MP18: "50",  # Payment by postgiro (the only row)
    ModalitaPagamento.MP19: "59",  # SEPA direct debit
    ModalitaPagamento.MP22: "97",  # Clearing between partners (the only row)
    ModalitaPagamento.MP23: "9",  # National or regional clearing (the only row)
}
"""``ModalitaPagamento`` → payment means type code BT-81 (see the comment above); codes not listed get ``"1"``."""

PAYMENT_MEANS_WITHOUT_ACCOUNT: t.Final[t.Mapping[ModalitaPagamento, str]] = {
    ModalitaPagamento.MP05: "15",  # Bookentry credit: the first App. 5.6 MP05 row that BR-61 does not tie to BT-84
}
"""BT-81 when the ``DettaglioPagamento`` has no IBAN: BR-61 (CEN ``EN16931-model.sch`` 1.3.16, fatal) requires the
payment account BT-84 for codes 30 and 58, and IBAN (2.4.2.13) is optional, so MP05 without one cannot be 30."""
