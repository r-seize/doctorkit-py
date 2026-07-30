"""Tests for doctorkit built-in check factories."""
import os
import tempfile
import unittest.mock as mock

import pytest

from doctorkit.checks.env import env_check, envfile_check, envfile_vars_check
from doctorkit.checks.filesystem import dir_exists_check, file_exists_check, writable_check
from doctorkit.checks.process import command_check, _extract_version, _version_gte


# ---------------------------------------------------------------------------
# env checks
# ---------------------------------------------------------------------------


class TestEnvCheck:
    def test_variable_set(self, monkeypatch):
        monkeypatch.setenv("MY_VAR", "hello")
        result = env_check("MY_VAR")()
        assert result.status == "ok"
        assert "MY_VAR" in result.message

    def test_variable_missing(self, monkeypatch):
        monkeypatch.delenv("MY_VAR", raising=False)
        result = env_check("MY_VAR")()
        assert result.status == "fail"
        assert "MY_VAR" in result.message

    def test_pattern_match(self, monkeypatch):
        monkeypatch.setenv("MY_VAR", "sk-ant-abc123")
        result = env_check("MY_VAR", pattern=r"sk-ant-.+")()
        assert result.status == "ok"

    def test_pattern_no_match(self, monkeypatch):
        monkeypatch.setenv("MY_VAR", "wrong")
        result = env_check("MY_VAR", pattern=r"sk-ant-.+")()
        assert result.status == "fail"
        assert "format" in result.message

    def test_custom_hint(self, monkeypatch):
        monkeypatch.delenv("MISSING", raising=False)
        result = env_check("MISSING", hint="custom hint")()
        assert result.hint == "custom hint"


class TestEnvfileCheck:
    def test_existing_file(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("FOO=bar")
        result = envfile_check(str(f))()
        assert result.status == "ok"

    def test_missing_file(self, tmp_path):
        result = envfile_check(str(tmp_path / ".env"))()
        assert result.status == "fail"
        assert "not found" in result.message


# ---------------------------------------------------------------------------
# filesystem checks
# ---------------------------------------------------------------------------


class TestDirExistsCheck:
    def test_existing_dir(self, tmp_path):
        result = dir_exists_check(str(tmp_path))()
        assert result.status == "ok"

    def test_missing_dir(self, tmp_path):
        result = dir_exists_check(str(tmp_path / "nonexistent"))()
        assert result.status == "fail"
        assert "Run: mkdir" in result.hint

    def test_path_is_file_not_dir(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("x")
        result = dir_exists_check(str(f))()
        assert result.status == "fail"
        assert "not a directory" in result.message


class TestFileExistsCheck:
    def test_existing_file(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("x")
        result = file_exists_check(str(f))()
        assert result.status == "ok"

    def test_missing_file(self, tmp_path):
        result = file_exists_check(str(tmp_path / "missing.txt"))()
        assert result.status == "fail"
        assert "not found" in result.message

    def test_path_is_dir_not_file(self, tmp_path):
        result = file_exists_check(str(tmp_path))()
        assert result.status == "fail"
        assert "not a file" in result.message


class TestWritableCheck:
    def test_writable_dir(self, tmp_path):
        result = writable_check(str(tmp_path))()
        assert result.status == "ok"

    def test_missing_path(self, tmp_path):
        result = writable_check(str(tmp_path / "nonexistent"))()
        assert result.status == "fail"
        assert "does not exist" in result.message

    def test_non_writable_dir(self, tmp_path):
        d = tmp_path / "readonly"
        d.mkdir()
        os.chmod(str(d), 0o555)
        try:
            result = writable_check(str(d))()
            assert result.status == "fail"
            assert "not writable" in result.message
        finally:
            os.chmod(str(d), 0o755)


# ---------------------------------------------------------------------------
# process checks
# ---------------------------------------------------------------------------


class TestCommandCheck:
    def test_command_on_path(self):
        result = command_check("python3")()
        assert result.status in ("ok", "warn")

    def test_command_not_found(self):
        result = command_check("__nonexistent_cmd_xyz__")()
        assert result.status == "fail"
        assert "not found on PATH" in result.message

    def test_min_version_satisfied(self):
        result = command_check("python3", min_version="3.0")()
        assert result.status in ("ok", "warn")

    def test_min_version_too_high(self):
        result = command_check("python3", min_version="99.0")()
        assert result.status in ("fail", "warn")

    def test_extract_version(self):
        assert _extract_version("Python 3.11.2") == "3.11.2"
        assert _extract_version("v18.0.0") == "18.0.0"
        assert _extract_version("no version here") is None

    def test_version_gte(self):
        assert _version_gte("3.11", "3.9") is True
        assert _version_gte("3.9", "3.11") is False
        assert _version_gte("18.0.0", "18.0") is True
        assert _version_gte("18.0", "18.0") is True


class TestEnvfileVarsCheck:
    def test_all_vars_defined_in_env_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        example = tmp_path / ".env.example"
        example.write_text("DATABASE_URL=\nAPI_KEY=\n")
        env = tmp_path / ".env"
        env.write_text("DATABASE_URL=postgres://localhost\nAPI_KEY=secret\n")
        result = envfile_vars_check(str(example), env_file=str(env))()
        assert result.status == "ok"
        assert "2" in result.message

    def test_missing_var_fails(self, tmp_path, monkeypatch):
        monkeypatch.delenv("API_KEY", raising=False)
        example = tmp_path / ".env.example"
        example.write_text("API_KEY=\n")
        env = tmp_path / ".env"
        env.write_text("")
        result = envfile_vars_check(str(example), env_file=str(env))()
        assert result.status == "fail"
        assert "API_KEY" in result.message

    def test_var_set_in_process_env_is_accepted(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MY_SECRET", "value")
        example = tmp_path / ".env.example"
        example.write_text("MY_SECRET=\n")
        env = tmp_path / ".env"
        env.write_text("")
        result = envfile_vars_check(str(example), env_file=str(env))()
        assert result.status == "ok"

    def test_missing_example_file_fails(self, tmp_path):
        result = envfile_vars_check(str(tmp_path / "missing.example"))()
        assert result.status == "fail"
        assert "not found" in result.message

    def test_empty_example_ok(self, tmp_path):
        example = tmp_path / ".env.example"
        example.write_text("# just a comment\n\n")
        result = envfile_vars_check(str(example))()
        assert result.status == "ok"

    def test_comments_and_blank_lines_ignored(self, tmp_path, monkeypatch):
        monkeypatch.delenv("REAL_VAR", raising=False)
        example = tmp_path / ".env.example"
        example.write_text("# comment\n\nREAL_VAR=x\n")
        env = tmp_path / ".env"
        env.write_text("REAL_VAR=value\n")
        result = envfile_vars_check(str(example), env_file=str(env))()
        assert result.status == "ok"

    def test_no_env_file_still_checks_process_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PRESENT_VAR", "yes")
        monkeypatch.delenv("ABSENT_VAR", raising=False)
        example = tmp_path / ".env.example"
        example.write_text("PRESENT_VAR=\nABSENT_VAR=\n")
        result = envfile_vars_check(str(example), env_file=str(tmp_path / "nonexistent.env"))()
        assert result.status == "fail"
        assert "ABSENT_VAR" in result.message
