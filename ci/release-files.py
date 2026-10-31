#!/usr/bin/env python3
"""Файлы релиза клиента (job `release` client.yml): APK, карта R8, заметки и update.json - то, что читает обновлятор игры
(Updates.kt): сборка, провод и правила, на которых она говорит, APK и его SHA-256.

Запуск из каталога исходников клиента (src/) после распаковки сборки release-apk; в окружении DIRECT_APK и DIRECT_MAPPING
(`. ci/build-tasks.env`):
    python3 ../ci/release-files.py <тег v<versionName>> <каталог результата>
В каталог результата кладутся ExileForge-<тег>.apk, mapping.txt, RELEASE_NOTES.md и update.json. Ошибки - строкой ::error:: и код 1.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

# Пути результата сборки прямого канала - из ci/build-tasks.env (workflow кладёт их в окружение как DIRECT_APK и DIRECT_MAPPING)
APK_SOURCE = os.environ["DIRECT_APK"]
MAPPING_SOURCE = os.environ["DIRECT_MAPPING"]


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


def main():
    tag, out = sys.argv[1], sys.argv[2]
    name = tag.removeprefix("v")
    apk = f"ExileForge-{tag}.apk"
    shutil.copyfile(APK_SOURCE, os.path.join(out, apk))
    shutil.copyfile(MAPPING_SOURCE, os.path.join(out, "mapping.txt"))

    # Заметки: в RELEASE_NOTES.md - только эта версия, под первым заголовком «## <versionName>».
    heading = next((line.rstrip(" \t\r\n\f\v") for line in open("RELEASE_NOTES.md", encoding="utf-8") if line.startswith("## ")), "")
    if heading != f"## {name}":
        fail(f"RELEASE_NOTES.md first heading is '{heading}', not '## {name}'")
    shutil.copyfile("RELEASE_NOTES.md", os.path.join(out, "RELEASE_NOTES.md"))

    code = first_group("app/build.gradle.kts", r"versionCode = ([0-9]*)")
    api = first_group("backend/rules/src/main/kotlin/com/sperance/exileforge/rules/wire/Protocol.kt", r"^const val API_REVISION = ([0-9]*)")
    rules = first_group("backend/rules/src/main/kotlin/com/sperance/exileforge/rules/content/Content.kt", r"^const val RULES_VERSION = ([0-9]*)")
    if not (code and api and rules):
        fail(f"update.json: versionCode '{code}', API '{api}' or rules '{rules}' not found")

    with open(os.path.join(out, apk), "rb") as file:
        sha256 = hashlib.sha256(file.read()).hexdigest()
    size = os.path.getsize(os.path.join(out, apk))
    # Обязательность релиза: трейлер «Update-Mandatory: yes» в сообщении коммита релиза делает сборку обязательной и на том же
    # проводе; без него релиз на том же проводе - мягкое обновление (тост, не диалог).
    message = subprocess.run(["git", "log", "-1", "--format=%B"], check=True, capture_output=True, text=True).stdout
    mandatory = re.search(r"^Update-Mandatory: yes", message, re.IGNORECASE | re.MULTILINE) is not None

    notes = open("RELEASE_NOTES.md", encoding="utf-8").read().split("\n", 1)[1].strip()
    info = {"versionCode": int(code), "versionName": name, "apiRevision": int(api), "rules": int(rules),
            "apk": apk, "size": size, "sha256": sha256, "notes": notes, "mandatory": mandatory}
    with open(os.path.join(out, "update.json"), "w", encoding="utf-8", newline="\n") as file:
        file.write(json.dumps(info, ensure_ascii=False) + "\n")


main()
