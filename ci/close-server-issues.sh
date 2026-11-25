#!/usr/bin/env bash
# Закрытие отчётов в очереди, указанной в Report-Queue коммита, после отдельного выката сервера.
# Использование: ci/close-server-issues.sh <репозиторий клиента> <каталог сервера> <прошлый выкат или пусто> <коммит выката>
set -euo pipefail

repo=$1
server=$2
base=$3
SHA=$4
here=$(dirname "${BASH_SOURCE[0]}")
. "$here/issues-lib.sh"

[ -n "$base" ] || { echo "no previous deploy mark: no server issues closed"; exit 0; }
prod=$(python3 -I "$here/release_state.py" server-issues --srv "$server" --base "$base" --head "$SHA" --repo "$repo" --queue prod)
test=$(python3 -I "$here/release_state.py" server-issues --srv "$server" --base "$base" --head "$SHA" --repo "$repo" --queue test)
day=$(date -u +%F)
failed=0
close_issues "${REPORTS_API_URL:-}" false "сервер $day" "$prod" || failed=1
close_issues "${TEST_REPORTS_API_URL:-}" true "сервер $day" "$test" || failed=1
exit "$failed"
