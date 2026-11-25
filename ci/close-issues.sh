#!/usr/bin/env bash
# Закрытие отчётов в очереди, указанной в Report-Queue коммита, после публикации выпуска.
# Запуск из каталога исходников клиента с историей, тегами и сабмодулем backend/.
# Использование: ci/close-issues.sh <репозиторий клиента> <тег> <коммит релиза>
set -euo pipefail

repo=$1
TAG=$2
SHA=$3
here=$(dirname "${BASH_SOURCE[0]}")
. "$here/issues-lib.sh"

netcall read git fetch --quiet --tags
[ "$(git rev-parse --verify "$TAG^{commit}")" = "$SHA" ] || { echo "::error::the published client tag does not name this commit" >&2; exit 1; }
prev=$(git for-each-ref --sort=-creatordate --format='%(refname:short)' 'refs/tags/v*' | while read -r t; do
  [ "$t" != "$TAG" ] && git merge-base --is-ancestor "$t" "$SHA" 2>/dev/null && { echo "$t"; break; }
done)
prod=$(python3 -I "$here/release_state.py" issues --cli . --srv backend --base "${prev:-}" --head "$SHA" --repo "$repo" --queue prod --closing)
test=$(python3 -I "$here/release_state.py" issues --cli . --srv backend --base "${prev:-}" --head "$SHA" --repo "$repo" --queue test --closing)
failed=0
close_issues "${REPORTS_API_URL:-}" false "$TAG" "$prod" || failed=1
close_issues "${TEST_REPORTS_API_URL:-}" true "$TAG" "$test" "$SHA" . "" || failed=1
exit "$failed"
