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
