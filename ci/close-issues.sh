#!/usr/bin/env bash
# Issues, что чинит релиз: коммиты с прошлого релиза, что называют «Closes #N» (fixes, resolves), - Issue получает метку версии и
# закрывается выполненным, без комментария; игра увидит это синхронизацией сервера. Рабочая ветка - не основная, сам GitHub по таким
# словам Issues не закрывает.
# Запуск из каталога исходников клиента (src/) с историей и тегами; GH_TOKEN - токен с Issues: write на репозиторий клиента.
# Использование: ci/close-issues.sh <репозиторий клиента> <тег> <коммит релиза>
set -euo pipefail

repo=$1
TAG=$2
SHA=$3

git fetch --quiet --tags
prev=$(git for-each-ref --sort=-creatordate --format='%(refname:short)' 'refs/tags/v*' | while read -r t; do
  [ "$t" != "$TAG" ] && git merge-base --is-ancestor "$t" "$SHA" 2>/dev/null && { echo "$t"; break; }
done)
range=${prev:+$prev..}$SHA
issues=$(git log --format=%B "$range" | grep -oiE '\b(close[sd]?|fix(e[sd])?|resolve[sd]?) #[0-9]+' | grep -oE '[0-9]+' | sort -un || true)
[ -n "$issues" ] || { echo "no issues named since ${prev:-the start}"; exit 0; }
gh label create "$TAG" -R "$repo" --color 7BE0A6 --description "Released in ${TAG#v}" 2>/dev/null || true
for n in $issues; do
  state=$(gh issue view "$n" -R "$repo" --json state --jq .state 2>/dev/null) || { echo "::warning::issue #$n not found"; continue; }
  [ "$state" = OPEN ] || continue
  gh issue edit "$n" -R "$repo" --add-label "$TAG" >/dev/null
  gh issue close "$n" -R "$repo" --reason completed >/dev/null
  echo "closed #$n in ${TAG#v}"
done
