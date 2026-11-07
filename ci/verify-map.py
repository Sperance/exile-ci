#!/usr/bin/env python3
"""Проверка, что карта R8 принадлежит своей сборке: pg_map_id из шапки mapping.txt совпадает с идентификатором, который R8
записал в dex пакета строкой `r8-map-id-<id>` (имя исходного файла). Вывод - только вердикт, без содержимого пакета.

Запуск: python3 ci/verify-map.py <APK или AAB> <mapping.txt>
Ошибки - строкой ::error:: и код 1."""
import re
import sys
import zipfile


def fail(message):
    print(f"::error::{message}")
    sys.exit(1)


def map_id(path):
    with open(path, encoding="utf-8", errors="replace") as lines:
        for line in lines:
            found = re.match(r"#\s*pg_map_id:\s*([0-9a-f]+)\s*$", line)
            if found:
                return found.group(1)
            if not line.startswith("#"):
                break
    return ""


def main():
    package, mapping = sys.argv[1], sys.argv[2]
    expected = map_id(mapping)
    if not expected:
        fail(f"{mapping}: no pg_map_id header")
    needle = f"r8-map-id-{expected}\0".encode()
    with zipfile.ZipFile(package) as archive:
        dexes = [name for name in archive.namelist() if re.fullmatch(r"(base/dex/|)classes\d*\.dex", name)]
        if not dexes:
            fail(f"{package}: no dex files")
        if not any(needle in archive.read(name) for name in dexes):
            fail(f"{package}: map id of {mapping} is not embedded in the build (the map belongs to another build)")
    print(f"map of {package} matches its build")


main()
