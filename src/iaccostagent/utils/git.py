"""
Git helpers for fetching Terraform from remote repositories.

The CLI accepts a git URL in place of a local path. We shallow-clone the
repo to a temp directory, let the pipeline run against it, and clean up
afterwards. Keeping this logic in one place makes it easy to reuse across
analyze / estimate / diff.
"""

import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_GIT_URL_RE = re.compile(r"^(https?://|git@|git://|ssh://)")


class GitError(RuntimeError):
    """Raised when git is missing or a clone fails."""


def is_git_url(path: str) -> bool:
    """Heuristic: true if `path` looks like a git URL rather than a filesystem path."""
    if _GIT_URL_RE.match(path):
        return True
    return path.endswith(".git") and "/" in path


def shallow_clone(url: str, *, target_dir: Path | None = None) -> Path:
    """
    Clone `url` (depth=1) into a directory and return its path.

    Raises GitError if git is not installed or the clone fails.
    Callers are responsible for cleaning up the returned directory.
    """
    tmp = Path(target_dir) if target_dir else Path(tempfile.mkdtemp(prefix="iaccostagent-"))
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", url, str(tmp)],
            check=True,
            capture_output=True,
            text=True,
            shell=False,
        )
    except FileNotFoundError as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise GitError("git is not installed. Install git to analyze remote repositories.") from e
    except subprocess.CalledProcessError as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise GitError(f"git clone failed: {e.stderr.strip() or e.stdout.strip() or 'unknown error'}") from e
    return tmp


@contextmanager
def fetch_source(path: str, subdir: str | None = None) -> Iterator[tuple[Path, Path | None]]:
    """
    Resolve a local path or git URL into a usable filesystem path.

    Yields a tuple `(resolved_path, cloned_dir)`. `cloned_dir` is non-None
    only when we cloned a git URL; callers don't need to care about
    cleanup — this context manager handles rmtree on exit.

    If `subdir` is provided and the resolved path is a directory, we
    append it (useful for repos that keep Terraform under `infrastructure/`,
    `terraform/`, etc.).
    """
    cloned: Path | None = None
    try:
        if is_git_url(path):
            cloned = shallow_clone(path)
            resolved = cloned
        else:
            resolved = Path(path)

        if subdir:
            candidate = resolved / subdir
            if not candidate.exists():
                raise GitError(f"Subdirectory '{subdir}' not found in {resolved}")
            resolved = candidate

        yield resolved, cloned
    finally:
        if cloned is not None:
            shutil.rmtree(cloned, ignore_errors=True)
