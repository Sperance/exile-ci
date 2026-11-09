#!/usr/bin/env python3
"""Сводка слепка баланса теста для Release → preview: только числа и имена файлов, значений баланса и текстов нет (журнал публичен).

    python3 -I ci/balance-summary.py <слепок .gz> <файл сводки>
        -> блок «Баланс теста» в файл сводки (дописывается): сколько файлов баланса теста отличается от образа (имена файлов контента),
           сколько поправок текстов клиента по языкам, отличается ли мир теста от боя (по хэшам слепка), версия выпуска теста.
Слепок - gzip JSON `TransferFile` сервера; нечитаемый слепок - строка об этом, код 0 (сводка вспомогательная). Ошибки аргументов - ::error:: и код 1.
"""
import collections
import gzip
import json
import re
import sys

FILE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def lines_of(snapshot):
    changed = snapshot.get("changed") or {}
    texts = snapshot.get("texts") or []
    names = sorted(name for name in changed if FILE_NAME.match(name))
    languages = collections.Counter(str(item.get("language", "?")) for item in texts if isinstance(item, dict))
    release = snapshot.get("release")
    lines = ["### Баланс теста", f"- Выпуск баланса на тесте: {'№' + str(release) if release is not None else 'свой выпуск не публиковался'}.",
             f"- Файлов баланса, отличных от образа: {len(changed)}" + (f" ({', '.join(names)})." if names else ".")]
    lines.append(f"- Поправок текстов клиента: {sum(languages.values())}" + (f" ({', '.join(f'{code} {count}' for code, count in sorted(languages.items()))})." if languages else "."))
    base, world = snapshot.get("baseWorldHash"), snapshot.get("worldHash")
    if base and world:
        lines.append("- Мир теста " + ("совпадает с боевым, переносить нечего." if base == world else "отличается от боевого: при выпуске клиента баланс уйдёт в бой."))
    else:
        lines.append("- Сравнить с боем нельзя: у слепка нет хэшей мира.")
    return lines


def main():
    if len(sys.argv) != 3:
        print("::error::usage: balance-summary.py <snapshot.gz> <summary file>")
        sys.exit(1)
    try:
        snapshot = json.loads(gzip.open(sys.argv[1], "rb").read().decode("utf-8"))
        lines = lines_of(snapshot)
    except (OSError, ValueError, AttributeError):
        lines = ["### Баланс теста", "- Слепок не разобран."]
    with open(sys.argv[2], "a", encoding="utf-8") as out:
        out.write("\n".join(lines) + "\n")
    print(f"balance summary: {len(lines) - 1} line(s)")


main()
