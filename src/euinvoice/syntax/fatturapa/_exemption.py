"""BT-120 from FatturaPA ``Natura`` and ``RiferimentoNormativo``: the one format the reader and the writer share (#137).

App. 4.1 of the SdI "Regole tecniche fatture europee" v2.6, rows 2.2.2.2 and 2.2.2.8: "In BT-120 vengono concatenati
2.2.2.2 <Natura> e 2.2.2.8 <RiferimentoNormativo>". App. 4.1 gives no separator. The ones used here are a policy
choice listed in https://github.com/letsrevel/euinvoice/issues/132, so a decision there changes only this module.
"""

import typing as t

from euinvoice.model.it import Natura

__all__ = ["exemption_reason"]


def exemption_reason(summaries: t.Iterable[tuple[Natura, str | None]]) -> str:
    """BT-120 of one VAT BREAKDOWN (BG-23) made of the given ``DatiRiepilogo``.

    Each summary gives its ``Natura``, followed by its ``RiferimentoNormativo`` after a space when it has one. The
    summaries are joined by ``"; "``, and a text that repeats an earlier one is left out.

    Args:
        summaries: ``(Natura, RiferimentoNormativo or None)`` of each summary, in document order.

    Returns:
        The BT-120 text.
    """
    texts = (str(nature) if legal is None else f"{nature} {legal}" for nature, legal in summaries)
    return "; ".join(dict.fromkeys(texts))
