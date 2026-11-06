#!/usr/bin/env bash
# Повтор чтения с GitHub сразу после пуша: хранилище Git на GitHub отдаёт чтение с ограниченным отставанием от записи, поэтому
# только что запушенный коммит или ветка изредка ещё «не найдены». Подключается через source; actions/checkout повторяет сам.
# Использование: retry <команда...> - до 4 попыток с паузами 2, 4, 8 с; код возврата - последней попытки.
retry() {
    local attempt=1 delay=2
    until "$@"; do
        ((attempt < 4)) || return 1
        echo "::notice::GitHub read failed, retry $attempt of 3 in ${delay}s" >&2
        sleep "$delay"
        attempt=$((attempt + 1)) delay=$((delay * 2))
    done
}
