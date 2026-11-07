#!/usr/bin/env bash
# Проверенный образ сервера для коммита <sha>: образ самого коммита (тег :<sha> ставит job `mark` server.yml после зелёных проверок)
# или ближайшего предка, если после него менялись только .md вне образа (ci/server-diff.sh) - такие пуши CI не проверяет.
# Вывод: «<коммит образа> <дайджест>»; код 1 - проверенного образа нет. Нужен вход в ghcr.io с правом чтения пакета.
# Использование: ci/checked-image.sh <образ> <клон сервера с историей> <sha>
set -euo pipefail

image=$1
dir=$2
sha=$3
for commit in $(git -C "$dir" rev-list --first-parent --max-count=50 "$sha"); do
    # Дальше по истории - другой код: старший образ выкатывать нельзя
    bash "$(dirname "$0")/server-diff.sh" "$dir" "$commit" "$sha" || exit 1
    if digest=$(docker buildx imagetools inspect "$image:$commit" --format '{{.Manifest.Digest}}' 2>/dev/null); then
        [[ $digest =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "::error::bad image digest for $commit" >&2; exit 1; }
        echo "$commit $digest"
        exit 0
    fi
done
exit 1
