#!/usr/bin/env bash
# Issues, что чинит выкат сервера без клиента (Release → server): коммиты сервера между прошлым выкатом и этим с трейлером
# «Refs <репозиторий клиента>#N» (ci/release_state.py server-issues). Issue получает метку «сервер <дата>» (ISO, как метка версии - с
# описанием) и закрывается выполненным без комментария; метки `ready` и `in-progress` снимаются. Нет отметки прошлого выката
# (теги server-deployed/<sha>) - ничего не закрывается: диапазон неизвестен.
# Запуск из любого каталога; GH_TOKEN - токен с Issues: write на репозиторий клиента.
# Использование: ci/close-server-issues.sh <репозиторий клиента> <каталог сервера> <прошлый выкат или пусто> <коммит выката>
set -euo pipefail

repo=$1
server=$2
base=$3
SHA=$4
here=$(dirname "${BASH_SOURCE[0]}")
. "$here/issues-lib.sh"

[ -n "$base" ] || { echo "no previous deploy mark: no server issues closed"; exit 0; }
issues=$(python3 -I "$here/release_state.py" server-issues --srv "$server" --base "$base" --head "$SHA" --repo "$repo")
day=$(date -u +%F)
close_issues "$repo" "сервер $day" "Server deployed $day" "$issues"
