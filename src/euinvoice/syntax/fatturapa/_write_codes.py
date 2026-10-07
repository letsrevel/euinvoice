"""Code tables of the writer, from App. 4.1 and 5 of the SdI "Regole tecniche fatture europee" v2.6 (15/05/2025).

Each table is transcribed from the named appendix of ``Specifiche-Tecniche-Fatturazione-Europea-v2.6.pdf``
(fatturapa.gov.it, fetched for #115; not a pinned artifact, plan §3). Only the rows the v1 writer needs are here.
"""

import types
import typing as t

from euinvoice.model.codes import VatCategory
from euinvoice.model.it import EsigibilitaIVA, ModalitaPagamento, Natura, TipoDocumento

__all__ = [
    "CATEGORY_OF_NATURA",
    "CHARGEABILITY_OF_VAT_POINT",
    "DOCUMENT_TYPES",
    "PAYMENT_METHOD_OF_MEANS",
    "VATEX_OF_NATURA",
]

DOCUMENT_TYPES: t.Final[t.Mapping[TipoDocumento, str]] = types.MappingProxyType(
    {
        TipoDocumento.TD01: "380",
        TipoDocumento.TD04: "381",
        TipoDocumento.TD17: "380",
        TipoDocumento.TD24: "380",
    }
)
"""The TipoDocumento codes the v1 writer emits (plan M11) and the invoice type code BT-3 of each (App. 5.4)."""

CATEGORY_OF_NATURA: t.Final[t.Mapping[Natura, VatCategory]] = types.MappingProxyType(
    {
        Natura.N1: VatCategory.ZERO_RATED,
        Natura.N2_1: VatCategory.EXEMPT,
        Natura.N2_2: VatCategory.EXEMPT,
        Natura.N3_1: VatCategory.EXPORT_OUTSIDE_EU,
        Natura.N3_2: VatCategory.INTRA_COMMUNITY_SUPPLY,
        Natura.N3_3: VatCategory.EXPORT_OUTSIDE_EU,
        Natura.N3_4: VatCategory.EXPORT_OUTSIDE_EU,
        Natura.N3_5: VatCategory.EXPORT_OUTSIDE_EU,
        Natura.N3_6: VatCategory.INTRA_COMMUNITY_SUPPLY,
        Natura.N4: VatCategory.EXEMPT,
        Natura.N5: VatCategory.EXEMPT,
        Natura.N6_1: VatCategory.REVERSE_CHARGE,
        Natura.N6_2: VatCategory.REVERSE_CHARGE,
        Natura.N6_3: VatCategory.REVERSE_CHARGE,
        Natura.N6_4: VatCategory.REVERSE_CHARGE,
        Natura.N6_5: VatCategory.REVERSE_CHARGE,
        Natura.N6_6: VatCategory.REVERSE_CHARGE,
        Natura.N6_7: VatCategory.REVERSE_CHARGE,
        Natura.N6_8: VatCategory.REVERSE_CHARGE,
        Natura.N6_9: VatCategory.REVERSE_CHARGE,
        Natura.N7: VatCategory.INTRA_COMMUNITY_SUPPLY,
    }
)
"""App. 5.1, first table (domestic invoices): the VAT category BT-118 of each Natura. The generic N2, N3 and N6 are
not in it (SdI 00445 refuses them since 2021)."""

