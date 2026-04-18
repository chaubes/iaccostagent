"""Unit tests for the CLI pre-flight checks and --verify flag."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from iaccostagent.cli.app import app
from iaccostagent.utils.subprocess_runner import SubprocessResult

runner = CliRunner()


@pytest.fixture(autouse=True)
def _no_dotenv():
    """Disable .env auto-loading so tests don't pick up the local .env file."""
    with patch("iaccostagent.cli.app.load_dotenv"):
        yield


def _stub_backend(*, is_available: bool = True, estimate_raises: Exception | None = None) -> MagicMock:
    """Build a MagicMock backend with the given availability / estimate behavior."""
    inst = MagicMock()
    inst.is_available.return_value = is_available
    if estimate_raises is not None:
        inst.estimate.side_effect = estimate_raises
    return inst


def _patch_registry(backend_mock: MagicMock):
    """Patch iaccostagent.cli.app.get_backend to return `backend_mock`."""
    return patch("iaccostagent.cli.app.get_backend", return_value=backend_mock)


class TestAnalyzePreflight:
    def test_analyze_exits_early_when_binary_missing(self) -> None:
        with _patch_registry(_stub_backend(is_available=False)):
            result = runner.invoke(app, ["analyze", "/tmp/anywhere", "--backend", "infracost"])
        assert result.exit_code == 1
        assert "not available" in result.stdout
        assert "brew install infracost" in result.stdout

    def test_analyze_exits_early_when_api_key_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("INFRACOST_API_KEY", raising=False)
        with _patch_registry(_stub_backend(is_available=True)):
            result = runner.invoke(app, ["analyze", "/tmp/anywhere", "--backend", "infracost"])
        assert result.exit_code == 1
        assert "INFRACOST_API_KEY is not set" in result.stdout

    def test_estimate_has_same_preflight(self) -> None:
        with _patch_registry(_stub_backend(is_available=False)):
            result = runner.invoke(app, ["estimate", "/tmp/anywhere"])
        assert result.exit_code == 1
        assert "not available" in result.stdout

    def test_diff_has_same_preflight(self) -> None:
        with _patch_registry(_stub_backend(is_available=False)):
            result = runner.invoke(app, ["diff", "/tmp/a", "/tmp/b"])
        assert result.exit_code == 1
        assert "not available" in result.stdout


