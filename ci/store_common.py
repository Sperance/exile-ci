"""Общее для скриптов магазинов (ci/play.py, ci/rustore.py, ci/store-status.py): только стандартная библиотека.

Журналы этого репозитория публичны, а скрипты запускает ci/quiet.sh: весь вывод уходит в зашифрованный журнал упавшего шага. В
публичный журнал попадает только то, что скрипт сам пишет в файл $PUBLIC_NOTES функцией [say] - короткие строки без данных (канал,
версия, доля выкладки, код ответа); шаг workflow печатает файл после запуска.
"""
import json
import os
import re
import sys
import urllib.error
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import net
import notes
from net import get_json

REPORT_PATH = "/api/v1/admin/release/channels"
CHANNELS = ("DIRECT", "PLAY", "RUSTORE")
RELEASES_SCAN = 30


def say(message):
    """Строка для публичного журнала (и в обычный вывод, который перехватывает ci/quiet.sh)."""
    print(message, flush=True)
    path = os.environ.get("PUBLIC_NOTES")
    if path:
        with open(path, "a", encoding="utf-8") as notes:
            notes.write(message + "\n")


def fail(message):
    say(f"::error::{message}")
    sys.exit(1)


def load_update(path):
    """update.json релиза: versionCode, versionName, apiRevision, rules, notes и остальное, что читает игра."""
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def public_notes(text):
    """Заметки для магазина (ci/notes.py): первые пункты «Нового» (нет их - остальные публичные), без «Техническое», обязательности
    и пунктов сервера. Заметки без подразделов (прежний вид) - все пункты, кроме «Техническое: …». В update.json для клиента
    заметки остаются целиком."""
    parsed = notes.parse(text)
    if parsed.items(""):
        lines = [line for line in re.sub(r"<!--.*?(-->|$)", "", text, flags=re.DOTALL).splitlines()
                 if not re.match(r"^\s*(?:[-*]\s+)?Техническое:", line)]
        return "\n".join(lines).strip()
    return "\n".join(f"- {item}" for item in notes.store_items(parsed))


def short_notes(text, limit):
    """Публичные заметки (public_notes) не длиннее limit знаков: обрезка по границе строки или слова, с многоточием."""
    text = public_notes(text)
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    boundary = max(cut.rfind("\n"), cut.rfind(" "))
    if boundary > limit // 2:
        cut = cut[:boundary]
    return cut.rstrip() + "…"


def build_entry(version_code, version_name, revision, availability, published_at=0, rules=0, content_schema=None, mandatory=None):
    """ReportedBuild сервера (rules/.../wire/release/ReleaseWire.kt). Форма контента и обязательность необязательны: релиз без них
    (старый update.json) их не присылает, а сервер, что их не знает, лишние поля отбрасывает (ignoreUnknownKeys)."""
    entry = {"versionCode": int(version_code), "versionName": version_name, "revision": int(revision),
             "availability": float(availability), "publishedAt": int(published_at), "rules": int(rules)}
    if content_schema is not None:
        entry["contentSchema"] = int(content_schema)
    if mandatory is not None:
        entry["mandatory"] = bool(mandatory)
    return entry


def parse_time(text):
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)


class Catalog:
    """Релизы exile-ci: для каждого - update.json (versionCode, versionName, apiRevision, rules, contentSchema) и время выхода. Нужны,
    чтобы отчёту о сборке магазина дать ревизию и правила: магазин их не знает."""

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


def server_ready():
    """Есть ли куда и с чем слать отчёты: адрес сервера (переменная SERVER_URL) и секрет RELEASE_STATUS_TOKEN."""
    return bool(os.environ.get("SERVER_URL", "").strip() and os.environ.get("RELEASE_STATUS_TOKEN", "").strip())


def post_report(channel, active, build=None, attempts=1, pause=30):
    """ChannelStatusReport на сервер (POST admin/release/channels, заголовок X-Release-Token). Повтор того же отчёта ничего не меняет.
    В исключении - только код ответа: тело ответа и адрес в журнал не идут."""
    body = {"channel": channel, "active": bool(active), "build": build}
    url = os.environ["SERVER_URL"].strip().rstrip("/") + REPORT_PATH
    headers = {"Content-Type": "application/json", "X-Release-Token": os.environ["RELEASE_STATUS_TOKEN"].strip()}
    try:
        net.fetch(url, method="POST", data=json.dumps(body).encode(), headers=headers, timeout=30, mode=net.IDEMPOTENT, delays=(pause,) * (attempts - 1))
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"report of {channel} refused: HTTP {error.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise RuntimeError(f"report of {channel} refused: {type(error).__name__}") from None
