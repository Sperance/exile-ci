#!/usr/bin/env python3
"""Ожидание сервера перед выкладкой в магазин: сборка с ревизией N не должна дойти до игроков раньше сервера, который на ней говорит
(иначе «клиент впереди сервера» и игра не пускает). Опрашивает публичный манифест `${SERVER_URL}/static/index.json` (поле `revision`),
пока оно не станет не меньше `apiRevision` из update.json релиза.

    python3 ci/wait-server.py <update.json>

Окружение: SERVER_URL (нет - ошибка: без ожидания защита от выкладки раньше сервера не работает), WAIT_MINUTES (по умолчанию 30).
Не дождались - код 1 и строка ::error::. В журнал идут только короткие строки: адрес сервера и тело ответа не печатаются.
"""
import json
import os
import sys
import time
import urllib.error

import net
from store_common import fail, load_update, say

POLL_SECONDS = 30
REPORT_EVERY = 10


def server_revision(base):
    """Ревизия, что сервер объявляет в манифесте; None - манифест не отдан или не разобран."""
    try:
        response = net.fetch(base + "/static/index.json", headers={"Accept": "application/json"}, timeout=20, delays=())
        return int(json.loads(response.body)["revision"])
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, TypeError):
        return None


def main():
    if len(sys.argv) != 2:
        fail("usage: wait-server.py <update.json>")
    base = os.environ.get("SERVER_URL", "").strip().rstrip("/")
    if not base:
        fail("SERVER_URL is not set: the store upload cannot wait for the server")
    needed = int(load_update(sys.argv[1])["apiRevision"])
    deadline = time.monotonic() + int(os.environ.get("WAIT_MINUTES", "30")) * 60
    polls = 0
    while True:
        revision = server_revision(base)
        if revision is not None and revision >= needed:
            say(f"Server speaks API {revision}, the build needs {needed}: uploading")
            return
        if polls % REPORT_EVERY == 0:
            say(f"Waiting for the server: API {revision if revision is not None else 'unknown'}, the build needs {needed}")
        polls += 1
        if time.monotonic() + POLL_SECONDS > deadline:
            fail(f"The server did not reach API {needed} in time: the store upload is held, rerun the job after the server deploy")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
