"""doctorkit init - project scanner and doctor.py generator."""
from __future__ import annotations

import pathlib
from typing import List, Set, Tuple

_MARKERS: List[Tuple[str, str]] = [
    ("package.json",       "node"),
    ("pyproject.toml",     "python"),
    ("setup.py",           "python"),
    ("requirements.txt",   "python"),
    ("Pipfile",            "python"),
    ("docker-compose.yml", "docker"),
    ("docker-compose.yaml","docker"),
    ("Dockerfile",         "docker"),
    (".env.example",       "dotenv"),
    (".env",               "dotenv"),
]

_KNOWN_ENV_VARS: Set[str] = {
    "DATABASE_URL", "DB_URL", "POSTGRES_URL",
    "REDIS_URL",
    "SECRET_KEY", "API_KEY", "API_SECRET",
    "SMTP_HOST", "MAIL_HOST",
    "S3_BUCKET", "AWS_ACCESS_KEY_ID",
}


def cmd_init(directory: str = ".") -> None:
    root = pathlib.Path(directory).resolve()
    if not root.is_dir():
        print(f"Error: {directory} is not a directory")
        return

    target = root / "doctor.py"
    if target.exists():
        print(f"doctor.py already exists in {root} - skipping")
        return

    detected, env_vars = _scan(root)
    content = _generate(detected, env_vars)
    target.write_text(content, encoding="utf-8")
    print(f"Generated {target}")
    print("Run it with: python doctor.py")


def _scan(root: pathlib.Path) -> Tuple[Set[str], List[str]]:
    detected: Set[str] = set()
    for filename, kind in _MARKERS:
        if (root / filename).exists():
            detected.add(kind)

    env_vars: List[str] = []
    for candidate in (".env.example", ".env"):
        env_file = root / candidate
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                name = line.split("=")[0].strip()
                if name.upper() in _KNOWN_ENV_VARS:
                    env_vars.append(name)
            break

    return detected, env_vars


def _generate(detected: Set[str], env_vars: List[str]) -> str:
    lines: List[str] = [
        "from doctorkit import Doctor",
    ]

    imports: List[str] = []
    if "dotenv" in detected or env_vars:
        imports.append("from doctorkit.checks.env import env_check, envfile_check")
    if detected & {"node", "docker", "python"}:
        imports.append("from doctorkit.checks.network import http_check, tcp_check")
    imports.append("from doctorkit.checks.filesystem import dir_exists_check, writable_check")
    imports.append("from doctorkit.checks.process import command_check")

    lines += imports
    lines += ["", "doctor = Doctor()", ""]

    if "dotenv" in detected or env_vars:
        lines.append('doctor.add("dotenv", envfile_check(".env"), tag="env")')
        for var in env_vars:
            lines.append(f'doctor.add("{var}", env_check("{var}"), tag="env")')
        lines.append("")

    tools: List[Tuple[str, str, str | None]] = []
    if "node" in detected:
        tools += [("node", "node", "18.0"), ("npm", "npm", None)]
    if "python" in detected:
        tools.append(("python", "python3", "3.9"))
    if "docker" in detected:
        tools.append(("docker", "docker", None))

    if tools:
        for check_name, cmd, min_ver in tools:
            if min_ver:
                lines.append(
                    f'doctor.add("{check_name}", command_check("{cmd}", min_version="{min_ver}"), tag="tools")'
                )
            else:
                lines.append(
                    f'doctor.add("{check_name}", command_check("{cmd}"), tag="tools")'
                )
        lines.append("")

    lines += [
        'if __name__ == "__main__":',
        "    import sys",
        "    sys.exit(doctor.run())",
        "",
    ]

    return "\n".join(lines)