_132: t.Final = "VATEX-EU-132"
_AE: t.Final = "VATEX-EU-AE"
VATEX_OF_NATURA: t.Final[t.Mapping[Natura, str]] = types.MappingProxyType(
    {
        Natura.N2_1: _132,
        Natura.N2_2: _132,
        Natura.N3_1: "VATEX-EU-G",
        Natura.N3_2: "VATEX-EU-IC",
        Natura.N3_3: "VATEX-EU-G",
        Natura.N3_4: "VATEX-EU-G",
        Natura.N3_5: "VATEX-EU-G",
        Natura.N3_6: "VATEX-EU-IC",
        Natura.N4: _132,
        Natura.N5: _132,
        Natura.N6_1: _AE,
        Natura.N6_2: _AE,
        Natura.N6_3: _AE,
        Natura.N6_4: _AE,
        Natura.N6_5: _AE,
        Natura.N6_6: _AE,
        Natura.N6_7: _AE,
        Natura.N6_8: _AE,
        Natura.N6_9: _AE,
        Natura.N7: "VATEX-EU-151",
    }
)
"""App. 5.1, first table: the VAT exemption reason code BT-121 of each Natura (``vatex-eu-…``, upper-cased as the model
stores it). N1 (category Z) has none."""

CHARGEABILITY_OF_VAT_POINT: t.Final[t.Mapping[str, EsigibilitaIVA]] = types.MappingProxyType(
    {"3": EsigibilitaIVA.I, "35": EsigibilitaIVA.I, "432": EsigibilitaIVA.D}
)
"""App. 4.1, row 2.2.2.7: EsigibilitaIVA from the VAT point date code BT-8 ("Se BT-8 = 3 allora I", 35 → I,
432 → D). Category B gives S instead (same row)."""

_MP: t.Final = ModalitaPagamento
PAYMENT_METHOD_OF_MEANS: t.Final[t.Mapping[str, ModalitaPagamento]] = types.MappingProxyType(
    {
        "1": _MP.MP01, "2": _MP.MP19, "3": _MP.MP19, "4": _MP.MP19, "5": _MP.MP19, "6": _MP.MP19, "7": _MP.MP19,
        "8": _MP.MP12, "9": _MP.MP23, "10": _MP.MP01, "11": _MP.MP19, "12": _MP.MP19, "13": _MP.MP19,
        "14": _MP.MP19, "15": _MP.MP05, "16": _MP.MP05, "17": _MP.MP01, "18": _MP.MP01, "19": _MP.MP01,
        "20": _MP.MP02, "21": _MP.MP03, "22": _MP.MP03, "23": _MP.MP03, "24": _MP.MP13, "25": _MP.MP02,
        "26": _MP.MP02, "27": _MP.MP01, "28": _MP.MP01, "29": _MP.MP01, "30": _MP.MP05, "31": _MP.MP13,
        "32": _MP.MP01, "33": _MP.MP01, "34": _MP.MP01, "35": _MP.MP01, "36": _MP.MP01, "37": _MP.MP01,
        "38": _MP.MP01, "39": _MP.MP01, "40": _MP.MP01, "41": _MP.MP01, "42": _MP.MP17, "43": _MP.MP01,
        "44": _MP.MP12, "45": _MP.MP05, "46": _MP.MP19, "47": _MP.MP19, "48": _MP.MP08, "49": _MP.MP19,
        "50": _MP.MP18, "51": _MP.MP05, "52": _MP.MP01, "53": _MP.MP01, "54": _MP.MP08, "55": _MP.MP08,
        "56": _MP.MP05, "57": _MP.MP15, "58": _MP.MP05, "59": _MP.MP19, "60": _MP.MP06, "61": _MP.MP06,
        "62": _MP.MP06, "63": _MP.MP06, "64": _MP.MP06, "65": _MP.MP06, "66": _MP.MP06, "67": _MP.MP06,
        "68": _MP.MP05, "70": _MP.MP12, "74": _MP.MP13, "75": _MP.MP13, "76": _MP.MP13, "77": _MP.MP13,
        "78": _MP.MP13, "91": _MP.MP03, "92": _MP.MP02, "93": _MP.MP05, "94": _MP.MP05, "95": _MP.MP05,
        "96": _MP.MP01, "97": _MP.MP22, "ZZZ": _MP.MP04,
    }
)  # fmt: skip
"""App. 5.6: ModalitaPagamento from the payment means type code BT-81, many to one. Codes 69 and 98 of the UNTDID 4461
list (BR-CL-16) have no row."""
