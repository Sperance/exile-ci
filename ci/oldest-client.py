#!/usr/bin/env python3
"""Самый старый клиент, что сервер ещё обязан поддерживать (job `compat` в server.yml): релиз exile-ci с наименьшей версией, чья
ревизия API не ниже зерна окна MIN_API_REVISION сервера и не выше его API_REVISION. Тег релиза exile-ci vX.Y.Z - и тег
приватного ExileForge (job `release` client.yml создаёт его на коммите клиента), поэтому по нему и берётся коммит клиента.

    python3 ci/oldest-client.py <Protocol.kt сервера>
Окружение: GITHUB_REPOSITORY (релизы), GITHUB_TOKEN (необязательно), SOURCE_TOKEN (проверить, что тег есть в приватном ExileForge),
GITHUB_OUTPUT. Результат - строка `tag=` в $GITHUB_OUTPUT: пусто, если старее нового клиента в окне нет (поддерживать нечего).
Вывод перехватывает ci/quiet.sh; в публичный журнал - $PUBLIC_NOTES.
"""
import json
import os
import re
import subprocess
import sys
import urllib.request

from store_common import fail, say

CLIENT_REPO = "Sperance/ExileForge"
SCAN = 60


def get_json(url, token=None):
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
        return json.load(response)


def revisions(protocol):
    """(MIN_API_REVISION, API_REVISION) из Protocol.kt; зерно может быть числом или выражением `API_REVISION` (выпуск, что вводит окно)."""
    text = open(protocol, encoding="utf-8").read()
    api = re.search(r"^const val API_REVISION = (\d+)", text, re.M)
    low = re.search(r"^const val MIN_API_REVISION = (\d+|API_REVISION)\b", text, re.M)
    if not (api and low):
        fail("API_REVISION or MIN_API_REVISION not found in Protocol.kt")
    api = int(api.group(1))
    return (api if low.group(1) == "API_REVISION" else int(low.group(1))), api


def has_client_tag(tag):
    token = os.environ.get("SOURCE_TOKEN", "")
    if not token:
        return True
    url = f"https://x-access-token:{token}@github.com/{CLIENT_REPO}.git"
    return subprocess.run(["git", "ls-remote", "--exit-code", "--tags", url, f"refs/tags/{tag}"], capture_output=True).returncode == 0


def main():
    low, api = revisions(sys.argv[1])
    repo = os.environ.get("GITHUB_REPOSITORY", "Sperance/exile-ci")
    token = os.environ.get("GITHUB_TOKEN")
    releases = [r for r in get_json(f"https://api.github.com/repos/{repo}/releases?per_page={SCAN}", token)
                if not r.get("draft") and not r.get("prerelease")]
    window = []
    for release in releases:  # от новых к старым: ревизия со временем не убывает, дальше окна идти незачем
        asset = next((a for a in release.get("assets", []) if a["name"] == "update.json"), None)
        if not asset:
            continue
        revision = int(get_json(asset["browser_download_url"]).get("apiRevision", 0))
        if revision < low:
            break
        if revision <= api:
            window.append(release["tag_name"])
    tag = next((t for t in reversed(window) if has_client_tag(t)), "")
    if tag:
        say(f"oldest supported client: {tag} (window {low}..{api}, {len(window)} release(s) in it)")
    else:
        say(f"::notice::no released client in the revision window {low}..{api} has a source tag: compat check skipped")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
        out.write(f"tag={tag}\n")


main()
