#!/bin/bash
export PATH="$HOME/.opencode/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
cd -- "$(dirname -- "$0")" || exit 1
if command -v opencode >/dev/null 2>&1; then
    opencode
    result=$?
else
    echo 'Сначала установи OpenCode 2 по инструкции https://opencode.ai/v2/docs'
    result=1
fi
read -r -p 'Нажми Enter, чтобы закрыть окно.'
exit "$result"
