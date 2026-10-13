#!/bin/bash
cd -- "$(dirname -- "$0")" || exit 1
bash scripts/mac.sh report
result=$?
read -r -p 'Нажми Enter, чтобы закрыть окно.'
exit "$result"
