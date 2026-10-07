"""Recognizing a signed FatturaPA file (``.xml.p7m``, CAdES), which the reader refuses (#120).

A CAdES-BES envelope is a CMS ``SignedData`` (RFC 5652 §5.1, content type ``id-signedData``, OID
1.2.840.113549.1.7.2) in DER, often transmitted base64-encoded. Reading the XML out of it needs an ASN.1 / CMS
parser, which neither the standard library nor the runtime dependencies (D6) provide, and v1 is unsigned (#115
decision 1). So such input is refused with a message naming the way out, instead of failing as malformed XML.
"""

import base64
import binascii
import typing as t

__all__ = ["is_signed"]

# DER of the OID 1.2.840.113549.1.7.2 (id-signedData, RFC 5652 §5.1): tag 06, length 09, then the encoded arcs.
_SIGNED_DATA: t.Final = bytes.fromhex("06092a864886f70d010702")
_WINDOW: t.Final = 64  # the content type follows the outer SEQUENCE header within the first bytes of ContentInfo
_BASE64_WINDOW: t.Final = 88  # base64 text of (at least) the first 64 bytes, a multiple of 4
_WHITESPACE: t.Final = b" \t\r\n"


def is_signed(data: bytes) -> bool:
    """Whether ``data`` looks like a CMS ``SignedData`` envelope, in DER or base64.

    Args:
        data: The input bytes.

    Returns:
        ``True`` when the ``id-signedData`` content type appears in the first bytes of a DER ``SEQUENCE`` (or of its
        base64 text); ``False`` otherwise, e.g. for XML.
    """
    head = data.lstrip(_WHITESPACE)
    if head[:1] == b"\x30":  # DER SEQUENCE: ContentInfo
        return _SIGNED_DATA in head[:_WINDOW]
    if head[:2] == b"MI":  # base64 of 0x30 0x8x: a long-form DER SEQUENCE
        text = b"".join(head[: _BASE64_WINDOW * 2].split())[:_BASE64_WINDOW]
        try:
            return _SIGNED_DATA in base64.b64decode(text, validate=True)[:_WINDOW]
        except binascii.Error:
            return False
    return False
