"""Italian extension of the model: FatturaPA data with no EN 16931 business term (D3 as amended, ADR 0001).

:class:`ItalianExtension` hangs on ``Invoice.it`` (and ``InvoiceDraft.it``), :class:`ItalianLineExtension` on
``InvoiceLine.it`` (and ``LineDraft.it``). Their fields cite FatturaPA element ids instead of BTs
(:func:`fatturapa_id`); :mod:`euinvoice.model.bt_index` skips them. UBL and CII have no place for them, so their
writers refuse an invoice that sets one (plan §1, "never silently dropped").
"""

from euinvoice.model.it.codes import (
    CondizioniPagamento,
    EsigibilitaIVA,
    ModalitaPagamento,
    Natura,
    RegimeFiscale,
    SoggettoEmittente,
    TipoCessionePrestazione,
    TipoDocumento,
)
from euinvoice.model.it.extension import (
    ItalianExtension,
    ItalianLineExtension,
    ItalianPayment,
    ItalianVatSummary,
    fatturapa_id,
)

__all__ = [
    "CondizioniPagamento",
    "EsigibilitaIVA",
    "ItalianExtension",
    "ItalianLineExtension",
    "ItalianPayment",
    "ItalianVatSummary",
    "ModalitaPagamento",
    "Natura",
    "RegimeFiscale",
    "SoggettoEmittente",
    "TipoCessionePrestazione",
    "TipoDocumento",
    "fatturapa_id",
]
