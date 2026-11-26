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

import net
from rustore import status_of
from store_common import say

CLIENT_REPO = "Sperance/ExileForge"
API = "https://api.github.com"
TITLE = "[RuStore] Загрузить {} вручную"
TITLE_RE = re.compile(r"^\[RuStore\] Загрузить (\S+) вручную$")
# Метка в теле Issue: код версии и versionId живой версии магазина при последней попытке; повтор - только когда живая версия сменилась;
# reason - почему версия не в магазине: manual (нужна ручная загрузка) или busy (магазин модерирует прошлую версию)
MARK_RE = re.compile(r"<!-- rustore code=(\d+) after=(-?\d+) reason=(\w+) -->")
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
    response = net.send(None, "GET", f"{API}/repos/{CLIENT_REPO}/issues", params={"state": "open", "per_page": 100}, headers=_headers(token), timeout=60)
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
            f"{steps}\n\n{PERMISSION_NOTE}\n\n<!-- rustore code={code} after={live} reason=manual -->")


def _wait_body(version, code, live, waiting):
    if waiting:
        status = ("Сейчас: RuStore ещё модерирует прошлую версию - руками ничего делать не нужно. Когда она будет опубликована, "
                  "CI сам повторит выкладку и закроет этот Issue.")
    else:
        status = ("Сейчас: на модерации ничего нет, а версия в магазине отсутствует - CI повторил выкладку сам, но она не прошла. "
                  "Проверьте состояние версии в консоли RuStore.")
    return (f"RuStore не принял версию {version} через API: магазин модерирует прошлую версию, новая ждёт её публикации.\n\n{status}\n\n"
            f"<!-- rustore code={code} after={live} reason=busy -->")


def _upsert_issue(token, title, body):
    """Один Issue на версию: новый или обновление открытого с тем же заголовком."""
    existing = next((i for i in _open_issues(token) if i["title"] == title), None)
    if existing:
        net.send(None, "PATCH", f"{API}/repos/{CLIENT_REPO}/issues/{existing['number']}", json={"body": body}, headers=_headers(token), timeout=60).raise_for_status()
    else:
        net.send(None, "POST", f"{API}/repos/{CLIENT_REPO}/issues", json={"title": title, "body": body}, headers=_headers(token), timeout=60).raise_for_status()


def _summary_line(line, error=False):
    """Строка в сводку прогона и в журнал: красная - потеря видна сразу."""
    marker = "::error::" if error else "::warning::"
    summary = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if summary:
        with open(summary, "a", encoding="utf-8") as file:
            file.write(f"### {marker}{line}\n")
    say(f"{marker}{line}")


def note(version, url, state_path):
    """Issue на версию, которую магазин не принял из-за нового чувствительного разрешения: нужна ручная загрузка."""
    with open(state_path, encoding="utf-8") as file:
        state = json.load(file)
    token = _issue_token()
    title = TITLE.format(version)
    _upsert_issue(token, title, _body(version, url, state["code"], state["live"], state["waiting"]))
    line = (f"RuStore: {version} ждёт публикации прошлой версии - выкладка повторится сама" if state["waiting"]
            else f"RuStore: {version} нужна ручная загрузка в консоли (Issue «{title}»)")
    _summary_line(line)


def wait(version, state_path):
    """Issue на версию, которую магазин не принял из-за модерации прошлой версии: выкладка повторится сама."""
    with open(state_path, encoding="utf-8") as file:
        state = json.load(file)
    token = _issue_token()
    title = TITLE.format(version)
    _upsert_issue(token, title, _wait_body(version, state["code"], state["live"], state["waiting"]))
    _summary_line(f"RuStore: {version} ждёт публикации прошлой версии - выкладка повторится сама (Issue «{title}»)", error=True)


def _dispatch_stores():
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    response = net.send(None, "POST", f"{API}/repos/{repo}/actions/workflows/client.yml/dispatches", json={"ref": "main", "inputs": {"mode": "stores"}},
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
    versions = [v for v in store.versions() if status_of(v) != "DRAFT"]
    for v in versions:
        say(f"RUSTORE: version {v.get('versionName')} code {v.get('versionCode')} id {v.get('versionId')} {v.get('versionStatus')}")
    sent = [v for v in versions if status_of(v) in SUBMITTED]
    present = {int(v["versionCode"]) for v in sent if int(v.get("versionCode") or 0) > 0}
    names = {str(v.get("versionName")) for v in sent}
    dispatched = False
    for issue in issues:
        mark = MARK_RE.search(issue.get("body") or "")
        if not mark:
            continue
        code, after = int(mark.group(1)), int(mark.group(2))
        reason = mark.group(3)
        version = TITLE_RE.match(issue["title"]).group(1)
        if any(c >= code for c in present) or version in names:
            net.send(None, "PATCH", f"{API}/repos/{CLIENT_REPO}/issues/{issue['number']}", json={"state": "closed", "state_reason": "completed"},
                           headers=_headers(token), timeout=60).raise_for_status()
            say(f"RUSTORE: {version} is in the store, manual-upload Issue closed")
        elif waiting:
            say(f"RUSTORE: {version} waits for the moderation of the previous version")
        elif live > after and not dispatched:
            _dispatch_stores()
            dispatched = True
            body = MARK_RE.sub(f"<!-- rustore code={code} after={live} reason={reason} -->", issue["body"])
            net.send(None, "PATCH", f"{API}/repos/{CLIENT_REPO}/issues/{issue['number']}", json={"body": body}, headers=_headers(token), timeout=60).raise_for_status()
            say(f"RUSTORE: previous version is live, client.yml stores started again for {version}")
        else:
            say(f"::warning::RUSTORE: {version} still needs a manual upload in the console")
    if issues or latest is None:
        return
    # Очередь: свежий релиз ждал модерации прошлой версии - магазин освободился, отправляем его (промежуточные пропускаются)
    code, name = int(latest["versionCode"]), latest["versionName"]
    status = {int(v.get("versionCode") or 0): status_of(v) for v in versions}
    if status.get(code) in REFUSED:
        say(f"::warning::RUSTORE: {name} was refused by the store review, it is not sent again")
    elif code not in present and name not in names:
        if waiting:
            say(f"::warning::RUSTORE: {name} waits for the moderation of the previous version")
        else:
            _dispatch_stores()
            say(f"RUSTORE: the store is free, client.yml stores started for {name}")


def main():
    if len(sys.argv) == 5 and sys.argv[1] == "note":
        note(sys.argv[2], sys.argv[3], sys.argv[4])
    elif len(sys.argv) == 4 and sys.argv[1] == "wait":
        wait(sys.argv[2], sys.argv[3])
    else:
        sys.exit("usage: rustore_manual.py note <versionName> <apk url> <state.json> | wait <versionName> <state.json>")


if __name__ == "__main__":
    main()
