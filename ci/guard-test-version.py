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

import yaml

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


def check_prod_fallback():
    stand = os.path.join(HERE, "test-stand.py")
    commit = "d" * 40
    code, out = python(stand, "prod-live", stdin='{"version": "1.91.56", "commit": "%s", "revision": 145}' % commit)
    if code != 0 or out.strip() != f"1.91.56 {commit}":
        fail("the live prod manifest does not give the base of the test server version: deploy-test without a prod deploy mark would stall")
    code, _ = python(stand, "prod-live", stdin="not json")
    if code == 0:
        fail("a broken live prod manifest must not give a test server version")
    check_deploy_test_never_stalls()


def check_deploy_test_never_stalls():
    root = os.path.join(HERE, "..")
    document = yaml.safe_load(open(os.path.join(root, ".github", "workflows", "server.yml"), encoding="utf-8"))
    script = open(os.path.join(HERE, "test-server-version.sh"), encoding="utf-8").read()
    for step in document["jobs"]["deploy-test"]["steps"]:
        text = step.get("run") if isinstance(step.get("run"), str) else ""
        if re.search(r"no record of a prod|deploy mark|prod deploy|stand record|no record of", text, re.IGNORECASE) and re.search(r"\bexit 1\b", text):
            fail(f"step '{step.get('name')}' of deploy-test fails with 'exit 1' on a missing prod deploy mark or stand record: the test server must fall back to the live prod manifest or its own image version")
    if re.search(r"\bexit 1\b|\breturn 1\b", "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))):
        fail("ci/test-server-version.sh fails with exit 1/return 1: a missing prod deploy mark or stand record must fall back, not stall deploy-test")
    if "prod-live" not in script:
        fail("ci/test-server-version.sh lost the fallback to the live prod manifest (test-stand.py prod-live)")


def check_deploy_test_sends_build():
    root = os.path.join(HERE, "..")
    document = yaml.safe_load(open(os.path.join(root, ".github", "workflows", "server.yml"), encoding="utf-8"))
    steps = document["jobs"]["deploy-test"]["steps"]
    names = [step.get("name", "") for step in steps]
    sends = [i for i, step in enumerate(steps) if "ci/test-build.sh send" in (step.get("run") if isinstance(step.get("run"), str) else "")]
    deploys = [i for i, name in enumerate(names) if name == "Update the test server on the VPS"]
    if not sends or not deploys or sends[0] < deploys[0]:
        fail("deploy-test does not send `test-build <qa> <issues>` (ci/test-build.sh send) after the deploy step: the test server would depend on reading GitHub for the fix-verification list")
    body = "x\n<!-- issues: 1082,1083 -->\ny"
    done = subprocess.run(["bash", os.path.join(HERE, "test-build.sh"), "issues"], capture_output=True, text=True, input=body, check=False)
    if done.returncode != 0 or done.stdout.strip() != "1082,1083":
        fail("ci/test-build.sh does not read the <!-- issues: --> marker of the qa release body")
    bad = subprocess.run(["bash", os.path.join(HERE, "test-build.sh"), "issues"], capture_output=True, text=True, input="<!-- issues: 1; rm -->", check=False)
    if bad.returncode == 0:
        fail("ci/test-build.sh accepts a malformed issue list: only digits and commas go to the test stand")


def main():
    check_client_versions()
    check_server_versions()
    check_prod_fallback()
    check_deploy_test_sends_build()
    print("test version format: ok")


main()
