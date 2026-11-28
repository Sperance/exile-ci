#!/usr/bin/env python3
"""Сторож репозиториев Gradle: buildscript-плагины берутся через зеркало Maven Central, портал - только запасной.

    python3 -I ci/guard-gradle-repos.py [--server <settings.gradle.kts>] [--server-rules <rules/settings.gradle.kts>] [--client <settings.gradle.kts>]

Проблема, которую он ловит: корневой проект сервера объявляет плагины (kotlin, ktor, ktlint), а блока `pluginManagement`
в его settings.gradle.kts не было - весь buildscript-классpath (30 МБ kotlin-плагина и его зависимости) шёл через портал
Gradle, который отдаёт 429 Too Many Requests. Gradle прячет эту ошибку под «Problems writing to Binary store ...»: сборка
падала на настройке проекта, и те же сборки были зелёными там, где эти зависимости уже лежали в кэше Gradle.
Зеркало `https://maven-central.storage-download.googleapis.com/maven2/` должно стоять в `pluginManagement.repositories`
раньше `gradlePluginPortal()`: маркеры плагинов ktor и ktlint есть только на портале, остальное - на Maven Central.

Красное: в `pluginManagement` нет зеркала, портал стоит раньше зеркала, блока `pluginManagement` нет вовсе.
Файлы репозиториев передаёт job guards в check-wip.yml (git show из клонов сервера и клиента); без файлов (ci/precheck.sh) - пропуск с пометкой.
"""
import argparse
import sys

MIRROR = "maven-central.storage-download.googleapis.com"
PORTAL = "gradlePluginPortal"


def block_of(text, header):
    start = text.find(header)
    if start < 0:
        return None
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return text[start:]


def settings_errors(path):
    errors = []
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    block = block_of(text, "pluginManagement")
    if block is None:
        errors.append(f"{path}: no pluginManagement block: the buildscript plugins come only from the Gradle plugin portal")
        return errors
    repositories = block_of(block, "repositories")
    if repositories is None:
        errors.append(f"{path}: pluginManagement has no repositories block")
        return errors
    mirror = repositories.find(MIRROR)
    portal = repositories.find(PORTAL)
    if mirror < 0:
        errors.append(f"{path}: pluginManagement has no Maven Central mirror ({MIRROR}): the buildscript classpath comes from the plugin portal alone")
    elif portal >= 0 and portal < mirror:
        errors.append(f"{path}: gradlePluginPortal() stands before the Maven Central mirror: the buildscript classpath is fetched from the portal first")
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server")
    parser.add_argument("--server-rules")
    parser.add_argument("--client")
    args = parser.parse_args()
    files = [path for path in (args.server, args.server_rules, args.client) if path]
    if not files:
        print("gradle repos guard: green (repository files not given)")
        return 0
    errors = []
    for path in files:
        errors += settings_errors(path)
    for error in errors:
        print(f"::error::{error}")
    if not errors:
        print(f"gradle repos guard: green ({len(files)} settings file(s), the Maven Central mirror comes first)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
