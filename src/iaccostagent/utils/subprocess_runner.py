"""
Safe subprocess execution helper for wrapping external cost-estimation CLIs.

Always uses shell=False and a list of arguments, never a single string.
Captures stdout/stderr as text, enforces a timeout, raises a descriptive
error when the binary is missing from PATH.
"""

import shutil
import subprocess
from dataclasses import dataclass


class BinaryNotFoundError(RuntimeError):
    """Raised when a required external binary is not on PATH."""


class SubprocessError(RuntimeError):
    """Raised when a subprocess exits non-zero or times out."""


@dataclass
class SubprocessResult:
    """Captured stdout, stderr, and exit code of a completed subprocess."""

    stdout: str
    stderr: str
    returncode: int


def check_binary(name: str) -> str:
    """
    Resolve a binary name to its absolute path on PATH.

    Raises BinaryNotFoundError if not found.
    """
    resolved = shutil.which(name)
    if not resolved:
        raise BinaryNotFoundError(f"Required binary '{name}' not found on PATH")
    return resolved


def run(
    args: list[str],
    *,
    cwd: str | None = None,
    env: dict | None = None,
    timeout: int = 120,
    input_text: str | None = None,
) -> SubprocessResult:
    """
    Execute a subprocess safely.

    Args:
        args: Command as a list (first element is the binary).
        cwd: Working directory.
        env: Environment override. If None, inherits current env.
        timeout: Seconds before SIGKILL. Default 120.
        input_text: Optional stdin payload.

    Returns:
        SubprocessResult with stdout/stderr/returncode.

    Raises:
        BinaryNotFoundError: If args[0] is not on PATH.
        SubprocessError: On non-zero exit or timeout.
    """
    if not args:
        raise ValueError("args must be non-empty")

    check_binary(args[0])

    try:
        completed = subprocess.run(
            args,
            cwd=cwd,
            env=env,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as e:
        raise SubprocessError(f"{args[0]} timed out after {timeout}s") from e

    if completed.returncode != 0:
        raise SubprocessError(f"{args[0]} exited with code {completed.returncode}: {completed.stderr.strip()}")

    return SubprocessResult(
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
    )
