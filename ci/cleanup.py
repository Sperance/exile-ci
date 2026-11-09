"""Чистка платного хранилища GitHub (.github/workflows/maintenance.yml, задача cleanup): артефакты Actions приватных репозиториев и старые образы сервера.

Бесплатный лимит хранилища аккаунта - 0,5 ГБ, а считаются в нём только приватные репозитории: прежние прогоны ExileForge и
ktor-bestgame (до переезда CI в exile-ci) оставили по debug APK на прогон. Новые прогоны там артефактов не создают, поэтому
артефакты этих репозиториев удаляются все. Образы GHCR: живут версия с именованным тегом (ветка) и SERVER_KEEP последних
проверенных (тег :<sha>); черновые (только :build-<sha>) и безымянные старше суток удаляются - сутки покрывают идущий server.yml.
Предрелизы тестовой сборки клиента qa-<n> этого репозитория: живут QA_KEEP новейших по номеру, старшие удаляются (job `qa-release` client.yml).

Только стандартная библиотека; в публичный журнал (say) - лишь счётчики и коды ответов, без тегов и имён артефактов.
Записи о тестовом стенде stand-<UTC> (ci/test-stand.sh): живут STAND_KEEP новейших по имени.
Кэш Actions этого репозитория (`caches`): лимит GitHub - 10 ГБ, при его достижении вытесняются самые давние, в том числе нужные (Playwright, снимок эмулятора);
записи gradle-home пишутся на каждый коммит. Трогаются только записи с хэшем в ключе (по коммиту или дереву: gradle-home, client-green); записи без хэша (Playwright, снимок эмулятора, состояние поста Telegram) не удаляются никогда. Живут записи, к которым обращались за CACHE_IDLE_DAYS суток; от каждого семейства ключей (хэши в ключе заменены на #)
остаются CACHE_FAMILY_KEEP новейших; если и тогда сумма больше CACHE_BUDGET_BYTES, удаляются самые давно использованные, кроме новейшей записи каждого семейства.
Токен - workflow (job `caches` maintenance.yml, единственный с actions: write). В журнал - только счётчики и мегабайты, без ключей.
Использование: ci/cleanup.py artifacts | images | qa-releases | stand-releases | caches
"""
import json
import os
import re
import sys
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from store_common import fail, say
import net

API = "https://api.github.com"
PRIVATE_REPOS = ("Sperance/ExileForge", "Sperance/ktor-bestgame")
PACKAGE = "/users/Sperance/packages/container/ktor-bestgame"
SERVER_KEEP = 5
QA_KEEP = 5
QA_TAG = re.compile(r"^qa-([0-9]+)$")
STAND_KEEP = 10
STAND_TAG = re.compile(r"^stand-[0-9]{8}T[0-9]{6}Z$")
CACHE_IDLE_DAYS = 5
CACHE_FAMILY_KEEP = 2
CACHE_BUDGET_BYTES = 8 * 2**30
CACHE_HASH = re.compile(r"[0-9a-f]{16,}")
DRAFT_AGE = timedelta(days=1)
SHA_TAG = re.compile(r"^(build-)?[0-9a-f]{40}$")
# Удаления параллельно: по одному тысячи старых артефактов не укладывались в срок шага
WORKERS = 8


class GitHub:
    """REST GitHub одним токеном: постраничное чтение и удаление."""

    def __init__(self, token):
        self.token = token

    def request(self, method, url):
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            response = net.fetch(url if url.startswith("https://") else API + url, method=method, headers=headers, timeout=30)
            return response.status, json.loads(response.body) if response.body else None, response.headers.get("Link", "")
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


def doomed_qa_releases(releases):
    """Предрелизы qa-<n> на удаление: все, кроме QA_KEEP с наибольшим номером (номер - число коммитов рабочей ветки клиента)."""
    qa = [r for r in releases if r["prerelease"] and QA_TAG.match(r["tag_name"])]
    qa.sort(key=lambda r: int(QA_TAG.match(r["tag_name"]).group(1)), reverse=True)
    return qa[QA_KEEP:]


