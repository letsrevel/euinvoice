"""The BT-120 format shared by the FatturaPA reader and writer (#137, #132)."""

from euinvoice.model.it import Natura
from euinvoice.syntax.fatturapa._exemption import exemption_reason


def test_natura_and_legal_reference_joined_by_a_space_summaries_by_a_semicolon() -> None:
    reason = exemption_reason([(Natura.N2_2, "Art. 7 DPR 633/72"), (Natura.N4, None)])

    assert reason == "N2.2 Art. 7 DPR 633/72; N4"


def test_a_repeated_text_is_written_once() -> None:
    assert exemption_reason([(Natura.N4, None), (Natura.N4, None)]) == "N4"
