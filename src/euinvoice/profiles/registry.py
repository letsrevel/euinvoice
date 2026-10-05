"""The profile registry: every supported profile, looked up by its specification identifier (BT-24).

To add a profile, define it in its own module, append it to ``_PROFILES`` below and re-export it from
:mod:`euinvoice.profiles`.
"""

import typing as t
from collections.abc import Iterable, Mapping

from euinvoice.errors import UnsupportedDocumentError
from euinvoice.profiles._base import Profile
from euinvoice.profiles.en16931 import EN16931

__all__ = ["get"]


def _index(profiles: Iterable[Profile]) -> dict[str, Profile]:
    """Key ``profiles`` by their BT-24 value.

    Raises:
        ValueError: Two profiles declare the same BT-24.
    """
    index: dict[str, Profile] = {}
    for profile in profiles:
        if (other := index.get(profile.specification_identifier)) is not None:
            raise ValueError(
                f"profiles {other.id!r} and {profile.id!r} share BT-24 {profile.specification_identifier!r}"
            )
        index[profile.specification_identifier] = profile
    return index


# ponytail: one profile per BT-24. Factur-X EN16931 and XRECHNUNG reuse the BT-24 of EN 16931 core and
# XRechnung (plan §5), so the PDF container, not BT-24, must pick them; #22 extends the lookup for that.
_PROFILES: t.Final = (EN16931,)
_BY_BT24: t.Final[Mapping[str, Profile]] = _index(_PROFILES)


def get(specification_identifier: str) -> Profile:
    """Return the profile whose specification identifier (BT-24) is ``specification_identifier``.

    The match is exact: a CIUS identifier such as ``urn:cen.eu:en16931:2017#compliant#...`` never
    resolves to the core profile.

    Args:
        specification_identifier: A BT-24 value.

    Returns:
        The registered profile.

    Raises:
        UnsupportedDocumentError: No registered profile has this BT-24; the message lists the known ones.
    """
    try:
        return _BY_BT24[specification_identifier]
    except KeyError:
        known = ", ".join(sorted(_BY_BT24))
        raise UnsupportedDocumentError(
            f"unsupported specification identifier (BT-24) {specification_identifier!r}; known: {known}"
        ) from None
