import euinvoice


def test_version_is_exposed() -> None:
    assert euinvoice.__version__ == "0.2.0"
