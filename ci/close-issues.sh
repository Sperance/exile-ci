#!/usr/bin/env bash
# Issues, что чинит релиз: коммиты КЛИЕНТА с прошлого релиза с трейлером «Issue: #N» (так пишут работы: «Closes #N» в основной ветке
# GitHub закрыл бы Issue сразу при пуше) или прежним «Closes #N» (fixes, resolves) и коммиты СЕРВЕРА между закреплёнными в клиенте
# серверами прошлого и этого релиза с трейлером «Refs <репозиторий клиента>#N» (ci/release_state.py issues) - Issue получает метку версии
# и закрывается выполненным, без комментария; метки `ready` («ждёт выпуска») и `in-progress` снимаются; игра увидит это синхронизацией
# сервера. Рабочая ветка клиента - основная в репозитории: «Closes #N» GitHub исполняет сразу при пуше, поэтому работы пишут «Issue: #N».
# Запуск из каталога исходников клиента (src/) с историей, тегами и сабмодулем backend/ (его история нужна для коммитов сервера);
# GH_TOKEN - токен с Issues: write на репозиторий клиента.
# Использование: ci/close-issues.sh <репозиторий клиента> <тег> <коммит релиза>
set -euo pipefail

repo=$1
TAG=$2
SHA=$3
here=$(dirname "${BASH_SOURCE[0]}")
. "$here/issues-lib.sh"

git fetch --quiet --tags
prev=$(git for-each-ref --sort=-creatordate --format='%(refname:short)' 'refs/tags/v*' | while read -r t; do
  [ "$t" != "$TAG" ] && git merge-base --is-ancestor "$t" "$SHA" 2>/dev/null && { echo "$t"; break; }
done)
issues=$(python3 -I "$here/release_state.py" issues --cli . --srv backend --base "${prev:-}" --head "$SHA" --repo "$repo")
[ -n "$issues" ] || { echo "no issues named since ${prev:-the start}"; exit 0; }
close_issues "$repo" "$TAG" "Released in ${TAG#v}" "$issues"