class TestCheckBackend:
    def test_reports_missing_binary_with_install_hint(self) -> None:
        with _patch_registry(_stub_backend(is_available=False)):
            result = runner.invoke(app, ["check-backend", "--backend", "infracost"])
        assert result.exit_code == 1
        assert "NOT available" in result.stdout
        assert "brew install infracost" in result.stdout

    def test_reports_missing_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("INFRACOST_API_KEY", raising=False)
        with _patch_registry(_stub_backend(is_available=True)):
            result = runner.invoke(app, ["check-backend", "--backend", "infracost"])
        assert result.exit_code == 1
        assert "INFRACOST_API_KEY is not set" in result.stdout

    def test_reports_ready_when_all_green(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("INFRACOST_API_KEY", "ico-test")
        with _patch_registry(_stub_backend(is_available=True)):
            result = runner.invoke(app, ["check-backend", "--backend", "infracost"])
        assert result.exit_code == 0
        assert "is available" in result.stdout
        assert "INFRACOST_API_KEY is set" in result.stdout

    def test_unknown_backend_lists_registered(self) -> None:
        result = runner.invoke(app, ["check-backend", "--backend", "made-up"])
        assert result.exit_code == 1
        assert "Unknown backend" in result.stdout
        # Registered backends should be listed in the error message.
        assert "infracost" in result.stdout
        assert "azure-retail" in result.stdout


class TestReferenceBackendWarning:
    """Reference / extension-pattern backends must print a loud warning."""

    def test_warning_on_aws_pricing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("INFRACOST_API_KEY", "ico-test")
        with _patch_registry(_stub_backend(is_available=True)):
            result = runner.invoke(app, ["check-backend", "--backend", "aws-pricing"])
        combined = result.stdout + (result.stderr if result.stderr_bytes else "")
        assert "reference / extension-pattern backend" in combined
        assert "Use --backend infracost for production" in combined

    def test_warning_on_azure_retail(self) -> None:
        with _patch_registry(_stub_backend(is_available=True)):
            result = runner.invoke(app, ["check-backend", "--backend", "azure-retail"])
        combined = result.stdout + (result.stderr if result.stderr_bytes else "")
        assert "reference / extension-pattern backend" in combined

    def test_no_warning_on_infracost(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("INFRACOST_API_KEY", "ico-test")
        with _patch_registry(_stub_backend(is_available=True)):
            result = runner.invoke(app, ["check-backend", "--backend", "infracost"])
        combined = result.stdout + (result.stderr if result.stderr_bytes else "")
        assert "reference / extension-pattern" not in combined

    def test_warning_in_analyze_preflight(self) -> None:
        """analyze should warn before the pipeline starts, not after."""
        with _patch_registry(_stub_backend(is_available=True, estimate_raises=RuntimeError("stop"))):
            result = runner.invoke(app, ["analyze", "/tmp/anywhere", "--backend", "aws-pricing"])
        combined = result.stdout + (result.stderr if result.stderr_bytes else "")
        assert "reference / extension-pattern backend" in combined


class TestDiffSubdirFlags:
    """Verify --before-subdir / --after-subdir dispatch correctly."""

    def test_per_side_subdirs_override_shared_subdir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("INFRACOST_API_KEY", "ico-test")

        captured: dict = {}

        def _fake_resolve(path, *, subdir=None, verbose=False):
            from contextlib import contextmanager

            @contextmanager
            def _cm():
                captured.setdefault("calls", []).append((path, subdir))
                yield (tmp_path, None)

            return _cm()

        backend_mock = _stub_backend(is_available=True, estimate_raises=RuntimeError("stop here"))
        with (
            patch("iaccostagent.cli.app._resolve_path", side_effect=_fake_resolve),
            _patch_registry(backend_mock),
        ):
            runner.invoke(
                app,
                [
                    "diff",
                    "/tmp/a",
                    "/tmp/b",
                    "--subdir",
                    "ignored",
                    "--before-subdir",
                    "legacy_infra",
                    "--after-subdir",
                    "modern_terraform",
                ],
            )

        calls = captured.get("calls", [])
        assert len(calls) == 2
        assert calls[0][1] == "legacy_infra"
        assert calls[1][1] == "modern_terraform"

    def test_shared_subdir_applies_to_both_sides(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("INFRACOST_API_KEY", "ico-test")

        captured: dict = {}

        def _fake_resolve(path, *, subdir=None, verbose=False):
            from contextlib import contextmanager

            @contextmanager
            def _cm():
                captured.setdefault("calls", []).append((path, subdir))
                yield (tmp_path, None)

            return _cm()

        backend_mock = _stub_backend(is_available=True, estimate_raises=RuntimeError("stop here"))
        with (
            patch("iaccostagent.cli.app._resolve_path", side_effect=_fake_resolve),
            _patch_registry(backend_mock),
        ):
            runner.invoke(app, ["diff", "/tmp/a", "/tmp/b", "--subdir", "infrastructure"])

        calls = captured.get("calls", [])
        assert len(calls) == 2
        assert calls[0][1] == "infrastructure"
        assert calls[1][1] == "infrastructure"


class TestCheckBackendVerify:
    def test_verify_runs_backend_on_temp_fixture(
        self,
        monkeypatch: pytest.MonkeyPatch,
        infracost_output_path: Path,
    ) -> None:
        monkeypatch.setenv("INFRACOST_API_KEY", "ico-test")
        fake_stdout = infracost_output_path.read_text()

        with (
            patch(
                "iaccostagent.backends.infracost.check_binary",
                return_value="/usr/local/bin/infracost",
            ),
            patch(
                "iaccostagent.backends.infracost.run",
                return_value=SubprocessResult(stdout=fake_stdout, stderr="", returncode=0),
            ),
        ):
            result = runner.invoke(app, ["check-backend", "--backend", "infracost", "--verify"])

        assert result.exit_code == 0, result.stdout
        assert "end-to-end verification" in result.stdout
        assert "returned a valid estimate" in result.stdout
        assert "$1,235.41" in result.stdout

    def test_verify_reports_failure_on_backend_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("INFRACOST_API_KEY", "ico-test")

        from iaccostagent.utils.subprocess_runner import SubprocessError

        with (
            patch(
                "iaccostagent.backends.infracost.check_binary",
                return_value="/usr/local/bin/infracost",
            ),
            patch(
                "iaccostagent.backends.infracost.run",
                side_effect=SubprocessError("bad api key"),
            ),
        ):
            result = runner.invoke(app, ["check-backend", "--backend", "infracost", "--verify"])

        assert result.exit_code == 1
        assert "End-to-end verification failed" in result.stdout


class TestServeInstallHint:
    """The serve command's install hint must not be eaten by Rich markup."""

    def test_install_hint_mentions_server_extras(self) -> None:
        # Simulate the missing-extras branch by patching the import inside the
        # serve command. We monkeypatch sys.modules so `import uvicorn` fails.
        import sys

        saved_uvicorn = sys.modules.pop("uvicorn", None)
        sys.modules["uvicorn"] = None  # type: ignore[assignment]
        try:
            result = runner.invoke(app, ["serve", "--port", "8899"])
        finally:
            if saved_uvicorn is not None:
                sys.modules["uvicorn"] = saved_uvicorn
            else:
                sys.modules.pop("uvicorn", None)

        assert result.exit_code == 1
        # The literal string "[server]" must appear in the output — Rich
        # must not have eaten it as a markup tag.
        assert "[server]" in result.stdout
