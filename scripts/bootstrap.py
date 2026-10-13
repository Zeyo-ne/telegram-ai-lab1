"""Этот файл использует только стандартную библиотеку Python."""

import hashlib
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def configure_macos_version(env: dict[str, str], directory: Path) -> None:
    """Для дочерних Python берём фактическую версию macOS, если mac_ver пуст."""
    if sys.platform != "darwin" or platform.mac_ver()[0]:
        return
    version = subprocess.check_output(
        ["/usr/bin/sw_vers", "-productVersion"], env=env, text=True, timeout=10
    ).strip()
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,2}", version):
        raise OSError("sw_vers не вернул корректную версию macOS")
    directory.mkdir(parents=True, exist_ok=True)
    source = f'''"""Совместимость только для запуска этого проекта."""
import platform
import sys

if sys.platform == "darwin":
    _original_mac_ver = platform.mac_ver

    def _mac_ver(release="", versioninfo=("", "", ""), machine=""):
        result = _original_mac_ver(release, versioninfo, machine)
        if result[0]:
            return result
        return ({version!r}, result[1], result[2] or platform.machine())

    platform.mac_ver = _mac_ver
'''
    (directory / "sitecustomize.py").write_text(source, encoding="utf-8")
    env["PYTHONPATH"] = str(directory)
    print(f"Версия macOS для установки библиотек: {version} (из sw_vers).", flush=True)


def prepare_pip(python: Path, env: dict[str, str]) -> None:
    """Восстанавливаем pip и в окружении, оставшемся после неудачного venv."""
    probe = [str(python), "-m", "pip", "--version"]
    if (
        subprocess.run(
            probe, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).returncode
        == 0
    ):
        return
    print("Устанавливаем pip в .venv…", flush=True)
    # venv скрывает вывод ensurepip при ошибке; отдельный запуск сохраняет причину.
    result = subprocess.run([str(python), "-m", "ensurepip", "--upgrade", "--default-pip"], env=env)
    if result.returncode:
        print("Пробуем восстановить pip через основной Python…", flush=True)
        subprocess.run(
            [sys.executable, "-m", "pip", "--python", str(python), "install", "pip"],
            env=env,
            check=True,
        )
    subprocess.run(probe, env=env, check=True)


def main() -> int:
    if sys.version_info[:2] != (3, 12):
        print("Нужен Python 3.12. Установите его по инструкции в README.")
        return 1
    python = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    env = {**os.environ, "PYTHONUTF8": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    try:
        if not python.exists():
            print("Создаём отдельное окружение .venv…", flush=True)
            subprocess.run(
                [sys.executable, "-m", "venv", "--without-pip", str(ROOT / ".venv")],
                env=env,
                check=True,
            )
        check = subprocess.run(
            [str(python), "-c", "import sys; sys.exit(sys.version_info[:2] != (3, 12))"],
            env=env,
        )
        if check.returncode:
            print("В .venv другая версия Python. Переименуйте .venv и запустите скрипт снова.")
            return 1
        configure_macos_version(env, ROOT / ".venv" / ".macos-compat")
        prepare_pip(python, env)
        digest = hashlib.sha256(
            b"".join(
                (ROOT / name).read_bytes()
                for name in ["requirements.txt", "requirements-dev.txt", "constraints.txt"]
            )
        )
        marker = ROOT / ".venv" / ".requirements-sha256"
        if not marker.exists() or marker.read_text() != digest.hexdigest():
            print(
                "Устанавливаем зависимости (первый запуск может занять несколько минут)…",
                flush=True,
            )
            subprocess.run(
                [str(python), "-m", "pip", "install", "-r", str(ROOT / "requirements-dev.txt")],
                cwd=ROOT,
                env=env,
                check=True,
            )
            marker.write_text(digest.hexdigest(), encoding="utf-8")
        if sys.argv[1:] == ["--dependencies-only"]:
            return 0
        return subprocess.call([str(python), "-m", "scripts.cli", *sys.argv[1:]], cwd=ROOT, env=env)
    except (OSError, subprocess.CalledProcessError):
        print("Не удалось подготовить .venv. Пришлите последние строки ошибки выше.")
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
