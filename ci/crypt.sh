#!/usr/bin/env bash
# Общее шифрование CI (подключается через source; сам ничего не выполняет). Журналы и артефакты репозитория публичны, поэтому
# всё, что раскрывает код, шифруется:
#   age (ChaCha20-Poly1305, открытый ключ) - основной способ. На раннере лежит только ОТКРЫТЫЙ ключ из переменных репозитория,
#     расшифровать может лишь владелец закрытого ключа: ключ не утекает через раннер, целостность проверяется при расшифровке.
#     LOG_AGE_RECIPIENT - ключ владельца (журналы и отчёты; создаётся `age-keygen -o key.txt`, открытая часть - строка `age1...`).
#     SEAL_AGE_RECIPIENT - второй получатель для артефактов, что передаются между job'ами (сборка -> подпись -> публикация):
#     закрытая часть лежит секретом SEAL_AGE_IDENTITY и выдаётся только шагам, которые распаковывают артефакт.
#   openssl с общим паролем LOG_KEY (AES-256-CBC, PBKDF2) - переходный запасной способ, пока LOG_AGE_RECIPIENT не задан;
#     каждый раз предупреждает. Читать старые файлы: openssl enc -d -aes-256-cbc -pbkdf2 -pass env:LOG_KEY -in <файл>
# Читать файл age владельцу: age -d -i key.txt <файл> (артефакты-архивы: age -d -i key.txt <файл> | tar -xf -).

AGE_RECIPIENT_RE='^age1[a-z0-9]{50,}$'

# ensure_age: age нет в образе раннера - ставится из пакетов Ubuntu (подписанные архивы apt), один раз за job.
ensure_age() {
    command -v age >/dev/null 2>&1 && return 0
    { sudo apt-get update -qq && sudo apt-get install -y -qq age; } >/dev/null 2>&1 || { echo "::error::cannot install age"; return 1; }
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
    if ((${#args[@]})); then
        ensure_age || return 1
        age "${args[@]}" -o "$out" "${src[@]}"
        return
    fi
    if [[ -n ${LOG_KEY:-} ]]; then
        echo "::warning::LOG_AGE_RECIPIENT (and SEAL_AGE_RECIPIENT for artifacts passed between jobs) is not set: falling back to the deprecated openssl LOG_KEY encryption"
        local -a input=()
        [[ $in == - ]] || input=(-in "$in")
        openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:LOG_KEY -out "$out" "${input[@]}"
        return
    fi
    return 1
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
        Salted__*)
            [[ -n ${LOG_KEY:-} ]] || { echo "::error::LOG_KEY is not set: cannot unpack an openssl artifact" >&2; return 1; }
            openssl enc -d -aes-256-cbc -pbkdf2 -pass env:LOG_KEY -in "$file" ;;
        *) echo "::error::unknown encrypted file format: $file" >&2; return 1 ;;
    esac
}
