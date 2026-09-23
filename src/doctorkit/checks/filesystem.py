"""doctorkit.checks.filesystem - file and directory check factories."""
from __future__ import annotations

import os
import shutil
from typing import Callable, Optional

from .._types import CheckResult


def dir_exists_check(path: str) -> Callable[[], CheckResult]:
    """Return a check function that verifies *path* is an existing directory."""
    def _check() -> CheckResult:
        if os.path.isdir(path):
            return CheckResult(status="ok", message=f"{path} exists")
        if os.path.exists(path):
            return CheckResult(
                status="fail",
                message=f"{path} exists but is not a directory",
            )
        return CheckResult(
            status="fail",
            message=f"{path} does not exist",
            hint=f"Run: mkdir -p {path}",
        )

    return _check


def file_exists_check(path: str) -> Callable[[], CheckResult]:
    """Return a check function that verifies *path* is an existing file."""
    def _check() -> CheckResult:
        if os.path.isfile(path):
            return CheckResult(status="ok", message=f"{path} exists")
        if os.path.exists(path):
            return CheckResult(
                status="fail",
                message=f"{path} exists but is not a file",
            )
        return CheckResult(
            status="fail",
            message=f"{path} not found",
        )

    return _check


def writable_check(path: str) -> Callable[[], CheckResult]:
    """Return a check function that verifies *path* is writable by the current user."""
    def _check() -> CheckResult:
        if not os.path.exists(path):
            return CheckResult(
                status="fail",
                message=f"{path} does not exist",
                hint=f"Run: mkdir -p {path}",
            )
        if os.access(path, os.W_OK):
            return CheckResult(status="ok", message=f"{path} is writable")
        return CheckResult(
            status="fail",
            message=f"{path} is not writable",
            hint=f"Run: chmod u+w {path}",
        )

    return _check


def disk_space_check(
    path: Optional[str] = None,
    *,
    min_free_gb: float = 1.0,
) -> Callable[[], CheckResult]:
    """Return a check function that verifies free disk space at *path*.

    *path* defaults to the user's home directory. Fails when the free space
    available to the current user is below *min_free_gb* (default 1 GB).
    """
    def _check() -> CheckResult:
        target = path if path is not None else os.path.expanduser("~")
        try:
            free_gb = shutil.disk_usage(target).free / 1024 ** 3
        except OSError as exc:
            return CheckResult(
                status="fail",
                message=f"Cannot check disk space at {target}: {exc}",
            )
        if free_gb < min_free_gb:
            return CheckResult(
                status="fail",
                message=f"{target}: {free_gb:.1f} GB free (minimum {min_free_gb:g} GB required)",
                hint=f"Free up disk space on the volume containing {target}",
            )
        return CheckResult(status="ok", message=f"{target}: {free_gb:.1f} GB free")

    return _check
