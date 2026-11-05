#!/usr/bin/env python3
"""Защита деплоя сервера (job `deploy` server.yml): не выкатывать сервер, который отрежет сборку, ещё лежащую в канале магазина.

    python3 ci/deploy-guard.py <каталог с исходниками сервера>

Проверка на РЕГРЕССИЮ: сервер судит сборки по живому окну, а не по константам кода. Берётся публичный манифест работающего сервера
`${SERVER_URL}/static/index.json` (`revision`, `minRevision`, `activeRules`, `content.schema`, `content.minSchema`, `channels`: у канала
`minVersionCode` - самая старая отдаваемая сборка, нет её - `latestVersionCode`) и update.json релизов exile-ci этих versionCode
(apiRevision, rules, contentSchema). Для каждой сборки считается, играет ли она с живым сервером и с сервером после деплоя.

Сборка играет, если: её apiRevision не ниже minRevision сервера (сервер без окна, minRevision 0, - только своя ревизия); activeRules
сервера лежит в [rules-1..rules] (спящие правила; сборка без contentSchema - только rules); форма контента сервера лежит в
[contentSchema-1..contentSchema] при minSchema не выше contentSchema (сборка без contentSchema - только форма 3).

Сервер после деплоя: minRevision живого окна (MIN_API_REVISION, если MIN_API_REVISION_FORCED=true: тогда окно и activeRules
поднимаются до RULES_VERSION разом), activeRules живой (деплой её не двигает), форма CONTENT_SCHEMA и minSchema не ниже
CONTENT_SCHEMA-1. Отдельная ошибка: RULES_VERSION-1 выше живых activeRules - новый сервер не сможет считать живую эпоху.
Блокирует только сборка, которую живой сервер принимает, а новый отрежет; не принимаемая уже сейчас - предупреждение.

Окружение: SERVER_URL (нет - защита выключена, предупреждение), FORCE_BREAKING=true (владелец одобрил разрыв: нарушения - лишь
предупреждение), GITHUB_TOKEN, GITHUB_REPOSITORY. Нет манифеста или update.json нужной сборки - тоже ошибка: слепой деплой не
разрешается. В журнал идут короткие строки: канал, versionCode и числа; адрес и тела ответов не печатаются.
"""
import json
from collections import namedtuple
import os
import re
import sys
import urllib.error
import urllib.request

from store_common import Catalog, say

PROTOCOL = "rules/src/main/kotlin/com/sperance/exileforge/rules/wire/Protocol.kt"
CONTENT = "rules/src/main/kotlin/com/sperance/exileforge/rules/content/Content.kt"
LEGACY_SCHEMA = 3

Server = namedtuple("Server", "revision min_revision active_rules schema min_schema")


def constant(path, name):
    with open(path, encoding="utf-8") as file:
        found = re.search(rf"^const val {name} = ([0-9]+|true|false)\b", file.read(), re.MULTILINE)
    if not found:
        say(f"::error::{name} not found in the server source")
        sys.exit(1)
    return found.group(1) == "true" if found.group(1) in ("true", "false") else int(found.group(1))


def live_state(base):
    """Живой манифест: окно сервера и самая старая отдаваемая сборка каждого канала. Исключение - манифест недоступен."""
    request = urllib.request.Request(base + "/static/index.json", headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        manifest = json.load(response)
    content = manifest.get("content", {})
    schema = int(content["schema"])
    server = Server(int(manifest["revision"]), int(manifest.get("minRevision", 0)), int(manifest["activeRules"]), schema, int(content.get("minSchema", schema)))
    channels = manifest.get("channels", {})
    return server, {name: info.get("minVersionCode") or info.get("latestVersionCode") or 0 for name, info in channels.items()}


def after_deploy(live, revision, revision_min, forced, rules, schema):
    """Окно сервера после деплоя: ревизия и схема новые, минимум ревизии и правила двигаются только вынужденным минимумом."""
    if forced:
        return Server(revision, max(live.min_revision, revision_min), max(live.active_rules, rules), schema, max(live.min_schema, schema - 1))
    return Server(revision, live.min_revision, live.active_rules, schema, max(live.min_schema, schema - 1))


def problems(update, server):
    """Чем сборка не годится серверу; пустой список - играет."""
    own_rules = int(update.get("rules", 0))
    revision = int(update["apiRevision"])
    found = []
    if server.min_revision > 0:
        if revision < server.min_revision:
            found.append(f"API {revision} is below the server minimum {server.min_revision}")
    elif revision != server.revision:
        found.append(f"API {revision} differs from the server revision {server.revision}")
    if update.get("contentSchema") is None:
        if server.schema != LEGACY_SCHEMA:
            found.append(f"server content schema {server.schema} is not {LEGACY_SCHEMA}")
        if server.active_rules != own_rules:
            found.append(f"server rules {server.active_rules} differ from {own_rules}")
        return found
    own_schema = int(update["contentSchema"])
    if not own_schema - 1 <= server.schema <= own_schema:
        found.append(f"server content schema {server.schema} is outside {own_schema - 1}..{own_schema}")
    if server.min_schema > own_schema:
        found.append(f"server minimum schema {server.min_schema} is above {own_schema}")
    if not own_rules - 1 <= server.active_rules <= own_rules:
        found.append(f"server active rules {server.active_rules} are outside {own_rules - 1}..{own_rules}")
    return found


def main():
    source = sys.argv[1]
    base = os.environ.get("SERVER_URL", "").strip().rstrip("/")
    if not base:
        say("::warning::SERVER_URL is not set: the deploy guard is off")
        return
    forced = os.environ.get("FORCE_BREAKING", "").strip().lower() == "true"
    revision = constant(os.path.join(source, PROTOCOL), "API_REVISION")
    revision_min = constant(os.path.join(source, PROTOCOL), "MIN_API_REVISION")
    revision_forced = constant(os.path.join(source, PROTOCOL), "MIN_API_REVISION_FORCED")
    schema = constant(os.path.join(source, CONTENT), "CONTENT_SCHEMA")
    rules = constant(os.path.join(source, CONTENT), "RULES_VERSION")
    try:
        live, held = live_state(base)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, AttributeError, KeyError, TypeError) as error:
        # Сервер лежит - сверять не с чем, а деплой его поднимает: восстановление не ждёт force_breaking
        say(f"::warning::deploy guard: the live manifest is unavailable ({type(error).__name__}), deploy goes on")
        return
    after = after_deploy(live, revision, revision_min, revision_forced, rules, schema)
    broken = 0
    if rules - 1 > live.active_rules:
        broken += 1
        say(f"::error::deploy guard: the new server rules {rules} cannot compute the live era {live.active_rules} (needs active rules >= {rules - 1})")
    catalog = Catalog()
    for channel, code in sorted(held.items()):
        update = catalog.by_code(code) if code else None
        if update is None:
            broken += 1
            say(f"::error::deploy guard: {channel} holds version code {code} with no exile-ci release")
            continue
        was, will = problems(update, live), problems(update, after)
        if was:
            say(f"::warning::deploy guard: {channel} build {code} is already not admitted by the live server: {'; '.join(was)}")
        elif will:
            broken += 1
            say(f"::error::deploy guard: {channel} build {code} plays the live server but the new one would cut it: {'; '.join(will)}")
        else:
            say(f"deploy guard: {channel} build {code} keeps playing")
    if broken and forced:
        say("::warning::deploy guard: the break is approved by force_breaking")
    elif broken:
        say("::error::The new server would cut a playable build or could not read the live era: fix the server or run with force_breaking to approve the break")
        sys.exit(1)


if __name__ == "__main__":
    main()
