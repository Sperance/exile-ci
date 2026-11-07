#!/usr/bin/env bash
# Образ сервера двух коммитов один и тот же: второй - потомок первого, и между ними менялись только .md вне образа. В образ идут
# rules-md/ и RULES.md (справочник «Правила» панели) и всё из src/main/resources/ (заметки и инструкции панели). Такие пуши
# CI сервера не проверяет - тот же список стоит в paths у deploy.yml сервера, правится вместе.
# Использование: ci/server-diff.sh <клон сервера с историей> <от> <до>; код 0 - образ тот же, 1 - нет.
set -euo pipefail

dir=$1
from=$2
to=$3
[[ $from == "$to" ]] && exit 0
git -C "$dir" merge-base --is-ancestor "$from" "$to" || exit 1
while IFS= read -r file; do
    case $file in
        rules-md/* | RULES.md | src/main/resources/*) exit 1 ;;
        *.md) ;;
        *) exit 1 ;;
    esac
done < <(git -C "$dir" diff --name-only "$from" "$to")
