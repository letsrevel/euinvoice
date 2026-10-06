import pickle  # ruff: ignore[suspicious-pickle-import] - round-trips our own exception

import pydantic
import pytest

from euinvoice import errors, profiles


@pytest.mark.parametrize(
    "exc_type",
    [
        errors.ModelError,
        errors.ParseError,
        errors.UnsupportedDocumentError,
        errors.ArtifactsNotAvailableError,
        errors.ArtifactIntegrityError,
        errors.PdfError,
    ],
)
def test_every_error_derives_from_the_base(exc_type: type[Exception]) -> None:
    assert issubclass(exc_type, errors.EuInvoiceError)
    assert issubclass(errors.EuInvoiceError, Exception)


def test_model_error_is_a_value_error() -> None:
    assert issubclass(errors.ModelError, ValueError)


def test_model_error_raised_in_a_validator_surfaces_as_validation_error() -> None:
    class M(pydantic.BaseModel):
        x: int

        @pydantic.field_validator("x")
        @classmethod
        def _boom(cls, value: int) -> int:
            raise errors.ModelError("BT-1 broken")

    with pytest.raises(pydantic.ValidationError, match="BT-1 broken"):
        M(x=1)


def test_parse_error_without_location() -> None:
    err = errors.ParseError("DOCTYPE is forbidden")
    assert err.location is None
    assert str(err) == "DOCTYPE is forbidden"


def test_parse_error_with_location() -> None:
    err = errors.ParseError("unexpected element", location="/Invoice/cbc:Foo")
    assert err.location == "/Invoice/cbc:Foo"
    assert str(err) == "unexpected element (at /Invoice/cbc:Foo)"


def test_parse_error_location_is_keyword_only() -> None:
    with pytest.raises(TypeError):
        errors.ParseError("msg", "3:7")  # type: ignore[call-arg]  # positional location must be refused


def test_artifacts_not_available_without_fallback() -> None:
    err = errors.ArtifactsNotAvailableError("cen-ubl is missing; run: python -m euinvoice artifacts fetch")
    assert err.fallback_profile_id is None
    assert err.reason == str(err) == "cen-ubl is missing; run: python -m euinvoice artifacts fetch"


def test_artifacts_not_available_with_fallback_appends_the_python_hint() -> None:
    err = errors.ArtifactsNotAvailableError("rules not pinned", fallback_profile_id="en16931")
    assert err.fallback_profile_id == "en16931"
    assert err.reason == "rules not pinned"
    assert str(err) == "rules not pinned. To run only the EN 16931 core rules, pass profile=euinvoice.profiles.EN16931"


@pytest.mark.parametrize(
    "profile",
    [p for name in profiles.__all__ if isinstance(p := getattr(profiles, name), profiles.Profile)],
    ids=lambda p: p.id,
)
def test_artifacts_not_available_hint_names_the_exported_profile_constant(profile: profiles.Profile) -> None:
    # The hint derives the constant from the id (hyphens become underscores); every exported profile keeps that rule.
    constant = profile.id.upper().replace("-", "_")
    assert getattr(profiles, constant) is profile
    err = errors.ArtifactsNotAvailableError("rules not pinned", fallback_profile_id=profile.id)
    assert str(err).endswith(f", pass profile=euinvoice.profiles.{constant}")


def test_artifacts_not_available_keeps_its_fallback_through_pickle() -> None:
    err = errors.ArtifactsNotAvailableError("rules not pinned", fallback_profile_id="en16931")
    copy = pickle.loads(pickle.dumps(err))  # ruff: ignore[suspicious-pickle-usage] - our own object
    assert (str(copy), copy.reason, copy.fallback_profile_id) == (str(err), err.reason, err.fallback_profile_id)
