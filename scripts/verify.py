"""Одинаковые проверки на Windows/macOS, сохранение реального вывода."""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKS = [
    ["pytest", "-q", "-m", "not integration"],
    ["ruff", "check", "."],
    ["ruff", "format", "--check", "."],
    ["pip", "check"],
]


def main() -> int:
    results = []
    for arguments in CHECKS:
        completed = subprocess.run(
            [sys.executable, "-m", *arguments],
            cwd=ROOT,
            env={**os.environ, "PYTHONUTF8": "1"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        output = completed.stdout + completed.stderr
        print(output, end="")
        results.append(
            {
                "command": "python -m " + " ".join(arguments),
                "exit_code": completed.returncode,
                "output": output,
            }
        )
    folder = ROOT / "reports"
    folder.mkdir(exist_ok=True)
    (folder / "checks.json").write_text(
        json.dumps(
            {
                "date": datetime.now().astimezone().isoformat(),
                "platform": sys.platform,
                "checks": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return int(any(result["exit_code"] for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
