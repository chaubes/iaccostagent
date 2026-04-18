"""Unit tests for the OpenInfraQuote backend wrapper."""

from pathlib import Path
from unittest.mock import patch

import pytest

from iaccostagent.backends.openinfraquote import OpenInfraQuoteBackend
from iaccostagent.utils.subprocess_runner import SubprocessResult


class TestOpenInfraQuoteBackendParsing:
    async def test_parses_recorded_output(
        self,
        plan_json_path: Path,
        oiq_output_path: Path,
        tmp_path: Path,
    ) -> None:
        pricesheet = tmp_path / "prices.csv"
        pricesheet.write_text("type,region,price\n")
        backend = OpenInfraQuoteBackend(pricesheet=str(pricesheet))

        match_stdout = '{"matches": []}'
        price_stdout = oiq_output_path.read_text()

        with (
            patch(
                "iaccostagent.backends.openinfraquote.check_binary",
                return_value="/usr/local/bin/oiq",
            ),
            patch(
                "iaccostagent.backends.openinfraquote.run",
                side_effect=[
                    SubprocessResult(stdout=match_stdout, stderr="", returncode=0),
                    SubprocessResult(stdout=price_stdout, stderr="", returncode=0),
                ],
            ),
        ):
            estimate = await backend.estimate(str(plan_json_path), region="us-east-1")

        assert estimate.backend == "openinfraquote"
        assert estimate.total_monthly_cost == pytest.approx(1235.41)
        assert len(estimate.resource_costs) == 3
        assert estimate.provider.value == "aws"

    async def test_requires_plan_json(self, tmp_path: Path) -> None:
        pricesheet = tmp_path / "prices.csv"
        pricesheet.write_text("x,y\n")
        backend = OpenInfraQuoteBackend(pricesheet=str(pricesheet))

        with patch(
            "iaccostagent.backends.openinfraquote.check_binary",
            return_value="/usr/local/bin/oiq",
        ):
            with pytest.raises(ValueError, match="plan JSON"):
                await backend.estimate("/fake/terraform/dir")

    async def test_missing_pricesheet_raises(self, plan_json_path: Path) -> None:
        backend = OpenInfraQuoteBackend(pricesheet=None)
        with patch(
            "iaccostagent.backends.openinfraquote.check_binary",
            return_value="/usr/local/bin/oiq",
        ):
            with pytest.raises(RuntimeError, match="pricesheet"):
                await backend.estimate(str(plan_json_path))
