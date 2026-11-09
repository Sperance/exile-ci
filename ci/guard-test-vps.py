#!/usr/bin/env python3
"""Сторож тестового стенда: команды на тестовый проект VPS идут только его ключом (DEPLOY_SSH_KEY_TEST), боевой ключ в них не попадает.

    python3 -I ci/guard-test-vps.py [корень репозитория]

Проверяет job `test` vps.yml (test-status, test-reset) и job `deploy-test` server.yml: в них есть секрет DEPLOY_SSH_KEY_TEST, нет секрета
DEPLOY_SSH_KEY (боевого) и нет пути боевой установки /opt/exileforge. Ключ теста на VPS привязан к update.sh проекта /opt/exileforge-test,
этот сторож не даёт job'ам теста сменить ключ. Красное - строкой ::error:: и код 1 (job guards в check-wip.yml, шаг «CI scripts guards» client.yml и server.yml).
"""
import json
import os
import re
import sys

import yaml

JOBS = (("vps", "test"), ("server", "deploy-test"))
PROD_KEY = re.compile(r"secrets\.DEPLOY_SSH_KEY(?!_TEST)\b")
PROD_PATH = re.compile(r"/opt/exileforge(?!-test)")


def problems(root):
    found = []
    for workflow, job in JOBS:
        path = os.path.join(root, ".github", "workflows", f"{workflow}.yml")
        body = yaml.safe_load(open(path, encoding="utf-8")).get("jobs", {}).get(job)
        if body is None:
            found.append(f"{workflow}.yml: job `{job}` not found")
            continue
        text = json.dumps(body)
        if "secrets.DEPLOY_SSH_KEY_TEST" not in text:
            found.append(f"{workflow}.yml/{job}: the test key DEPLOY_SSH_KEY_TEST is not used")
        if PROD_KEY.search(text):
            found.append(f"{workflow}.yml/{job}: the prod deploy key DEPLOY_SSH_KEY must not reach a test job")
        if PROD_PATH.search(text):
            found.append(f"{workflow}.yml/{job}: the prod install path /opt/exileforge must not appear in a test job")
    return found


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    found = problems(root)
    for line in found:
        print(f"::error::{line}")
    print(f"test stand guard: {'RED, ' + str(len(found)) + ' problem(s)' if found else 'green'}")
    sys.exit(1 if found else 0)


main()
