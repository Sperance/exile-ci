"""Сетевые вызовы Python-скриптов CI - только через этот модуль (сторож ci/guard-network.py падает на голые urlopen и requests).

Близнец ci/retry.sh: те же режимы и те же правила, паузы между повторами 5, 10, 20 с (до 4 попыток; delays=() - одна попытка, когда
вызывающий сам опрашивает в цикле):
  READ        чтение: повторяются ответы 5xx, таймауты, обрывы и сбои соединения.
  IDEMPOTENT  запись, повтор которой даёт то же состояние (правка метки, commit status, editMessageText): повторяется, как READ.
  ONCE        запись, которую нельзя повторять вслепую (sendMessage, создание Issue, релиза, запуск workflow): повтор только когда сбой
              доказывает, что запрос не дошёл - имя не найдено или соединение отклонено до отправки. Ответ 5xx, таймаут и обрыв после
              отправки ошибку не снимают.
Режим по умолчанию - по методу: GET и HEAD читают (READ), PUT, PATCH и DELETE идемпотентны (IDEMPOTENT), POST - ONCE; POST, чей повтор безвреден
(выдача токена, правка), называет режим явно. Тело-файл (data=<файл>) - только ONCE: повтор не перемотает его.
Отказ по существу (4xx) возвращается сразу. Исключения те же, что у urllib и requests: вызывающий ловит HTTPError и URLError, как раньше.
В вывод идёт номер повтора и класс сбоя; адреса и тела ответов - нет (журналы публичные).

    net.get_json(url, token)                          JSON GitHub по адресу (в том числе browser_download_url ассета релиза)
    net.fetch(url, method=, data=, headers=, mode=)   Response(status, headers, body)
    net.run(mode, [команда...], **kwargs)             gh, git, curl: subprocess.run через ci/retry.sh (тот же классификатор сбоев, что у bash-шагов)
    net.send(client, method, url, mode=, **kwargs)    то же через requests (магазины, Issues): requests.Response; net.session() - сессия
"""
import http.client
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import namedtuple

READ = "read"
IDEMPOTENT = "idem"
ONCE = "once"
DELAYS = (5, 10, 20)
SERVER_ERRORS = range(500, 600)
NOT_SENT = (socket.gaierror, ConnectionRefusedError)
NOT_SENT_NAMES = ("NameResolutionError", "NewConnectionError", "ConnectTimeoutError", "ConnectTimeout")

Response = namedtuple("Response", "status headers body")


def _not_sent(error):
    """Сбой, после которого запрос точно не ушёл: имя не найдено, отказ в соединении или не установилось. urllib оборачивает в URLError
    только сбои до отправки; таймаут и обрыв ответа выходят голыми, и по ним судить, дошёл ли запрос, нельзя."""
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, NOT_SENT) or type(error).__name__ in NOT_SENT_NAMES:
            return True
        if isinstance(error, urllib.error.URLError) and not isinstance(error, urllib.error.HTTPError) and "handshake" in str(error.reason).lower():
            return True
        error = _inner(error)
    return False


def _inner(error):
    candidates = (getattr(error, "reason", None), error.__cause__, error.__context__, *error.args)
    return next((c for c in candidates if isinstance(c, BaseException)), None)


def _retryable(error, mode):
    if _not_sent(error):
        return True
    if mode == ONCE:
        return False
    if isinstance(error, urllib.error.HTTPError):
        return error.code in SERVER_ERRORS
    return isinstance(error, (OSError, http.client.HTTPException))


def _kind(error):
    return f"HTTP {error.code}" if isinstance(error, urllib.error.HTTPError) else type(error).__name__


def _pause(attempt, delays, kind, mode):
    delay = delays[attempt]
    print(f"::notice::network call failed ({kind}, mode {mode}), retry {attempt + 1} of {len(delays)} in {delay}s", file=sys.stderr, flush=True)
    time.sleep(delay)


def attempt_all(call, mode=READ, delays=DELAYS):
    """Выполняет call() с повторами по режиму; последняя ошибка уходит вызывающему как есть."""
    for attempt in range(len(delays) + 1):
        try:
            return call()
        except Exception as error:
            if attempt == len(delays) or not _retryable(error, mode):
                raise
            _pause(attempt, delays, _kind(error), mode)


def default_mode(method):
    return {"GET": READ, "HEAD": READ, "PUT": IDEMPOTENT, "PATCH": IDEMPOTENT, "DELETE": IDEMPOTENT}.get(method.upper(), ONCE)


def fetch(url, *, method="GET", data=None, headers=None, timeout=60, mode=None, delays=DELAYS):
    """Ответ по адресу: Response(status, headers, body). Код 4xx и 5xx после повторов - urllib.error.HTTPError."""
    mode = mode or default_mode(method)

    def call():
        request = urllib.request.Request(url, data=data, method=method, headers=headers or {})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return Response(response.status, response.headers, response.read())

    return attempt_all(call, mode, delays)


def get_json(url, token=None, **options):
    """JSON по адресу GitHub; token - Bearer. Скачивание ассетов релиза у GitHub бывает медленным и отвечает 504."""
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return json.loads(fetch(url, headers=headers, **options).body)


def run(mode, args, **kwargs):
    """subprocess.run для сетевых команд (gh, git, curl): повторы и режимы - ci/retry.sh, одно место разбора сбоев для bash и Python."""
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "retry.sh")
    return subprocess.run(["bash", script, mode, *args], **kwargs)


def session():
    import requests

    return requests.Session()


def send(client, method, url, *, mode=None, delays=DELAYS, **kwargs):
    """Запрос через requests: client - сессия (requests.Session, AuthorizedSession) или None. Ответ 5xx после повторов возвращается как есть:
    raise_for_status и разбор кода - дело вызывающего."""
    import requests

    mode = mode or default_mode(method)

    for attempt in range(len(delays) + 1):
        last = attempt == len(delays)
        try:
            response = (client or requests).request(method, url, **kwargs)
        except requests.RequestException as error:
            if last or not (_not_sent(error) or (mode != ONCE and isinstance(error, (requests.ConnectionError, requests.Timeout)))):
                raise
            _pause(attempt, delays, type(error).__name__, mode)
            continue
        if last or mode == ONCE or response.status_code not in SERVER_ERRORS:
            return response
        _pause(attempt, delays, f"HTTP {response.status_code}", mode)
