"""doctorkit.checks - stdlib check factory library.

Each submodule provides zero-dependency check factories built on Python's
standard library. Import what you need; nothing is auto-imported.

    from doctorkit.checks.network import http_check, tcp_check
    from doctorkit.checks.env import env_check
    from doctorkit.checks.filesystem import dir_exists_check
    from doctorkit.checks.process import command_check
"""
from .network import dns_check, http_check, tcp_check
from .env import env_check, envfile_check, envfile_vars_check
from .filesystem import dir_exists_check, file_exists_check, writable_check
from .process import command_check

__all__ = [
    "http_check",
    "tcp_check",
    "dns_check",
    "env_check",
    "envfile_check",
    "envfile_vars_check",
    "dir_exists_check",
    "file_exists_check",
    "writable_check",
    "command_check",
]
