#!/usr/bin/env python3
"""Отчёты CI серверу о каналах выкладки клиента (ChannelStatusReport, POST admin/release/channels) и доводка выкладки Play до 100%.

    python3 ci/store-status.py all                  - раз в час (store-status.yml): DIRECT по последнему релизу exile-ci, PLAY и RUSTORE
                                                      по состоянию магазинов; канал без ключей пропускается, как будто его нет;
    python3 ci/store-status.py direct <update.json> - сразу после публикации релиза (client.yml): прямой канал, долей 1.0; сервер ещё
                                                      может не знать маршрута (его выкатывает следующий деплой) - тогда лишь
                                                      предупреждение, отчёт повторит почасовой запуск.

Окружение: SERVER_URL и RELEASE_STATUS_TOKEN (нет любого - отчётов нет, прогон зелёный), PLAY_SERVICE_ACCOUNT_JSON, RUSTORE_KEY_ID,
RUSTORE_PRIVATE_KEY, EXILEFORGE_TOKEN (проверка падений), GITHUB_TOKEN, GITHUB_REPOSITORY, APP_ID. Вывод перехватывает ci/quiet.sh.
Выкладка Play: сборка на 20% не меньше суток, падений `crash`+`auto` с её выхода не больше CRASH_LIMIT - выкладка идёт на 100%.
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime

from store_common import build_entry, load_update, post_report, say, server_ready

PROMOTE_AFTER_MS = 24 * 3600 * 1000
CRASH_LIMIT = 3
CLIENT_REPO = "Sperance/ExileForge"
RELEASES_SCAN = 30


def get_json(url, token=None):
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
        return json.load(response)


def parse_time(text):
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)


class Catalog:
    """Релизы exile-ci: для каждого - update.json (versionCode, versionName, apiRevision, rules) и время выхода. Нужны, чтобы
    отчёту о сборке магазина дать ревизию и правила: магазин их не знает."""

    def __init__(self):
        repo = os.environ.get("GITHUB_REPOSITORY", "Sperance/exile-ci")
        listing = get_json(f"https://api.github.com/repos/{repo}/releases?per_page={RELEASES_SCAN}", os.environ.get("GITHUB_TOKEN"))
        self.pending = [r for r in listing if not r.get("draft") and not r.get("prerelease")]
        self.entries = []

    def _load_next(self):
        release = self.pending.pop(0)
        asset = next((a for a in release.get("assets", []) if a["name"] == "update.json"), None)
        if asset:
            update = get_json(asset["browser_download_url"])
            update["publishedAt"] = parse_time(release["published_at"])
            self.entries.append(update)

    def latest(self):
        while not self.entries and self.pending:
            self._load_next()
        return self.entries[0] if self.entries else None

    def by_code(self, version_code):
        """Релиз с таким versionCode среди последних RELEASES_SCAN или None."""
        index = 0
        while True:
            while index < len(self.entries):
                if int(self.entries[index]["versionCode"]) == int(version_code):
                    return self.entries[index]
                index += 1
            if not self.pending:
                return None
            self._load_next()


def entry_build(update, availability, published_at=None):
    return build_entry(update["versionCode"], update["versionName"], update["apiRevision"], availability,
                       update.get("publishedAt", 0) if published_at is None else published_at, update.get("rules", 0))


def report_direct(update, attempts=1):
    post_report("DIRECT", True, entry_build(update, 1.0), attempts=attempts)
    say(f"DIRECT: {update['versionName']} reported at 100%")


def crash_count(since_ms):
    """Открытые Issues ExileForge с метками crash и auto, созданные после since_ms. None - проверить нельзя (нет токена)."""
    token = os.environ.get("EXILEFORGE_TOKEN", "").strip()
    if not token:
        return None
    count, page = 0, 1
    while True:
        issues = get_json(f"https://api.github.com/repos/{CLIENT_REPO}/issues?labels=crash,auto&state=open&per_page=100&page={page}", token)
        count += sum(1 for i in issues if "pull_request" not in i and parse_time(i["created_at"]) >= since_ms)
        if len(issues) < 100:
            return count
        page += 1


def report_play(catalog):
    from play import Play

    play = Play(os.environ["PLAY_SERVICE_ACCOUNT_JSON"], os.environ["APP_ID"])
    release = play.production()
    if release is None:
        post_report("PLAY", True)
        say("PLAY: no release in production yet")
        return
    code = max(int(c) for c in release["versionCodes"])
    status = release.get("status", "")
    update = catalog.by_code(code)
    if status == "completed":
        availability = 1.0
    elif status == "inProgress":
        availability = float(release.get("userFraction", 0.0))
    else:
        availability = 0.0
    if update is None:
        post_report("PLAY", True)
        say(f"::warning::PLAY: version code {code} has no exile-ci release, only the channel state is reported")
        return
    if status == "inProgress" and availability < 1.0:
        age = int(time.time() * 1000) - update["publishedAt"]
        if age < PROMOTE_AFTER_MS:
            say(f"PLAY: {update['versionName']} at {availability:.0%}, {age // 3600000} h since the release, waiting for 24 h")
        else:
            crashes = crash_count(update["publishedAt"])
            if crashes is None:
                say("::notice::PLAY: promotion held: EXILEFORGE_TOKEN is missing, crashes cannot be checked")
            elif crashes > CRASH_LIMIT:
                say(f"::warning::PLAY: promotion to 100% halted: {crashes} open crash reports since the release (limit {CRASH_LIMIT})")
            else:
                play.promote(release)
                availability = 1.0
                say(f"PLAY: {update['versionName']} promoted to 100% ({crashes} open crash reports)")
    post_report("PLAY", True, entry_build(update, availability))
    say(f"PLAY: {update['versionName']} reported at {availability:.0%}")


def report_rustore(catalog):
    from rustore import RuStore

    store = RuStore(os.environ["RUSTORE_KEY_ID"].strip(), os.environ["RUSTORE_PRIVATE_KEY"], os.environ["APP_ID"])
    version = store.newest()
    if version is None:
        post_report("RUSTORE", True)
        say("RUSTORE: no versions yet")
        return
    update = catalog.by_code(version["versionCode"])
    if update is None:
        post_report("RUSTORE", True)
        say(f"::warning::RUSTORE: version code {version['versionCode']} has no exile-ci release, only the channel state is reported")
        return
    availability = store.availability(version)
    post_report("RUSTORE", True, entry_build(update, availability))
    say(f"RUSTORE: {update['versionName']} status {version.get('versionStatus')}, reported at {availability:.0%}")


def run_all():
    catalog = Catalog()
    problems = 0
    channels = [("DIRECT", True, lambda: report_direct(catalog.latest()) if catalog.latest() else post_report("DIRECT", True)),
                ("PLAY", bool(os.environ.get("PLAY_SERVICE_ACCOUNT_JSON", "").strip()), lambda: report_play(catalog)),
                ("RUSTORE", bool(os.environ.get("RUSTORE_KEY_ID", "").strip() and os.environ.get("RUSTORE_PRIVATE_KEY", "").strip()),
                 lambda: report_rustore(catalog))]
    for name, enabled, action in channels:
        if not enabled:
            say(f"{name}: no store keys, channel skipped")
            continue
        try:
            action()
        except Exception as error:  # один канал не мешает остальным; подробности - в зашифрованном журнале
            problems += 1
            say(f"::error::{name}: failed ({type(error).__name__})")
            import traceback
            traceback.print_exc()
    return problems


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if not server_ready():
        say("::notice::SERVER_URL or RELEASE_STATUS_TOKEN is not set: channel reports are off")
        return
    if mode == "direct":
        try:
            update = load_update(sys.argv[2])
            update["publishedAt"] = int(time.time() * 1000)
            report_direct(update, attempts=3)
        except RuntimeError as error:
            say(f"::warning::DIRECT report not delivered ({error}); the hourly store-status run repeats it")
    elif mode == "all":
        sys.exit(1 if run_all() else 0)
    else:
        sys.exit("usage: store-status.py all | direct <update.json>")


if __name__ == "__main__":
    main()
