"""Общее для скриптов магазинов (ci/play.py, ci/rustore.py, ci/store-status.py): только стандартная библиотека.

Журналы этого репозитория публичны, а скрипты запускает ci/quiet.sh: весь вывод уходит в зашифрованный журнал упавшего шага. В
публичный журнал попадает только то, что скрипт сам пишет в файл $PUBLIC_NOTES функцией [say] - короткие строки без данных (канал,
версия, доля выкладки, код ответа); шаг workflow печатает файл после запуска.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

REPORT_PATH = "/api/v1/admin/release/channels"
CHANNELS = ("DIRECT", "PLAY", "RUSTORE")


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


def short_notes(text, limit):
    """Заметки не длиннее limit знаков: обрезка по границе строки или слова, с многоточием."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    boundary = max(cut.rfind("\n"), cut.rfind(" "))
    if boundary > limit // 2:
        cut = cut[:boundary]
    return cut.rstrip() + "…"


def build_entry(version_code, version_name, revision, availability, published_at=0, rules=0):
    """ReportedBuild сервера (rules/.../wire/release/ReleaseWire.kt)."""
    return {"versionCode": int(version_code), "versionName": version_name, "revision": int(revision),
            "availability": float(availability), "publishedAt": int(published_at), "rules": int(rules)}


def server_ready():
    """Есть ли куда и с чем слать отчёты: адрес сервера (переменная SERVER_URL) и секрет RELEASE_STATUS_TOKEN."""
    return bool(os.environ.get("SERVER_URL", "").strip() and os.environ.get("RELEASE_STATUS_TOKEN", "").strip())


def post_report(channel, active, build=None, attempts=1, pause=30):
    """ChannelStatusReport на сервер (POST admin/release/channels, заголовок X-Release-Token). Повтор того же отчёта ничего не меняет.
    В исключении - только код ответа: тело ответа и адрес в журнал не идут."""
    body = {"channel": channel, "active": bool(active), "build": build}
    url = os.environ["SERVER_URL"].strip().rstrip("/") + REPORT_PATH
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "X-Release-Token": os.environ["RELEASE_STATUS_TOKEN"].strip()})
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                response.read()
            return
        except urllib.error.HTTPError as error:
            problem = f"HTTP {error.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            problem = type(error).__name__
        if attempt == attempts:
            raise RuntimeError(f"report of {channel} refused: {problem}")
        time.sleep(pause)
