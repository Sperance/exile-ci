#!/usr/bin/env python3
"""Сторож тестового стенда: команды на тестовый проект VPS идут только его ключом (DEPLOY_SSH_KEY_TEST), боевой ключ в них не попадает, и наоборот.

    python3 -I ci/guard-test-vps.py [корень репозитория]

1. Job'ы теста (`test` vps.yml, `deploy-test` server.yml): есть секрет DEPLOY_SSH_KEY_TEST, нет секрета DEPLOY_SSH_KEY (боевого) и нет пути боевой
   установки /opt/exileforge. Ключ теста на VPS привязан к update.sh проекта /opt/exileforge-test, этот сторож не даёт job'ам теста сменить ключ.
2. Перенос баланса между стендами - единственное место, где вместе стоят оба ключа: job'ы из TRANSFERS (workflow/job -> направление) обязаны брать
   оба ключа и звать действие ./.github/actions/balance-transfer с нужным направлением (в них нет путей установок и своего ssh); любой другой job
   в любом workflow, где есть оба ключа или это действие, - красный. Действие само не читает secrets и зовёт только ci/balance-transfer.sh.
3. Ключ теста не встречается ни в одном job'е, кроме job'ов теста и переноса (боевые job'ы не ходят на тест), а путь /opt/exileforge-test - вне job'ов теста.
Красное - строкой ::error:: и код 1 (job guards в check-wip.yml, шаг «CI scripts guards» client.yml и server.yml).
"""
import glob
import json
import os
import re
import sys

import yaml

TEST_JOBS = (("vps", "test"), ("server", "deploy-test"))
TRANSFERS = {
    ("server", "test-base"): "prod-to-test",
    ("vps", "test-base"): "prod-to-test",
    ("server", "balance"): "test-to-prod",
    ("release", "balance"): "test-to-prod",
}
ACTION = "./.github/actions/balance-transfer"
PROD_KEY = re.compile(r"secrets\.DEPLOY_SSH_KEY(?!_TEST)\b")
TEST_KEY = re.compile(r"secrets\.DEPLOY_SSH_KEY_TEST\b")
PROD_PATH = re.compile(r"/opt/exileforge(?!-test)")
TEST_PATH = re.compile(r"/opt/exileforge-test")
SSH_LINE = re.compile(r"vps-ssh\.sh|\bssh\b")


def load(root):
    jobs = {}
    for path in sorted(glob.glob(os.path.join(root, ".github", "workflows", "*.yml"))):
        workflow = os.path.basename(path)[:-4]
        for name, body in (yaml.safe_load(open(path, encoding="utf-8")).get("jobs") or {}).items():
            jobs[(workflow, name)] = body
    return jobs


def test_job_problems(label, text):
    found = []
    if not TEST_KEY.search(text):
        found.append(f"{label}: the test key DEPLOY_SSH_KEY_TEST is not used")
    if PROD_KEY.search(text):
        found.append(f"{label}: the prod deploy key DEPLOY_SSH_KEY must not reach a test job")
    if PROD_PATH.search(text):
        found.append(f"{label}: the prod install path /opt/exileforge must not appear in a test job")
    return found


def transfer_problems(label, body, text, direction):
    found = []
    if not (PROD_KEY.search(text) and TEST_KEY.search(text)):
        found.append(f"{label}: the transfer job needs both keys")
    steps = [step for step in body.get("steps") or [] if str(step.get("uses", "")).split("@")[0] == ACTION]
    if len(steps) != 1:
        found.append(f"{label}: the transfer goes through exactly one {ACTION} step")
    elif (steps[0].get("with") or {}).get("direction") != direction:
        found.append(f"{label}: the transfer direction must be {direction}")
    if PROD_PATH.search(text) or TEST_PATH.search(text):
        found.append(f"{label}: an install path must not appear in a transfer job")
    if any(SSH_LINE.search(str(step.get("run", ""))) for step in body.get("steps") or []):
        found.append(f"{label}: a transfer job does not run ssh itself, only the action does")
    return found


def action_problems(root):
    path = os.path.join(root, ACTION[2:], "action.yml")
    if not os.path.exists(path):
        return [f"{ACTION}: the action file is missing"]
    text = open(path, encoding="utf-8").read()
    found = []
    if "secrets." in text:
        found.append(f"{ACTION}: the action takes keys as inputs and never reads secrets itself")
    if len(re.findall(r"^\s*run:.*$", text, re.M)) != 1 or "ci/balance-transfer.sh" not in text:
        found.append(f"{ACTION}: the action runs only ci/balance-transfer.sh")
    return found


def problems(root):
    jobs = load(root)
    found = []
    for key in TEST_JOBS:
        if key not in jobs:
            found.append(f"{key[0]}.yml: job `{key[1]}` not found")
        else:
            found += test_job_problems(f"{key[0]}.yml/{key[1]}", json.dumps(jobs[key]))
    for key, direction in TRANSFERS.items():
        if key not in jobs:
            found.append(f"{key[0]}.yml: transfer job `{key[1]}` not found")
        else:
            found += transfer_problems(f"{key[0]}.yml/{key[1]}", jobs[key], json.dumps(jobs[key]), direction)
    for key, body in jobs.items():
        text = json.dumps(body)
        label = f"{key[0]}.yml/{key[1]}"
        if key in TRANSFERS:
            continue
        if ACTION in text or (PROD_KEY.search(text) and TEST_KEY.search(text)):
            found.append(f"{label}: both stand keys or the transfer action outside the transfer jobs {sorted(f'{w}/{j}' for w, j in TRANSFERS)}")
        elif key not in TEST_JOBS and (TEST_KEY.search(text) or TEST_PATH.search(text)):
            found.append(f"{label}: the test stand key or path must not appear outside the test and transfer jobs")
    return found + action_problems(root)


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    found = problems(root)
    for line in found:
        print(f"::error::{line}")
    print(f"test stand guard: {'RED, ' + str(len(found)) + ' problem(s)' if found else 'green'}")
    sys.exit(1 if found else 0)


main()
