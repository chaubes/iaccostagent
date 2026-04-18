"""Shared pytest fixtures for IaCCostAgent tests."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Root directory for all test fixtures."""
    return FIXTURES_DIR


@pytest.fixture
def terraform_fixtures_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "terraform"


@pytest.fixture
def plan_json_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "plan_json" / "sample_plan.json"


@pytest.fixture
def infracost_output_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "cost_output" / "infracost_simple.json"


@pytest.fixture
def oiq_output_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "cost_output" / "oiq_simple.json"
