#!/usr/bin/env bash
# Общее шифрование CI (подключается через source; сам ничего не выполняет). Журналы и артефакты репозитория публичны, поэтому
# всё, что раскрывает код, шифруется:
#   age (ChaCha20-Poly1305, открытый ключ) - основной способ. На раннере лежит только ОТКРЫТЫЙ ключ из переменных репозитория,
#     расшифровать может лишь владелец закрытого ключа: ключ не утекает через раннер, целостность проверяется при расшифровке.
#     LOG_AGE_RECIPIENT - ключ владельца (журналы и отчёты; создаётся `age-keygen -o key.txt`, открытая часть - строка `age1...`).
#     SEAL_AGE_RECIPIENT - второй получатель для артефактов, что передаются между job'ами (сборка -> подпись -> публикация):
#     закрытая часть лежит секретом SEAL_AGE_IDENTITY и выдаётся только шагам, которые распаковывают артефакт.
# Читать файл age владельцу: age -d -i key.txt <файл> (артефакты-архивы: age -d -i key.txt <файл> | tar -xf -).

AGE_RECIPIENT_RE='^age1[a-z0-9]{50,}$'

# ensure_age: age нет в образе раннера - ставится из выпуска age на GitHub (версия и sha256 закреплены выше, сверка до распаковки), при сбое -
# из пакетов Ubuntu (подписанные архивы apt); один раз за job. Зеркала Ubuntu у раннеров бывают недоступны часами (DNS).
AGE_URL=https://github.com/FiloSottile/age/releases/download/v1.2.1/age-v1.2.1-linux-amd64.tar.gz
AGE_SHA256=7df45a6cc87d4da11cc03a539a7470c15b1041ab2b396af088fe9990f7c79d50

age_from_release() {
    local dir
    dir=$(mktemp -d)
    netcall read curl -fsSL -o "$dir/age.tgz" "$AGE_URL" >/dev/null || return 1
    echo "$AGE_SHA256  $dir/age.tgz" | sha256sum -c --quiet - || { echo "::error::age archive checksum mismatch"; return 1; }
    tar -xzf "$dir/age.tgz" -C "$dir" && sudo install -m 0755 "$dir/age/age" /usr/local/bin/age
}

ensure_age() {
    command -v age >/dev/null 2>&1 && return 0
    . "$(dirname "${BASH_SOURCE[0]}")/retry.sh"
    age_from_release && return 0
    echo "::warning::age release download failed, trying apt"
    { netcall read sudo apt-get update -qq && netcall read sudo apt-get install -y -qq age; } >/dev/null 2>&1 || { echo "::error::cannot install age"; return 1; }
}

# crypt_recipient <имя переменной> -> 0, если значение задано и похоже на открытый ключ age; 1 - не задано; ошибка - неверное значение
crypt_recipient() {
    local value=${!1:-}
    [[ -n $value ]] || return 1
    [[ $value =~ $AGE_RECIPIENT_RE ]] || { echo "::error::$1 is not an age public key (age1...)"; exit 1; }
}

# encrypt <log|transit> <входной файл или -> <выходной файл>
# log - читает только владелец; transit - ещё и CI следующего job'а (нужен SEAL_AGE_RECIPIENT).
# 0 - зашифровано; 1 - нет ни одного ключа (вызывающий решает, что делать).
encrypt() {
    local kind=$1 in=$2 out=$3
    local -a args=() src=()
    [[ $in == - ]] || src=("$in")
    if crypt_recipient LOG_AGE_RECIPIENT; then
        args=(-r "$LOG_AGE_RECIPIENT")
        if [[ $kind == transit ]]; then
            if crypt_recipient SEAL_AGE_RECIPIENT; then
                args+=(-r "$SEAL_AGE_RECIPIENT")
            else
                args=()
            fi
        fi
    fi
    ((${#args[@]})) || return 1
    ensure_age || return 1
    age "${args[@]}" -o "$out" "${src[@]}"
}

# decrypt <файл> -> расшифрованный поток в stdout. Формат определяется по заголовку файла.
decrypt() {
    local file=$1 magic identity
    magic=$(head -c 21 "$file" | LC_ALL=C tr -d '\0')
    case $magic in
        age-encryption.org/v1)
            [[ -n ${SEAL_AGE_IDENTITY:-} ]] || { echo "::error::SEAL_AGE_IDENTITY is not set: cannot unpack an age artifact" >&2; return 1; }
            ensure_age || return 1
            identity=$(mktemp)
            printf '%s\n' "$SEAL_AGE_IDENTITY" >"$identity"
            age -d -i "$identity" "$file"
            local code=$?
            rm -f "$identity"
            return $code ;;
        *) echo "::error::unknown encrypted file format: $file" >&2; return 1 ;;
    esac
}
