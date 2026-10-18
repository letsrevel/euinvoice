import pathlib
import tomllib

import euinvoice


def test_version_is_exposed() -> None:
    pyproject = pathlib.Path(__file__).resolve().parent.parent / "pyproject.toml"
    expected = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    assert euinvoice.__version__ == expected
