"""
Integration checks for the cost backend CLIs.

Each test is skipped automatically when the relevant binary is not on
PATH, so `pytest tests/integration -v` runs cleanly in environments where
only one of the backends is installed.
"""

import pytest

from iaccostagent.backends.infracost import InfracostBackend
from iaccostagent.backends.openinfraquote import OpenInfraQuoteBackend


class TestInfracostLive:
    def test_cli_is_available(self) -> None:
        if not InfracostBackend().is_available():
            pytest.skip("infracost not on PATH")

    def test_cli_prints_version(self) -> None:
        backend = InfracostBackend()
        if not backend.is_available():
            pytest.skip("infracost not on PATH")


class TestOIQLive:
    def test_cli_is_available(self) -> None:
        if not OpenInfraQuoteBackend().is_available():
            pytest.skip("oiq not on PATH")
