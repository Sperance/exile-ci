#!/usr/bin/env bash
# Контрольные суммы архивов для облачных сессий агента: файл SHA256SUMS в prerelease `gradle-cache` приватного ExileForge. Хуки
# сессии (.claude/hooks/gradle-cache.sh, toolchain.sh) сверяют SHA-256 скачанного архива с этим файлом ДО распаковки: подменённый
# архив не распаковывается. Строка на архив - формат `sha256sum`. Для каждого .tar.gz релиза сумма берётся из файла; нет строки -
# архив скачивается и считается; архивы, которых в релизе уже нет, из файла уходят; переданные локальные файлы (только что
# загруженные) считаются заново, потому что архив того же имени перезаписывается.
# Использование: GH_TOKEN=<токен с Contents: write на репозиторий> ci/cache-sums.sh <репозиторий> <тег> [локальный архив...]
set -euo pipefail

repo=$1
tag=$2
shift 2
dir=$(mktemp -d)
trap 'rm -rf "$dir"' EXIT
mkdir -p "$dir/dl"
. "$(dirname "${BASH_SOURCE[0]}")/retry.sh"

netcall read gh release view "$tag" -R "$repo" >/dev/null 2>&1 || { echo "no $tag release yet: checksums skipped"; exit 0; }
netcall read gh release download "$tag" -R "$repo" -p SHA256SUMS -D "$dir" --clobber >/dev/null 2>&1 || : >"$dir/SHA256SUMS"
declare -A local_sum=()
for file in "$@"; do
    local_sum[$(basename "$file")]=$(sha256sum "$file" | cut -d' ' -f1)
done

: >"$dir/new"
while IFS= read -r name; do
    [[ $name == *.tar.gz ]] || continue
    sum=${local_sum[$name]:-}
    [[ -n $sum ]] || sum=$(awk -v n="$name" '$2 == n { print $1; exit }' "$dir/SHA256SUMS")
    if [[ -z $sum ]]; then
        netcall read gh release download "$tag" -R "$repo" -p "$name" -D "$dir/dl" --clobber >/dev/null
        sum=$(sha256sum "$dir/dl/$name" | cut -d' ' -f1)
        rm -f "$dir/dl/$name"
    fi
    [[ $sum =~ ^[0-9a-f]{64}$ ]] || { echo "::error::no checksum for $name"; exit 1; }
    printf '%s  %s\n' "$sum" "$name" >>"$dir/new"
done < <(netcall read gh release view "$tag" -R "$repo" --json assets -q '.assets[].name' | sort)

sort -k2 "$dir/new" >"$dir/SHA256SUMS"
netcall idem gh release upload "$tag" "$dir/SHA256SUMS" -R "$repo" --clobber >/dev/null
echo "checksums: $(wc -l <"$dir/SHA256SUMS") archive(s) in SHA256SUMS"
