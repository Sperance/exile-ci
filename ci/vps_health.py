#!/usr/bin/env python3
"""Часовой присмотр за VPS: строки «OK|FAIL <проверка>» от update.sh health -> Issue в ExileForge.

Есть провал - один открытый Issue «[VPS] Сервер требует внимания» со списком проверок (без адресов, чисел и журнала: подробности
только в зашифрованном журнале прогона); тело меняется, лишь когда сменился набор провалов, чтобы не слать письма каждый час.
Всё в порядке - открытый Issue закрывается. Сам скрипт на сервере ничего не чинит (rules-md/server/vps-maintenance.md сервера).

    python3 ci/vps_health.py <вывод health> <код ssh>

Окружение: EXILEFORGE_TOKEN (Issues ExileForge), RUN_URL. Значения не печатаются.
"""
import os
import re
import sys

import requests

REPO = "Sperance/ExileForge"
API = "https://api.github.com"
TITLE = "[VPS] Сервер требует внимания"
NAMES = {
    "game": "контейнер игры не здоров",
    "https": "игра не отвечает снаружи",
    "disk": "мало места на диске",
    "memory": "мало свободной памяти",
    "mongo": "база не отвечает",
    "backup": "нет свежей суточной копии базы",
    "cert": "сертификат скоро истекает или не читается",
    "updates": "автообновления безопасности не запускались",
    "ssh": "нет связи с VPS по SSH",
}


def failures(path, code):
    try:
        with open(path, encoding="utf-8", errors="replace") as file:
            lines = file.read().splitlines()
    except OSError:
        lines = []
    seen = {m.group(2): m.group(1) for m in (re.match(r"^(OK|FAIL)\s+([a-z]+)", line) for line in lines) if m}
    if code != 0 or not seen:
        return ["ssh"]
    return sorted(name for name, state in seen.items() if state == "FAIL")


def main():
    path, code = sys.argv[1], int(sys.argv[2])
    failed = failures(path, code)
    token = os.environ["EXILEFORGE_TOKEN"].strip()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    response = requests.get(f"{API}/repos/{REPO}/issues", params={"state": "open", "labels": "vps", "per_page": 50}, headers=headers, timeout=60)
    response.raise_for_status()
    issue = next((i for i in response.json() if i["title"] == TITLE and "pull_request" not in i), None)
    if not failed:
        if issue:
            requests.patch(f"{API}/repos/{REPO}/issues/{issue['number']}", json={"state": "closed", "state_reason": "completed"},
                           headers=headers, timeout=60).raise_for_status()
            print("vps health: all checks pass, issue closed")
        else:
            print("vps health: all checks pass")
        return
    mark = "<!-- vps-health " + ",".join(failed) + " -->"
    items = "\n".join(f"- {NAMES.get(name, name)}" for name in failed)
    body = (f"Часовая проверка VPS нашла проблему:\n\n{items}\n\nСам присмотр ничего не чинит. Подробности - в зашифрованном журнале "
            f"прогона: {os.environ.get('RUN_URL', '')}\n\nIssue закроется сам, когда все проверки пройдут.\n\n{mark}")
    if issue is None:
        requests.post(f"{API}/repos/{REPO}/issues", json={"title": TITLE, "body": body, "labels": ["bug", "vps"]},
                      headers=headers, timeout=60).raise_for_status()
        print(f"::warning::vps health: {len(failed)} failing check(s), issue opened")
    elif mark not in (issue.get("body") or ""):
        requests.patch(f"{API}/repos/{REPO}/issues/{issue['number']}", json={"body": body}, headers=headers, timeout=60).raise_for_status()
        print(f"::warning::vps health: {len(failed)} failing check(s), issue updated")
    else:
        print(f"::warning::vps health: {len(failed)} failing check(s), issue already open")


if __name__ == "__main__":
    main()
