"""doctorkit - health-check engine for CLI tools.

Public API::

    from doctorkit import Doctor, CheckResult, CheckInfo

Internal modules (prefixed with ``_``) are private implementation details
and should not be imported directly by consumers of the library.
"""

from ._doctor import Doctor
from ._types import CheckInfo, CheckRecord, CheckResult, FixResult, RunResult, RunSummary

__version__ = "0.1.0"

__all__ = [
    "Doctor",
    "CheckResult",
    "FixResult",
    "CheckInfo",
    "CheckRecord",
    "RunSummary",
    "RunResult",
    "__version__",
]
