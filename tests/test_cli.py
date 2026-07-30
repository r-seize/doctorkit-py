"""Tests for doctorkit CLI (init command)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from doctorkit.cli._init import cmd_init, _scan, _generate


class TestCmdInit:
    def test_generates_doctor_py(self, tmp_path):
        cmd_init(str(tmp_path))
        target = tmp_path / "doctor.py"
        assert target.exists()
        content = target.read_text()
        assert "from doctorkit import Doctor" in content
        assert "doctor = Doctor()" in content

    def test_skips_if_exists(self, tmp_path, capsys):
        target = tmp_path / "doctor.py"
        target.write_text("# existing")
        cmd_init(str(tmp_path))
        assert target.read_text() == "# existing"
        captured = capsys.readouterr()
        assert "skipping" in captured.out

    def test_invalid_directory(self, tmp_path, capsys):
        cmd_init(str(tmp_path / "nonexistent"))
        captured = capsys.readouterr()
        assert "Error" in captured.out

    def test_detects_node_project(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        cmd_init(str(tmp_path))
        content = (tmp_path / "doctor.py").read_text()
        assert "command_check" in content
        assert '"node"' in content

    def test_detects_python_project(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'")
        cmd_init(str(tmp_path))
        content = (tmp_path / "doctor.py").read_text()
        assert "python3" in content

    def test_detects_dotenv(self, tmp_path):
        (tmp_path / ".env.example").write_text("DATABASE_URL=postgres://localhost/db\n")
        cmd_init(str(tmp_path))
        content = (tmp_path / "doctor.py").read_text()
        assert "envfile_check" in content
        assert "DATABASE_URL" in content

    def test_detects_docker(self, tmp_path):
        (tmp_path / "docker-compose.yml").write_text("version: '3'")
        cmd_init(str(tmp_path))
        content = (tmp_path / "doctor.py").read_text()
        assert "docker" in content

    def test_env_vars_filtered_to_known(self, tmp_path):
        (tmp_path / ".env.example").write_text("UNKNOWN_VAR=x\nREDIS_URL=redis://localhost\n")
        cmd_init(str(tmp_path))
        content = (tmp_path / "doctor.py").read_text()
        assert "REDIS_URL" in content
        assert "UNKNOWN_VAR" not in content


class TestScan:
    def test_empty_dir(self, tmp_path):
        detected, env_vars = _scan(tmp_path)
        assert len(detected) == 0
        assert len(env_vars) == 0

    def test_multiple_markers(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "Dockerfile").write_text("FROM node:18")
        detected, _ = _scan(tmp_path)
        assert "node" in detected
        assert "docker" in detected


class TestGenerate:
    def test_minimal_output(self):
        content = _generate(set(), [])
        assert "from doctorkit import Doctor" in content
        assert "doctor = Doctor()" in content
        assert 'if __name__ == "__main__"' in content

    def test_env_vars_included(self):
        content = _generate({"dotenv"}, ["DATABASE_URL"])
        assert "envfile_check" in content
        assert "DATABASE_URL" in content

    def test_node_tools_included(self):
        content = _generate({"node"}, [])
        assert '"node"' in content
        assert "18.0" in content
