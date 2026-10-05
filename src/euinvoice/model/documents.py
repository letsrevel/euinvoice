"""EN 16931 ADDITIONAL SUPPORTING DOCUMENTS (BG-24), including the attached document (BT-125)."""

import typing as t

from euinvoice.model._base import EuInvoiceModel, bt
from euinvoice.model.datatypes import BinaryObject, NonBlankText, Text

__all__ = ["AdditionalSupportingDocument"]


class AdditionalSupportingDocument(EuInvoiceModel):
    """ADDITIONAL SUPPORTING DOCUMENTS (BG-24)."""

    reference: t.Annotated[NonBlankText, bt("BT-122")]
    """Supporting document reference (BR-52)."""
    description: t.Annotated[Text | None, bt("BT-123")] = None
    """Supporting document description."""
    external_location: t.Annotated[Text | None, bt("BT-124")] = None
    """External document location (a URL)."""
    attached_document: t.Annotated[BinaryObject | None, bt("BT-125")] = None
    """Attached document with its MIME code (BR-CL-24) and filename."""
