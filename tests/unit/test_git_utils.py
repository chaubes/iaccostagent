"""Unit tests for the git URL helpers."""

from pathlib import Path
from unittest.mock import patch

import pytest

from iaccostagent.utils.git import GitError, fetch_source, is_git_url, shallow_clone


class TestIsGitUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/user/repo.git",
            "https://github.com/user/repo",
            "http://gitlab.example.com/team/project.git",
            "git@github.com:user/repo.git",
            "ssh://git@github.com/user/repo",
            "git://github.com/user/repo",
        ],
    )
    def test_recognizes_git_url(self, url: str) -> None:
        assert is_git_url(url) is True

    @pytest.mark.parametrize(
        "path",
        [
            "/tmp/local/path",
            "./infrastructure",
            "plan.json",
            "tests/fixtures/terraform/simple_web_app",
        ],
    )
    def test_recognizes_local_path(self, path: str) -> None:
        assert is_git_url(path) is False


class TestShallowClone:
    def test_git_missing_raises_clear_error(self, tmp_path: Path) -> None:
        with patch(
            "subprocess.run",
            side_effect=FileNotFoundError(2, "No such file or directory: 'git'"),
        ):
            with pytest.raises(GitError, match="git is not installed"):
                shallow_clone("https://example.com/foo.git", target_dir=tmp_path / "clone")

    def test_clone_failure_cleans_up_and_raises(self, tmp_path: Path) -> None:
        import subprocess

        target = tmp_path / "clone"

        def _fake_run(args, **kwargs):  # type: ignore[no-untyped-def]
            target.mkdir(parents=True, exist_ok=True)
            raise subprocess.CalledProcessError(returncode=128, cmd=args, stderr="fatal: repository not found")

        with patch("subprocess.run", side_effect=_fake_run):
            with pytest.raises(GitError, match="repository not found"):
                shallow_clone("https://example.com/missing.git", target_dir=target)

        assert not target.exists(), "Failed clone should remove the partial target dir"


class TestFetchSource:
    def test_local_path_yields_unchanged(self, tmp_path: Path) -> None:
        (tmp_path / "main.tf").write_text("# empty")
        with fetch_source(str(tmp_path)) as (resolved, cloned):
            assert resolved == tmp_path
            assert cloned is None

    def test_local_path_with_subdir(self, tmp_path: Path) -> None:
        sub = tmp_path / "infrastructure"
        sub.mkdir()
        (sub / "main.tf").write_text("# empty")
        with fetch_source(str(tmp_path), subdir="infrastructure") as (resolved, cloned):
            assert resolved == sub
            assert cloned is None

    def test_missing_subdir_raises(self, tmp_path: Path) -> None:
        with pytest.raises(GitError, match="Subdirectory 'missing'"):
            with fetch_source(str(tmp_path), subdir="missing"):
                pass

    def test_git_url_clones_then_cleans_up(self, tmp_path: Path) -> None:
        fake_clone = tmp_path / "fake-clone"
        fake_clone.mkdir()
        (fake_clone / "main.tf").write_text("# cloned")

        with patch("iaccostagent.utils.git.shallow_clone", return_value=fake_clone):
            with fetch_source("https://example.com/repo.git") as (resolved, cloned):
                assert resolved == fake_clone
                assert cloned == fake_clone
                assert fake_clone.exists()

        assert not fake_clone.exists(), "Clone should be removed after context exits"
