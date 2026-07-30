"""doctorkit.checks.env - environment variable check factories."""
from __future__ import annotations

import os
import re
from typing import Callable, List, Optional

from .._types import CheckResult


def env_check(
    name: str,
    *,
    pattern: Optional[str] = None,
    hint: Optional[str] = None,
) -> Callable[[], CheckResult]:
    """Return a check function that verifies *name* is set in the environment.

    If *pattern* is given (regex), the value must also match it.
    """
    def _check() -> CheckResult:
        value = os.environ.get(name)
        if value is None:
            return CheckResult(
                status="fail",
                message=f"{name} is not set",
                hint=hint or f"Run: export {name}=<value>",
            )
        if pattern and not re.fullmatch(pattern, value):
            return CheckResult(
                status="fail",
                message=f"{name} does not match expected format",
                hint=hint or f"Expected pattern: {pattern}",
            )
        return CheckResult(status="ok", message=f"{name} is set")

    return _check


def envfile_vars_check(
    example_path: str = ".env.example",
    *,
    env_file: str = ".env",
) -> Callable[[], CheckResult]:
    """Return a check that verifies every variable declared in *example_path* is defined.

    A variable is considered defined if it appears in *env_file* OR is already
    set in the current process environment.  Comment lines and blank lines are ignored.
    """
    def _check() -> CheckResult:
        try:
            example_text = open(example_path, encoding="utf-8", errors="ignore").read()
        except FileNotFoundError:
            return CheckResult(
                status="fail",
                message=f"{example_path} not found",
                hint=f"Create {example_path} listing the required variable names",
            )

        required: List[str] = []
        for line in example_text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name = line.split("=")[0].strip()
            if name:
                required.append(name)

        if not required:
            return CheckResult(status="ok", message=f"{example_path} has no variables")

        defined: set = set()
        if os.path.exists(env_file):
            env_text = open(env_file, encoding="utf-8", errors="ignore").read()
            for line in env_text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                name = line.split("=")[0].strip()
                if name:
                    defined.add(name)

        missing = [n for n in required if n not in defined and n not in os.environ]

        if missing:
            return CheckResult(
                status="fail",
                message=f"{len(missing)} variable(s) missing: {', '.join(missing)}",
                hint=f"Add the missing variables to {env_file}",
            )
        return CheckResult(
            status="ok",
            message=f"all {len(required)} variable(s) from {example_path} are set",
        )

    return _check


def envfile_check(path: str = ".env") -> Callable[[], CheckResult]:
    """Return a check function that verifies *path* exists and is readable."""
    def _check() -> CheckResult:
        try:
            with open(path):
                pass
            return CheckResult(status="ok", message=f"{path} found and readable")
        except FileNotFoundError:
            return CheckResult(
                status="fail",
                message=f"{path} not found",
                hint=f"Copy .env.example to {path} and fill in the values",
            )
        except PermissionError:
            return CheckResult(
                status="fail",
                message=f"{path} is not readable",
                hint=f"Run: chmod 600 {path}",
            )

    return _check
