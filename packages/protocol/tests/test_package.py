from importlib.metadata import version

import tamforge_protocol


def test_protocol_package_imports_with_expected_version() -> None:
    assert tamforge_protocol.__version__ == "0.1.0"
    assert version("tamforge-protocol") == "0.1.0"
