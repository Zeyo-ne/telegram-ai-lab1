#!/bin/bash
set -euo pipefail
export PATH="$HOME/.opencode/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
cd -- "$(dirname -- "$0")"
if ! command -v opencode >/dev/null 2>&1; then
    echo 'Сначала установи OpenCode 2 и проведи настоящую сессию в папке проекта.'
    read -r -p 'Нажми Enter.'
    exit 1
fi
opencode session list
read -r -p 'Вставь ID своей сессии (ses_…): ' session_id
if [[ ! "$session_id" =~ ^ses_[A-Za-z0-9_-]+$ ]]; then
    echo 'Нужен точный идентификатор ses_… из списка выше.'
    read -r -p 'Нажми Enter.'
    exit 1
fi
umask 077
mkdir -p reports/private
opencode session export "$session_id" > "reports/private/opencode-original-$session_id.json"
opencode session export "$session_id" --sanitize > "reports/opencode-sanitized-$session_id.json"
echo 'Оригинал сохранён в reports/private — его не публикуй.'
echo 'Копия для передачи сохранена в reports/opencode-sanitized-….json.'
echo 'Проверь копию на секреты перед передачей преподавателю.'
read -r -p 'Нажми Enter, чтобы закрыть окно.'
