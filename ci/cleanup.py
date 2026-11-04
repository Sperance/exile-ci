"""Чистка платного хранилища GitHub (.github/workflows/cleanup.yml): артефакты Actions приватных репозиториев и старые образы сервера.

Бесплатный лимит хранилища аккаунта - 0,5 ГБ, а считаются в нём только приватные репозитории: прежние прогоны ExileForge и
ktor-bestgame (до переезда CI в exile-ci) оставили по debug APK на прогон. Новые прогоны там артефактов не создают, поэтому
артефакты этих репозиториев удаляются все. Образы GHCR: живут версия с именованным тегом (ветка) и SERVER_KEEP последних
проверенных (тег :<sha>); черновые (только :build-<sha>) и безымянные старше суток удаляются - сутки покрывают идущий server.yml.

Только стандартная библиотека; в публичный журнал (say) - лишь счётчики и коды ответов, без тегов и имён артефактов.
Использование: ci/cleanup.py artifacts | images
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from store_common import fail, say

API = "https://api.github.com"
PRIVATE_REPOS = ("Sperance/ExileForge", "Sperance/ktor-bestgame")
PACKAGE = "/users/Sperance/packages/container/ktor-bestgame"
SERVER_KEEP = 5
DRAFT_AGE = timedelta(days=1)
SHA_TAG = re.compile(r"^(build-)?[0-9a-f]{40}$")
# Удаления параллельно: по одному тысячи старых артефактов не укладывались в срок шага
WORKERS = 8


class GitHub:
    """REST GitHub одним токеном: постраничное чтение и удаление."""

    def __init__(self, token):
        self.token = token

    def request(self, method, url):
        request = urllib.request.Request(url if url.startswith("https://") else API + url, method=method, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
                return response.status, json.loads(body) if body else None, response.headers.get("Link", "")
        except urllib.error.HTTPError as error:
            return error.code, None, ""

    def pages(self, path, key=None):
        """Все элементы списка: key - поле с массивом в ответе (у артефактов), иначе ответ сам массив."""
        url = f"{path}?per_page=100"
        while url:
            status, body, link = self.request("GET", url)
            if status != 200:
                fail(f"listing {path.rsplit('/', 1)[-1]} answered {status}")
            yield from (body[key] if key else body)
            url = next((part.split(";")[0].strip(" <>") for part in link.split(",") if 'rel="next"' in part), None)

    def delete(self, path):
        return self.request("DELETE", path)[0]

    def delete_all(self, paths):
        """Коды ответов на удаление каждого пути; 204 - удалено, 404 - уже нет (прерванный прежний прогон)."""
        with ThreadPoolExecutor(WORKERS) as pool:
            return list(pool.map(self.delete, paths))


def clean_artifacts():
    token = os.environ.get("CLEANUP_TOKEN", "").strip()
    if not token:
        say("::warning::CLEANUP_TOKEN is not set: artifacts of the private repositories are not cleaned")
        return
    github = GitHub(token)
    for repo in PRIVATE_REPOS:
        name = repo.split("/")[1]
        artifacts = [a for a in github.pages(f"/repos/{repo}/actions/artifacts", "artifacts") if not a["expired"]]
        size = sum(a["size_in_bytes"] for a in artifacts)
        failed = [code for code in github.delete_all(f"/repos/{repo}/actions/artifacts/{a['id']}" for a in artifacts) if code not in (204, 404)]
        say(f"{name}: {len(artifacts) - len(failed)} of {len(artifacts)} artifacts deleted, {size / 2**20:.0f} MB")
        if failed:
            fail(f"{name}: {len(failed)} deletions refused (codes {sorted(set(failed))}) - CLEANUP_TOKEN needs Actions: Read and write")


def doomed_versions(versions, now):
    """Версии образа на удаление: всё, кроме именованных тегов и SERVER_KEEP новейших проверенных; черновые и безымянные - со стажем."""
    checked = 0
    doomed = []
    for version in sorted(versions, key=lambda v: v["created_at"], reverse=True):
        tags = version["metadata"]["container"]["tags"]
        if any(not SHA_TAG.match(tag) for tag in tags):
            continue
        if any(not tag.startswith("build-") for tag in tags):
            checked += 1
            if checked <= SERVER_KEEP:
                continue
        elif now - datetime.fromisoformat(version["created_at"].replace("Z", "+00:00")) < DRAFT_AGE:
            continue
        doomed.append(version)
    return doomed


def clean_images():
    github = GitHub(os.environ["GITHUB_TOKEN"])
    versions = list(github.pages(f"{PACKAGE}/versions"))
    doomed = doomed_versions(versions, datetime.now(timezone.utc))
    failed = [code for code in github.delete_all(f"{PACKAGE}/versions/{v['id']}" for v in doomed) if code not in (204, 404)]
    say(f"server images: {len(doomed) - len(failed)} of {len(doomed)} old versions deleted, {len(versions) - len(doomed) + len(failed)} kept")
    if failed:
        fail(f"server images: {len(failed)} deletions refused (codes {sorted(set(failed))}) - "
             "give exile-ci the Admin role in the package's Manage Actions access")


if __name__ == "__main__":
    {"artifacts": clean_artifacts, "images": clean_images}[sys.argv[1]]()
