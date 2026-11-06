#!/usr/bin/env bash
# SSH на VPS с закреплённым ключом хоста: StrictHostKeyChecking=yes и известный ключ из переменной репозитория VPS_HOST_KEY
# (строка вида `ssh-ed25519 AAAA...` - открытый ключ хоста без имени). Раньше раннер доверял любому ключу при первом входе
# (accept-new), а подменить сервер на пути - значит получить вывод update.sh и токен Issues из stdin.
# Имя хоста в known_hosts не пишется (оно секретное): ключ привязан к псевдониму `vps`, а настоящий адрес берётся из окружения.
# Получить ключ: ssh-keyscan -t ed25519 <хост> с доверенной машины, сверить отпечаток с консолью VPS-провайдера.
# Окружение: VPS_HOST (адрес), VPS_KEY_FILE (приватный ключ деплоя), VPS_HOST_KEY (vars.VPS_HOST_KEY).
# Использование: ci/vps-ssh.sh <команда для update.sh> - stdin и stdout пробрасываются как у ssh.
set -euo pipefail

[[ -n ${VPS_HOST_KEY:-} ]] || {
    echo "::error::VPS_HOST_KEY (repository variable) is not set: pin the VPS host key, see the owner checklist (ssh-keyscan -t ed25519 <host>)"
    exit 1
}
[[ -n ${VPS_HOST:-} && -f ${VPS_KEY_FILE:-} ]] || { echo "::error::VPS_HOST or VPS_KEY_FILE is not set"; exit 1; }
[[ $VPS_HOST_KEY =~ ^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521))[[:space:]]+[A-Za-z0-9+/]+=*([[:space:]].*)?$ && $VPS_HOST_KEY != *$'\n'* ]] || {
    echo "::error::VPS_HOST_KEY must be one line: <key type> <base64 key> (the public host key, no host name)"
    exit 1
}

known=$(mktemp)
trap 'rm -f "$known"' EXIT
printf 'vps %s\n' "$VPS_HOST_KEY" >"$known"
ssh -i "$VPS_KEY_FILE" \
    -o IdentitiesOnly=yes \
    -o StrictHostKeyChecking=yes \
    -o UserKnownHostsFile="$known" \
    -o GlobalKnownHostsFile=/dev/null \
    -o HostKeyAlias=vps \
    -o BatchMode=yes \
    -o ServerAliveInterval=30 \
    -o LogLevel=ERROR \
    "root@$VPS_HOST" "$@"
