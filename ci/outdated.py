#!/usr/bin/env python3
"""Устаревшие зависимости клиента и сервера (maintenance.yml, задача outdated, раз в неделю): только сводка в журнал.

    python3 ci/outdated.py <метка=каталог.toml>...   например client=src-client/gradle/libs.versions.toml

Читает каталоги версий Gradle (gradle/libs.versions.toml) и сверяет каждую версию с последним стабильным выпуском в Maven Central,
Google Maven и Gradle Plugin Portal. Ничего не меняет и кода не открывает: в публичный журнал через [say] попадают только счётчики, а строки
«метка: группа:артефакт 1.2.0 -> 1.3.0» - в файл $OUTDATED_REPORT, который job шифрует в артефакт. Прогон зелёный при любом числе устаревших; красный только
если каталога нет или он не читается. Записи без версии (версию задаёт BOM) пропускаются. Только стандартная библиотека.
"""
import re
import os
import sys
import tomllib
import urllib.error
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

import net
from store_common import say

LIBRARY_REPOS = ("https://repo.maven.apache.org/maven2", "https://dl.google.com/dl/android/maven2")
PLUGIN_REPOS = ("https://plugins.gradle.org/m2",)
UNSTABLE = re.compile(r"(?i)(alpha|beta|rc|dev|snapshot|eap|preview|pre|candidate|milestone|(?<![a-z])m\d+)")
PLAIN = re.compile(r"\d+(\.\d+)*")
TIMEOUT_S = 20


def version_of(entry, versions):
    spec = entry.get("version")
    if isinstance(spec, dict):
        spec = versions.get(spec["ref"]) if "ref" in spec else next((spec[k] for k in ("strictly", "require", "prefer") if k in spec), None)
    return spec if isinstance(spec, str) and spec else None


def coordinates(path):
    with open(path, "rb") as file:
        catalog = tomllib.load(file)
    versions = catalog.get("versions", {})
    found = []
    for lib in catalog.get("libraries", {}).values():
        module = lib.get("module") or f"{lib['group']}:{lib['name']}"
        version = version_of(lib, versions)
        if version:
            found.append((module, version, LIBRARY_REPOS))
    for plugin in catalog.get("plugins", {}).values():
        version = version_of(plugin, versions)
        if version:
            found.append((f"{plugin['id']}:{plugin['id']}.gradle.plugin", version, PLUGIN_REPOS))
    return sorted(set(found))


def order(version):
    return tuple(int(part) for part in re.findall(r"\d+", version))


def published(module, repos):
    group, artifact = module.split(":")
    for repo in repos:
        url = f"{repo}/{group.replace('.', '/')}/{artifact}/maven-metadata.xml"
        try:
            root = ET.fromstring(net.fetch(url, timeout=TIMEOUT_S).body)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                continue
            return None
        except (urllib.error.URLError, TimeoutError, ET.ParseError):
            return None
        return [node.text for node in root.iter("version") if node.text]
    return []


def newest(current, available):
    if UNSTABLE.search(current):
        wanted = available
    elif PLAIN.fullmatch(current):
        wanted = [v for v in available if PLAIN.fullmatch(v)]
    else:
        wanted = [v for v in available if not UNSTABLE.search(v)]
    return max(wanted, key=order, default=None)


def check(item):
    module, current, repos = item
    available = published(module, repos)
    if available is None:
        return module, current, None, "unreachable"
    latest = newest(current, available)
    if latest is None:
        return module, current, None, "unknown"
    return module, current, latest, "outdated" if order(latest) > order(current) else "current"


def report(label, path):
    items = coordinates(path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(check, items))
    with open(os.environ.get("OUTDATED_REPORT", os.devnull), "a", encoding="utf-8") as sealed:
        for module, current, latest, state in results:
            if state == "outdated":
                sealed.write(f"{label}: {module} {current} -> {latest}\n")
    counts = {state: sum(1 for r in results if r[3] == state) for state in ("outdated", "unknown", "unreachable")}
    say(f"{label}: {counts['outdated']} of {len(results)} outdated, {counts['unknown']} not found, {counts['unreachable']} unreachable")


def main(arguments):
    if not arguments:
        say("::error::no catalogs given")
        return 1
    for argument in arguments:
        label, _, path = argument.partition("=")
        try:
            report(label, path)
        except (OSError, tomllib.TOMLDecodeError, KeyError) as error:
            say(f"::error::{label}: the version catalog is unreadable ({type(error).__name__})")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
