#!/bin/bash
cd -- "$(dirname -- "$0")" || exit 1
bash scripts/mac.sh run
result=$?
echo "Программа завершилась (код $result)."
read -r -p 'Нажми Enter, чтобы закрыть окно.'
exit "$result"
