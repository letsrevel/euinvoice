"""EN 16931 core: the European standard without a CIUS or extension, in UBL and CII."""

import typing as t

from euinvoice.profiles._base import Profile
from euinvoice.syntax import Syntax

__all__ = ["EN16931"]

EN16931: t.Final = Profile(
    id="en16931",
    title="EN 16931 (core)",
    # BT-24 as used by every core example of CEN validation-1.3.16: 15 UBL ``examples/*.xml``
    # (``cbc:CustomizationID``) and 12 CII ``examples/*.xml``
    # (``ram:GuidelineSpecifiedDocumentContextParameter/ram:ID``). The CEN Schematron fixes no value:
    # BR-01 (fatal, ``EN16931-model.sch``) only requires BT-24 to be non-empty.
    specification_identifier="urn:cen.eu:en16931:2017",
    syntaxes=frozenset(Syntax),
    # XSD, then the CEN rules only (rule sets per profile verified on issue #17).
    rule_sets=("cen",),
    # No BT-23 default: BT-23 is optional in EN 16931 and no CEN rule requires it.
)
"""The EN 16931 core profile, BT-24 ``urn:cen.eu:en16931:2017``."""
