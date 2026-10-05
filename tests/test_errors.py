import pydantic
import pytest

from euinvoice import errors


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
