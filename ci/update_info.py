"""Общая часть update.json клиента: релиз (ci/release-files.py) и тестовая сборка (ci/qa-files.py) пишут одну форму, которую читает обновлятор игры (Updates.kt).

Запуск из каталога исходников клиента (src/): константы провода и правил читаются из сабмодуля backend/. Ошибки - строкой ::error:: и код 1.
"""
import hashlib
import json
import os
import re
import sys

PROTOCOL = "backend/rules/src/main/kotlin/com/sperance/exileforge/rules/wire/Protocol.kt"
CONTENT = "backend/rules/src/main/kotlin/com/sperance/exileforge/rules/content/Content.kt"


def fail(message):
    print(f"::error::{message}")
    sys.exit(1)


def first_group(path, pattern):
    """Первое совпадение построчно (как `sed -n ... | head -1`) или пустая строка."""
    with open(path, encoding="utf-8") as lines:
        for line in lines:
            found = re.search(pattern, line)
            if found:
                return found.group(1)
    return ""


def wire_constants():
    api = first_group(PROTOCOL, r"^const val API_REVISION = ([0-9]*)")
    rules = first_group(CONTENT, r"^const val RULES_VERSION = ([0-9]*)")
    schema = first_group(CONTENT, r"^const val CONTENT_SCHEMA = ([0-9]*)")
    if not (api and rules and schema):
        fail(f"update.json: API '{api}', rules '{rules}' or content schema '{schema}' not found")
    return int(api), int(rules), int(schema)


def write(out, code, name, apk, notes, mandatory):
    api, rules, schema = wire_constants()
    with open(os.path.join(out, apk), "rb") as file:
        sha256 = hashlib.sha256(file.read()).hexdigest()
    size = os.path.getsize(os.path.join(out, apk))
    info = {"versionCode": code, "versionName": name, "apiRevision": api, "rules": rules, "contentSchema": schema,
            "apk": apk, "size": size, "sha256": sha256, "notes": notes, "mandatory": mandatory}
    with open(os.path.join(out, "update.json"), "w", encoding="utf-8", newline="\n") as file:
        file.write(json.dumps(info, ensure_ascii=False) + "\n")
