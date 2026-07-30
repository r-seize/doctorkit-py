"""doctorkit.cli - command-line interface for doctorkit.

Entry point: ``doctorkit`` (installed via pyproject.toml scripts).
Also invocable as ``python -m doctorkit.cli``.
"""
from ._main import main

__all__ = ["main"]
