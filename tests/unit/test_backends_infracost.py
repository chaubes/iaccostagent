"""Unit tests for the Infracost backend wrapper (subprocess monkey-patched)."""

from pathlib import Path
from unittest.mock import patch

import pytest

from iaccostagent.backends.infracost import InfracostBackend
from iaccostagent.utils.subprocess_runner import SubprocessResult


class TestInfracostBackendParsing:
    def setup_method(self) -> None:
        self.backend = InfracostBackend()

    async def test_parses_recorded_output(self, infracost_output_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        stdout = infracost_output_path.read_text()
        monkeypatch.setenv("INFRACOST_API_KEY", "ico-test-key")

        with (
            patch(
                "iaccostagent.backends.infracost.check_binary",
                return_value="/usr/local/bin/infracost",
            ),
            patch(
                "iaccostagent.backends.infracost.run",
                return_value=SubprocessResult(stdout=stdout, stderr="", returncode=0),
            ),
        ):
            estimate = await self.backend.estimate("/fake/path", region="us-east-1")

        assert estimate.backend == "infracost"
        assert estimate.currency == "USD"
        assert estimate.total_monthly_cost == pytest.approx(1235.41)
        assert estimate.region == "us-east-1"
        assert len(estimate.resource_costs) == 3
        db = next(rc for rc in estimate.resource_costs if rc.resource.resource_type == "aws_db_instance")
        assert db.monthly_cost == pytest.approx(1152.40)
        assert db.percentage_of_total > 90.0  # DB dominates in this fixture

    async def test_missing_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("INFRACOST_API_KEY", raising=False)
        with patch(
            "iaccostagent.backends.infracost.check_binary",
            return_value="/usr/local/bin/infracost",
        ):
            with pytest.raises(RuntimeError, match="INFRACOST_API_KEY"):
                await self.backend.estimate("/fake/path")

    def test_is_available_false_when_missing(self) -> None:
        from iaccostagent.utils.subprocess_runner import BinaryNotFoundError

        with patch(
            "iaccostagent.backends.infracost.check_binary",
            side_effect=BinaryNotFoundError("infracost"),
        ):
            assert self.backend.is_available() is False
