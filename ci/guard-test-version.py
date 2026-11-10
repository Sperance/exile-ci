#!/usr/bin/env python3
"""Сторож формата версии тестовой сборки и тестового сервера: x.y.z_test (ci/qa-files.py, ci/test-stand.py) читают TestVersion сервера и клиента
(rules `wire/TestVersion.kt`), по номеру сборки из versionCode считаются карты падений R8 и проверка исправлений автором. Смена формата только здесь или
только там ломает их молча, поэтому формат закреплён таблицей: тот же ряд примеров держит тест TestVersionTest сервера.

Без сети и секретов; в журнал - только «ok» или причина. Ошибки - строкой ::error:: и код 1.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = re.compile(r"^\d+\.\d+\.\d+_test$")
VERSION_CASES = (
    ("v0.25.0", "-", "-", "0.25.1_test"),
    ("v0.25.0", "0.25.1_test", "-", "0.25.2_test"),
    ("v0.25.0", "0.25.1-test.5256+e2db540", "-", "0.25.2_test"),
    ("v0.25.0", "0.25.3_test", "0.25.2_test", "0.25.2_test"),
    ("v0.26.0", "0.25.7_test", "-", "0.26.1_test"),
    ("v0.25.3", "0.25.3_test", "-", "0.25.4_test"),
)
SERVER_CASES = (
    ("1.91.56", "-", "b", "1.91.57_test"),
    ("1.91.56", "same", "b", "1.91.57_test"),
    ("1.91.56", "same", "c", "1.91.58_test"),
)


def fail(message):
    print(f"::error::{message}")
    sys.exit(1)


def python(*args, stdin=None):
    done = subprocess.run([sys.executable, "-I", *args], capture_output=True, text=True, input=stdin, check=False)
    return done.returncode, done.stdout


def check_client_versions():
    for last, previous, same, wanted in VERSION_CASES:
        with tempfile.TemporaryDirectory() as folder:
            out = os.path.join(folder, "out")
            code, _ = python(os.path.join(HERE, "qa-files.py"), "version", last, "5300", "abcdef1", previous, same, out)
            made = open(out, encoding="utf-8").read().strip() if code == 0 else ""
        if made != f"name={wanted}" or not NAME.match(made.removeprefix("name=")):
            fail(f"the test client version for {last} after {previous} is not {wanted}: TestVersion of the server and the client reads x.y.z_test")


def check_server_versions():
    base, first, second = "a" * 40, "b" * 40, "c" * 40
    with tempfile.TemporaryDirectory() as folder:
        previous = os.path.join(folder, "previous.json")
        with open(previous, "w", encoding="utf-8") as out:
            out.write('{"base": "%s", "k": 1, "image": "%s", "version": "1.91.57_test"}' % (base, first))
        for prod, state, image, wanted in SERVER_CASES:
            target = os.path.join(folder, "out")
            open(target, "w", encoding="utf-8").close()
            code, _ = python(os.path.join(HERE, "test-stand.py"), "version", prod, base, "-" if state == "-" else previous, (first if image == "b" else second), target)
            made = open(target, encoding="utf-8").read().splitlines()[:1] if code == 0 else []
            if made != [f"name={wanted}"]:
                fail(f"the test server version for prod {prod} is not {wanted}: ServerVersion of the server reads x.y.z_test")


def main():
    check_client_versions()
    check_server_versions()
    print("test version format: ok")


main()
