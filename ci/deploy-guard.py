#!/usr/bin/env python3
"""Защита деплоя сервера (job `deploy` server.yml): не выкатывать сервер, который отрежет сборку, ещё лежащую в канале магазина.

    python3 ci/deploy-guard.py <каталог с исходниками сервера>

Берёт у собираемого сервера MIN_API_REVISION (Protocol.kt), RULES_VERSION и CONTENT_SCHEMA (Content.kt). Состояние каналов - публичный
манифест работающего сервера `${SERVER_URL}/static/index.json` (`channels`: у каждого канала `minVersionCode` - самая старая отдаваемая
сборка в окне, нет её - `latestVersionCode`) и update.json релизов exile-ci этих versionCode (ревизия, правила, форма контента).
Окно администратора (`GET admin/release/versions`) требует сессии, поэтому не используется: нового секрета не нужно.

Сборка играет с сервером, если её apiRevision не ниже MIN_API_REVISION сервера, CONTENT_SCHEMA сервера лежит в
[contentSchema-1..contentSchema] сборки, а RULES_VERSION - в [rules-1..rules] (клиентская логика предыдущей версии приходит в том же
выпуске). Сборка с update.json без contentSchema играет только с формой 3 и только со своими правилами. Хоть один канал со сборкой,
что не играет, - код 1 и ::error::.

Окружение: SERVER_URL (нет - защита выключена, предупреждение), FORCE_BREAKING=true (владелец одобрил разрыв: нарушения - лишь
предупреждение), GITHUB_TOKEN, GITHUB_REPOSITORY. Нет манифеста или update.json нужной сборки - тоже ошибка: слепой деплой не
разрешается. В журнал идут короткие строки: канал, versionCode и числа; адрес и тела ответов не печатаются.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

from store_common import Catalog, say

PROTOCOL = "rules/src/main/kotlin/com/sperance/exileforge/rules/wire/Protocol.kt"
CONTENT = "rules/src/main/kotlin/com/sperance/exileforge/rules/content/Content.kt"
LEGACY_SCHEMA = 3


def constant(path, name):
    with open(path, encoding="utf-8") as file:
        found = re.search(rf"^const val {name} = ([0-9]+)", file.read(), re.MULTILINE)
    if not found:
        say(f"::error::{name} not found in the server source")
        sys.exit(1)
    return int(found.group(1))


def held_builds(base):
    """Самая старая отдаваемая сборка каждого канала работающего сервера: {канал: versionCode}. Исключение - манифест недоступен."""
    request = urllib.request.Request(base + "/static/index.json", headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        channels = json.load(response).get("channels", {})
    return {name: info.get("minVersionCode") or info.get("latestVersionCode") or 0 for name, info in channels.items()}


def problems(update, revision_min, schema, rules):
    """Чем сборка не годится серверу; пустой список - играет."""
    own_rules = int(update.get("rules", 0))
    if update.get("contentSchema") is None:
        schemas, rule_set = (LEGACY_SCHEMA, LEGACY_SCHEMA), (own_rules, own_rules)
    else:
        own_schema = int(update["contentSchema"])
        schemas, rule_set = (own_schema - 1, own_schema), (own_rules - 1, own_rules)
    found = []
    if int(update["apiRevision"]) < revision_min:
        found.append(f"API {update['apiRevision']} is below the server minimum {revision_min}")
    if not schemas[0] <= schema <= schemas[1]:
        found.append(f"server content schema {schema} is outside {schemas[0]}..{schemas[1]}")
    if not rule_set[0] <= rules <= rule_set[1]:
        found.append(f"server rules {rules} are outside {rule_set[0]}..{rule_set[1]}")
    return found


def main():
    source = sys.argv[1]
    base = os.environ.get("SERVER_URL", "").strip().rstrip("/")
    if not base:
        say("::warning::SERVER_URL is not set: the deploy guard is off")
        return
    forced = os.environ.get("FORCE_BREAKING", "").strip().lower() == "true"
    revision_min = constant(os.path.join(source, PROTOCOL), "MIN_API_REVISION")
    schema = constant(os.path.join(source, CONTENT), "CONTENT_SCHEMA")
    rules = constant(os.path.join(source, CONTENT), "RULES_VERSION")
    try:
        held = held_builds(base)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, AttributeError) as error:
        say(f"::error::deploy guard: the live manifest is unavailable ({type(error).__name__})")
        sys.exit(0 if forced else 1)
    catalog, broken = Catalog(), 0
    for channel, code in sorted(held.items()):
        update = catalog.by_code(code) if code else None
        if update is None:
            broken += 1
            say(f"::error::deploy guard: {channel} holds version code {code} with no exile-ci release")
            continue
        issues = problems(update, revision_min, schema, rules)
        if issues:
            broken += 1
            say(f"::error::deploy guard: {channel} oldest build {code} cannot play this server: {'; '.join(issues)}")
        else:
            say(f"deploy guard: {channel} build {code} plays this server")
    if broken and forced:
        say("::warning::deploy guard: the break is approved by force_breaking")
    elif broken:
        say("::error::The server would cut a build still held by a store channel: fix the server or run with force_breaking to approve the break")
        sys.exit(1)


if __name__ == "__main__":
    main()