def clean_qa_releases():
    github = GitHub(os.environ["GITHUB_TOKEN"])
    repo = os.environ["GITHUB_REPOSITORY"]
    doomed = doomed_qa_releases(list(github.pages(f"/repos/{repo}/releases")))
    failed = [code for code in github.delete_all(f"/repos/{repo}/releases/{r['id']}" for r in doomed) if code not in (204, 404)]
    github.delete_all(f"/repos/{repo}/git/refs/tags/{r['tag_name']}" for r in doomed)
    say(f"test builds: {len(doomed) - len(failed)} of {len(doomed)} old prereleases deleted, {QA_KEEP} newest kept")
    if failed:
        fail(f"test builds: {len(failed)} deletions refused (codes {sorted(set(failed))})")


def doomed_stand_releases(releases):
    """Записи stand-<UTC> на удаление: все, кроме STAND_KEEP новейших (имя сортируется по времени выката)."""
    stand = sorted((r for r in releases if r["prerelease"] and STAND_TAG.match(r["tag_name"])), key=lambda r: r["tag_name"], reverse=True)
    return stand[STAND_KEEP:]


def clean_stand_releases():
    github = GitHub(os.environ["GITHUB_TOKEN"])
    repo = os.environ["GITHUB_REPOSITORY"]
    doomed = doomed_stand_releases(list(github.pages(f"/repos/{repo}/releases")))
    failed = [code for code in github.delete_all(f"/repos/{repo}/releases/{r['id']}" for r in doomed) if code not in (204, 404)]
    github.delete_all(f"/repos/{repo}/git/refs/tags/{r['tag_name']}" for r in doomed)
    say(f"test stand records: {len(doomed) - len(failed)} of {len(doomed)} old records deleted, {STAND_KEEP} newest kept")
    if failed:
        fail(f"test stand records: {len(failed)} deletions refused (codes {sorted(set(failed))})")


def cache_family(key):
    return CACHE_HASH.sub("#", key)


def cache_time(cache):
    return datetime.fromisoformat(cache["last_accessed_at"].replace("Z", "+00:00"))


def doomed_caches(caches, now):
    """Записи кэша на удаление: давно не использованные, сверх CACHE_FAMILY_KEEP в семействе, затем самые давние сверх бюджета (новейшая записи семейства неприкосновенна)."""
    by_family = {}
    for cache in sorted((c for c in caches if CACHE_HASH.search(c["key"])), key=cache_time, reverse=True):
        by_family.setdefault(cache_family(cache["key"]), []).append(cache)
    doomed = []
    kept = []
    for family in by_family.values():
        for index, cache in enumerate(family):
            idle = now - cache_time(cache) > timedelta(days=CACHE_IDLE_DAYS)
            (doomed if idle or index >= CACHE_FAMILY_KEEP else kept).append(cache)
    total = sum(cache["size_in_bytes"] for cache in kept)
    newest = {family[0]["id"] for family in by_family.values()}
    for cache in sorted(kept, key=cache_time):
        if total <= CACHE_BUDGET_BYTES:
            break
        if cache["id"] not in newest:
            doomed.append(cache)
            total -= cache["size_in_bytes"]
    return doomed


def clean_caches():
    github = GitHub(os.environ["GITHUB_TOKEN"])
    repo = os.environ["GITHUB_REPOSITORY"]
    caches = list(github.pages(f"/repos/{repo}/actions/caches", "actions_caches"))
    doomed = doomed_caches(caches, datetime.now(timezone.utc))
    failed = [code for code in github.delete_all(f"/repos/{repo}/actions/caches/{c['id']}" for c in doomed) if code not in (204, 404)]
    left = sum(c["size_in_bytes"] for c in caches) - sum(c["size_in_bytes"] for c in doomed)
    say(f"actions cache: {len(caches)} entries, {len(doomed) - len(failed)} deleted, about {left / 2**20:.0f} MB left")
    if failed:
        fail(f"actions cache: {len(failed)} deletions refused (codes {sorted(set(failed))}) - the job needs actions: write")


if __name__ == "__main__":
    {"artifacts": clean_artifacts, "images": clean_images, "qa-releases": clean_qa_releases, "stand-releases": clean_stand_releases, "caches": clean_caches}[sys.argv[1]]()
