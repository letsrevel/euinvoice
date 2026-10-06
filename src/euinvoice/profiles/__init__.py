"""Profiles (EN 16931 core, CIUSes, extensions) and their registry, looked up by BT-24 (D5).

Example:
    >>> from euinvoice import profiles
    >>> profiles.get("urn:cen.eu:en16931:2017") is profiles.EN16931
    True
"""

from euinvoice.profiles._base import Preflight, Profile, no_preflight
from euinvoice.profiles.en16931 import EN16931
from euinvoice.profiles.peppol import PEPPOL
from euinvoice.profiles.registry import get
from euinvoice.profiles.xrechnung import XRECHNUNG, XRECHNUNG_CVD, XRECHNUNG_EXTENSION

__all__ = [
    "EN16931",
    "PEPPOL",
    "XRECHNUNG",
    "XRECHNUNG_CVD",
    "XRECHNUNG_EXTENSION",
    "Preflight",
    "Profile",
    "get",
    "no_preflight",
]
