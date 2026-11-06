#!/usr/bin/env python3
"""RuStore, ручная выкладка: Issue ExileForge «[RuStore] Загрузить <версия> вручную» и автоматический повтор.

RuStore не принимает через API сборку с новым чувствительным разрешением, пока прошлая версия с ним не опубликована или разрешение
не объявлено в консоли. Тогда публикация (client.yml, publish-rustore) кладёт APK в релиз и зовёт `note`: один Issue на версию с
шагами и строкой состояния; почасовая store-status зовёт `retry`: версия уже в магазине - Issue закрывается; магазин ничего не ждёт
и живая версия сменилась после прошлой попытки - client.yml запускается в режиме stores (одна попытка на каждую новую живую версию).

    python3 ci/rustore_manual.py note <versionName> <apk url> <state.json>   - Issue и строка сводки прогона (GITHUB_STEP_SUMMARY)

Окружение: EXILEFORGE_TOKEN (Issues ExileForge), GITHUB_TOKEN и GITHUB_REPOSITORY (запуск client.yml). Значения не печатаются.
"""
import json
import os
import re
import sys

import requests

from store_common import say

CLIENT_REPO = "Sperance/ExileForge"
API = "https://api.github.com"
TITLE = "[RuStore] Загрузить {} вручную"
TITLE_RE = re.compile(r"^\[RuStore\] Загрузить (\S+) вручную$")
# Метка в теле Issue: код версии и versionId живой версии магазина при последней попытке; повтор - только когда живая версия сменилась
MARK_RE = re.compile(r"<!-- rustore code=(\d+) after=(-?\d+) -->")
PERMISSION_NOTE = ("POST_NOTIFICATIONS: локальные напоминания игроку (конец состязания, новые задания, готовое ремесло), без сервера и "
                   "рекламы; отключаются в настройках игры.")


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def _issue_token():
    token = os.environ.get("EXILEFORGE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("EXILEFORGE_TOKEN is not set")
    return token


def _open_issues(token):
    response = requests.get(f"{API}/repos/{CLIENT_REPO}/issues", params={"state": "open", "per_page": 100}, headers=_headers(token), timeout=60)
    response.raise_for_status()
    return [i for i in response.json() if "pull_request" not in i and TITLE_RE.match(i["title"])]


def _body(version, url, code, live, waiting):
    if waiting:
        status = ("Сейчас: RuStore ещё модерирует прошлую версию - руками ничего делать не нужно. Когда она будет опубликована, "
                  "CI сам повторит выкладку и закроет этот Issue.")
    else:
        status = ("Сейчас: на модерации ничего нет - RuStore ждёт ручной загрузки. После неё и публикации следующие версии снова "
                  "уйдут автоматически.")
    steps = "\n".join([
        f"1. Скачать APK: {url}",
        "2. Консоль RuStore → приложение → Новая версия → загрузить APK.",
        "3. Объявить разрешение (текст ниже) и отправить на модерацию.",
    ])
    return (f"RuStore не принял APK {version} через API: в сборке разрешение, которого нет у опубликованной версии.\n\n{status}\n\n"
            f"{steps}\n\n{PERMISSION_NOTE}\n\n<!-- rustore code={code} after={live} -->")


def note(version, url, state_path):
    with open(state_path) as file:
        state = json.load(file)
    token = _issue_token()
    body = _body(version, url, state["code"], state["live"], state["waiting"])
    title = TITLE.format(version)
    existing = next((i for i in _open_issues(token) if i["title"] == title), None)
    if existing:
        requests.patch(f"{API}/repos/{CLIENT_REPO}/issues/{existing['number']}", json={"body": body}, headers=_headers(token), timeout=60).raise_for_status()
    else:
        requests.post(f"{API}/repos/{CLIENT_REPO}/issues", json={"title": title, "body": body}, headers=_headers(token), timeout=60).raise_for_status()
    line = (f"RuStore: {version} ждёт публикации прошлой версии - выкладка повторится сама" if state["waiting"]
            else f"RuStore: {version} нужна ручная загрузка в консоли (Issue «{title}»)")
    summary = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if summary:
        with open(summary, "a") as file:
            file.write(f"### {line}\n")
    say(f"::warning::{line}")


def _dispatch_stores():
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    response = requests.post(f"{API}/repos/{repo}/actions/workflows/client.yml/dispatches", json={"ref": "main", "inputs": {"mode": "stores"}},
                             headers=_headers(token), timeout=60)
    response.raise_for_status()


# Статусы, при которых версия в магазине есть или ещё может туда дойти: такую версию заново не отправляем
SUBMITTED = {"ACTIVE", "PUBLISHED", "MODERATION", "APPROVED", "READY_FOR_PUBLICATION", "PENDING_PUBLICATION"}
REFUSED = {"REJECTED", "DECLINED"}


def retry(store, latest=None):
    """Почасовой шаг store-status: закрывает Issue выложенных версий, повторяет выкладку, когда магазин освободился, и
    отправляет самый свежий релиз (latest - его update.json), если он ждал модерации прошлой версии."""
    token = _issue_token()
    issues = _open_issues(token)
    live, waiting = store.standing()
    # Версия уже в магазине - по коду или по названию: у загруженных через консоль магазин отдаёт versionCode -1
    versions = [v for v in store.versions() if str(v.get("versionStatus", "")).upper() != "DRAFT"]
    for v in versions:
        say(f"RUSTORE: version {v.get('versionName')} code {v.get('versionCode')} id {v.get('versionId')} {v.get('versionStatus')}")
    sent = [v for v in versions if str(v.get("versionStatus", "")).upper() in SUBMITTED]
    present = {int(v["versionCode"]) for v in sent if int(v.get("versionCode") or 0) > 0}
    names = {str(v.get("versionName")) for v in sent}
    dispatched = False
    for issue in issues:
        mark = MARK_RE.search(issue.get("body") or "")
        if not mark:
            continue
        code, after = int(mark.group(1)), int(mark.group(2))
        version = TITLE_RE.match(issue["title"]).group(1)
        if any(c >= code for c in present) or version in names:
            requests.patch(f"{API}/repos/{CLIENT_REPO}/issues/{issue['number']}", json={"state": "closed", "state_reason": "completed"},
                           headers=_headers(token), timeout=60).raise_for_status()
            say(f"RUSTORE: {version} is in the store, manual-upload Issue closed")
        elif waiting:
            say(f"RUSTORE: {version} waits for the moderation of the previous version")
        elif live > after and not dispatched:
            _dispatch_stores()
            dispatched = True
            body = MARK_RE.sub(f"<!-- rustore code={code} after={live} -->", issue["body"])
            requests.patch(f"{API}/repos/{CLIENT_REPO}/issues/{issue['number']}", json={"body": body}, headers=_headers(token), timeout=60).raise_for_status()
            say(f"RUSTORE: previous version is live, client.yml stores started again for {version}")
        else:
            say(f"::warning::RUSTORE: {version} still needs a manual upload in the console")
    if issues or waiting or latest is None:
        return
    # Очередь: свежий релиз ждал модерации прошлой версии - магазин освободился, отправляем его (промежуточные пропускаются)
    code, name = int(latest["versionCode"]), latest["versionName"]
    status = {int(v.get("versionCode") or 0): str(v.get("versionStatus", "")).upper() for v in versions}
    if status.get(code) in REFUSED:
        say(f"::warning::RUSTORE: {name} was refused by the store review, it is not sent again")
    elif code not in present and name not in names:
        _dispatch_stores()
        say(f"RUSTORE: the store is free, client.yml stores started for {name}")


def main():
    if len(sys.argv) == 5 and sys.argv[1] == "note":
        note(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        sys.exit("usage: rustore_manual.py note <versionName> <apk url> <state.json>")


if __name__ == "__main__":
    main()
