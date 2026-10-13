import subprocess
import sys
from unittest.mock import Mock

import pytest

from scripts import bootstrap


def test_existing_environment_missing_pip_recovers_without_recreating(monkeypatch, tmp_path):
    python = tmp_path / "python"
    python.write_text("existing interpreter")
    runner = Mock(side_effect=[Mock(returncode=1), Mock(returncode=0), Mock(returncode=0)])
    monkeypatch.setattr(bootstrap.subprocess, "run", runner)

    bootstrap.prepare_pip(python, {})

    assert python.read_text() == "existing interpreter"
    assert runner.call_args_list[1].args[0][1:] == ["-m", "ensurepip", "--upgrade", "--default-pip"]
    assert not any("venv" in call.args[0] for call in runner.call_args_list)


def test_ensurepip_failure_uses_base_pip_for_only_target_environment(monkeypatch, tmp_path):
    python = tmp_path / "python"
    runner = Mock(side_effect=[Mock(returncode=1), Mock(returncode=1), Mock(), Mock()])
    monkeypatch.setattr(bootstrap.subprocess, "run", runner)

    bootstrap.prepare_pip(python, {})

    assert runner.call_args_list[2].args[0] == [
        sys.executable,
        "-m",
        "pip",
        "--python",
        str(python),
        "install",
        "pip",
    ]
    assert runner.call_args_list[2].kwargs["check"]


def test_failed_recovery_does_not_install_requirements(monkeypatch, tmp_path):
    runner = Mock(
        side_effect=[
            Mock(returncode=1),
            Mock(returncode=1),
            subprocess.CalledProcessError(1, "pip"),
        ]
    )
    monkeypatch.setattr(bootstrap.subprocess, "run", runner)

    with pytest.raises(subprocess.CalledProcessError):
        bootstrap.prepare_pip(tmp_path / "python", {})

    assert runner.call_count == 3


def test_working_pip_needs_no_installation(monkeypatch, tmp_path):
    runner = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr(bootstrap.subprocess, "run", runner)

    bootstrap.prepare_pip(tmp_path / "python", {})

    assert runner.call_count == 1


def test_empty_macos_version_uses_actual_system_version_in_child_python(monkeypatch, tmp_path):
    monkeypatch.setattr(bootstrap.sys, "platform", "darwin")
    monkeypatch.setattr(bootstrap.platform, "mac_ver", lambda: ("", ("", "", ""), ""))
    command = Mock(return_value="26.2\n")
    monkeypatch.setattr(bootstrap.subprocess, "check_output", command)
    env = {}

    bootstrap.configure_macos_version(env, tmp_path / "compat")

    assert command.call_args.args[0] == ["/usr/bin/sw_vers", "-productVersion"]
    # Настоящий дочерний процесс: импортируется созданный файл, как при запуске pip.
    code = """
import sys, platform, runpy
sys.platform = "darwin"
platform.mac_ver = lambda *args: ("", ("", "", ""), "")
platform.machine = lambda: "arm64"
runpy.run_path(sys.argv[1])
assert platform.mac_ver() == ("26.2", ("", "", ""), "arm64")
"""
    subprocess.run(
        [sys.executable, "-c", code, str(tmp_path / "compat/sitecustomize.py")], check=True
    )
    assert env["PYTHONPATH"] == str(tmp_path / "compat")


def test_working_macos_version_does_not_enable_workaround(monkeypatch, tmp_path):
    monkeypatch.setattr(bootstrap.sys, "platform", "darwin")
    monkeypatch.setattr(bootstrap.platform, "mac_ver", lambda: ("26.2", ("", "", ""), "arm64"))
    env = {}

    bootstrap.configure_macos_version(env, tmp_path)

    assert not env and not (tmp_path / "sitecustomize.py").exists()


def test_macos_workaround_rejects_invalid_system_output(monkeypatch, tmp_path):
    monkeypatch.setattr(bootstrap.sys, "platform", "darwin")
    monkeypatch.setattr(bootstrap.platform, "mac_ver", lambda: ("", ("", "", ""), ""))
    monkeypatch.setattr(bootstrap.subprocess, "check_output", Mock(return_value="not-a-version"))

    with pytest.raises(OSError, match="sw_vers"):
        bootstrap.configure_macos_version({}, tmp_path)

    assert not (tmp_path / "sitecustomize.py").exists()
