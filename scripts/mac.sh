#!/usr/bin/env bash
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export PYTHONUTF8=1
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
action="${1:-run}"
if ! command -v python3.12 >/dev/null 2>&1; then
    echo 'Сначала установи Python 3.12. Если Homebrew уже установлен:'
    echo 'brew install python@3.12'
    echo 'Подробности — в файле НАЧНИ-ЗДЕСЬ.html.'
    exit 1
fi
python3.12 scripts/bootstrap.py --dependencies-only
if [[ "$action" == "tests" ]]; then
    .venv/bin/python -m scripts.verify
    exit $?
fi
if [[ "$action" == "report" ]]; then
    .venv/bin/python -m scripts.report
    open reports/lab1-report.html
    exit 0
fi
if ! command -v docker >/dev/null 2>&1; then
    export PATH="$HOME/.docker/bin:$PATH"
fi
if ! command -v docker >/dev/null 2>&1; then
    echo 'Установи Docker Desktop и открой его. Ссылка — в НАЧНИ-ЗДЕСЬ.html.'
    exit 1
fi
if ! docker info >/dev/null 2>&1; then
    open -a Docker || true
    echo 'Ждём запуска Docker Desktop…'
    for ((attempt=0; attempt<60; attempt++)); do
        if docker info >/dev/null 2>&1; then break; fi
        sleep 2
    done
fi
.venv/bin/python -m scripts.configure_llm
if [[ "$action" == "experiment" ]]; then
    python3.12 scripts/bootstrap.py local --setup-only
    .venv/bin/python -m scripts.experiment
    .venv/bin/python -m scripts.report
    open reports/lab1-report.html
elif [[ "$action" == "run" ]]; then
    python3.12 scripts/bootstrap.py local
else
    echo 'Неизвестный режим. Допустимы run, tests, experiment, report.'
    exit 1
fi
