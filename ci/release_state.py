#!/usr/bin/env python3
"""Накопительный выпуск: что копится с прошлого выпуска и что не должно потеряться. Читает git клиента и сервера, наружу - только счётчики,
номера и короткие хеши (журналы публичны, код и тексты приватных репозиториев в журнал не идут: ci/quiet.sh, $PUBLIC_NOTES).

Подкоманды (каталоги --cli и --srv - клон клиента и клон сервера с историей):
  check     проверки check-wip (check-wip.yml): заметки «Следующей версии» и неопубликованное «Важное» не потеряны, к вышедшему тексту
            не дописано, вайп игровой коллекции сопровождён текстом «Важного»; красное - код 1;
  preview   сводка выпуска без выпуска (Release → preview): полный markdown в --out (шифруется), счётчики в --summary;
  issues    номера Issues, что чинит выпуск: трейлеры клиента (`Issue: #N`, прежнее «Closes #N») и сервера (`Refs <репо>#N`) с прошлого выпуска;
  trailer   значения трейлера в коммитах клиента и сервера с прошлого выпуска (Update-Mandatory, Bump);
  baseline  последний выкаченный коммит сервера среди предков --head (теги server-deployed/<sha>).
Трейлеры работы в коммитах wip относительно рабочей ветки (любого из двух репозиториев): `Notes-Edit: <причина>` разрешает правку или
удаление накопленных строк, `Wipe-Silent: <причина>` - вайп без текста «Важного», `Bump: minor` - совет поднять minor.
"""
import argparse
import hashlib
import importlib.util
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "telegram"))
import net
import notes
from store_common import say

NOTES_PATH = "RELEASE_NOTES.md"
IMPORTANT_PATH = "IMPORTANT.md"
SCHEMAS_PATH = "src/main/kotlin/ru/descend/exileforge/config/CollectionSchemas.kt"
SERVICE_COLLECTIONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "service-collections.txt")
SCHEMA = re.compile(r'CollectionSchema\(\s*"(\w+)",\s*(\d+)')
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?) #(\d+)", re.IGNORECASE)
ISSUE_TRAILER = re.compile(r"^Issue: #(\d+)", re.MULTILINE)
SPLIT = "\x00"


def run(directory, *args):
    done = net.run(net.READ, ["git", "-C", directory, *args], capture_output=True)
    return done.stdout if done.returncode == 0 else None


def show(directory, ref, path):
    """Содержимое файла на ref (байты) или None, если файла нет."""
    return run(directory, "show", f"{ref}:{path}")


def text_at(directory, ref, path):
    data = show(directory, ref, path)
    return data.decode("utf-8") if data is not None else ""


def messages(directory, base, head):
    """Тексты коммитов base..head (base пуст - вся история head). Нет истории - пустой список."""
    span = f"{base}..{head}" if base else head
    out = run(directory, "log", "-z", "--format=%B", span)
    return [part for part in (out or b"").decode("utf-8", "replace").split(SPLIT) if part.strip()]


def trailer_values(texts, name):
    pattern = re.compile(rf"^{re.escape(name)}:[ \t]*(\S.*)$", re.MULTILINE | re.IGNORECASE)
    return [m.group(1).strip() for text in texts for m in pattern.finditer(text)]


def pin(cli, ref):
    out = run(cli, "ls-tree", ref, "backend")
    fields = (out or b"").decode().split()
    return fields[2] if len(fields) >= 3 and re.fullmatch(r"[0-9a-f]{40}", fields[2]) else ""


def release_messages(cli, srv, base, head):
    """Тексты коммитов с прошлого выпуска: клиента base..head и сервера - от сервера, закреплённого на base, до закреплённого на head."""
    server = []
    if base:
        old, new = pin(cli, base), pin(cli, head)
        if old and new and old != new:
            server = messages(srv, old, new)
    return messages(cli, base, head), server


def issue_numbers(client, server, repo):
    found = set()
    for text in client:
        found.update(int(n) for n in CLOSING.findall(text))
        found.update(int(n) for n in ISSUE_TRAILER.findall(text))
    refs = re.compile(rf"^Refs {re.escape(repo)}#(\d+)", re.MULTILINE)
    for text in server:
        found.update(int(n) for n in refs.findall(text))
    return sorted(found)


def listed(path):
    if not path or not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as file:
        return {line.strip().rsplit("/", 1)[-1] for line in file if line.strip()}


def deployed_baseline(srv, head, deployed):
    """Ближайший к head предок (или сам head) среди выкаченных коммитов сервера или пустая строка."""
    if not deployed:
        return ""
    out = run(srv, "rev-list", "--max-count=3000", head) or b""
    return next((sha for sha in out.decode().split() if sha in deployed), "")


def service_collections():
    with open(SERVICE_COLLECTIONS, encoding="utf-8") as file:
        return {line.strip() for line in file if line.strip() and not line.startswith("#")}


def schemas(srv, ref):
    return {name: int(version) for name, version in SCHEMA.findall(text_at(srv, ref, SCHEMAS_PATH))}


def raised(before, after):
    service = service_collections()
    return {name: (before[name], version) for name, version in after.items() if name not in service and name in before and version > before[name]}


def short(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def important_line(line):
    return re.sub(r"\s+", " ", re.sub(r"^#+\s*", "", line.strip()))


def important_lines(text):
    return {important_line(line) for line in text.splitlines() if line.strip()}


def important_tag(data):
    return "important-" + hashlib.sha256(data).hexdigest()[:12]


def unreleased_items(text):
    body = notes.next_section(text)
    return [] if body is None else [notes.normalize(item) for item in notes.parse(body).all_items()]


def check_notes(args, trailers):
    work = unreleased_items(text_at(args.cli, args.cli_work, NOTES_PATH))
    wip_text = text_at(args.cli, args.cli_wip, NOTES_PATH)
    wip = set(unreleased_items(wip_text))
    red = False
    lost = [(i + 1, short(item)) for i, item in enumerate(work) if item not in wip]
    if lost and not trailers["Notes-Edit"]:
        say(f"notes: {len(lost)} unreleased line(s) of the working branch are missing or changed on wip (item numbers and hashes: "
            f"{', '.join(f'{i}:{h}' for i, h in lost[:20])}); move lines between subsections freely, to delete or reword one add the trailer "
            f"'Notes-Edit: <reason>' to a wip commit")
        red = True
    body = notes.next_section(wip_text)
    if body is not None:
        for problem in notes.problems(body):
            say(f"notes: {problem}")
            red = True
    return red


def check_important(args, trailers, posted):
    work_data = show(args.srv, args.srv_work, IMPORTANT_PATH) or b""
    wip_data = show(args.srv, args.srv_wip, IMPORTANT_PATH) or b""
    red = False
    work_lines = important_lines(work_data.decode("utf-8"))
    wip_lines = important_lines(wip_data.decode("utf-8"))
    if work_data != wip_data:
        if work_data.strip() and important_tag(work_data) in posted:
            if work_lines <= wip_lines:
                say("important: the text of the working branch is already posted (tag exists), and wip appends to it: start IMPORTANT.md anew")
                red = True
        else:
            lost = work_lines - wip_lines
            if lost and not trailers["Notes-Edit"]:
                say(f"important: {len(lost)} line(s) of the unposted IMPORTANT.md of the working branch are missing or changed on wip "
                    f"(hashes: {', '.join(sorted(short(line) for line in lost)[:20])}); to delete or reword add the trailer "
                    f"'Notes-Edit: <reason>' to a wip commit")
                red = True
    if wip_data.strip():
        from important import compose
        from post import TelegramError
        try:
            compose(wip_data.decode("utf-8"), "0.99.99")
        except TelegramError as error:
            say(f"important: {error}")
            red = True
    return red


def check_wipe(args, trailers, posted, deployed):
    baseline = deployed_baseline(args.srv, args.srv_work, deployed)
    wip = schemas(args.srv, args.srv_wip)
    since_deploy = raised(schemas(args.srv, baseline or args.srv_work), wip)
    if not since_deploy:
        return False
    in_work = raised(schemas(args.srv, args.srv_work), wip)
    wip_data = show(args.srv, args.srv_wip, IMPORTANT_PATH) or b""
    work_lines = important_lines(text_at(args.srv, args.srv_work, IMPORTANT_PATH))
    has_text = bool(wip_data.strip()) and important_tag(wip_data) not in posted
    new_text = bool(important_lines(wip_data.decode("utf-8")) - work_lines)
    if has_text and (new_text or not in_work) or trailers["Wipe-Silent"]:
        say(f"wipe: game collections raised since the last deployed server: {', '.join(sorted(since_deploy))}; covered")
        return False
    say(f"wipe: game collections raised since the last deployed server ({', '.join(f'{n} {a}->{b}' for n, (a, b) in sorted(since_deploy.items()))}) "
        f"and IMPORTANT.md has no new unposted text: describe the wipe there or add the trailer 'Wipe-Silent: <reason>' to a wip commit")
    return True


def wip_trailers(args):
    texts = messages(args.cli, args.cli_work, args.cli_wip) + messages(args.srv, args.srv_work, args.srv_wip)
    return {name: trailer_values(texts, name) for name in ("Notes-Edit", "Wipe-Silent", "Bump")}


def command_check(args):
    trailers = wip_trailers(args)
    posted = listed(args.posted_important)
    deployed = listed(args.deployed)
    results = [check_notes(args, trailers), check_important(args, trailers, posted), check_wipe(args, trailers, posted, deployed)]
    say("release guards: " + ("RED" if any(results) else "green"))
    return 1 if any(results) else 0


def next_versions(last):
    spec = importlib.util.spec_from_file_location("bump_release", os.path.join(os.path.dirname(os.path.abspath(__file__)), "bump-release.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {bump: module.next_version(last, bump) for bump in ("patch", "minor")}


def open_issues(numbers, repo):
    if not os.environ.get("GH_TOKEN"):
        return numbers
    still = []
    for number in numbers:
        done = net.run(net.READ, ["gh", "issue", "view", str(number), "-R", repo, "--json", "state", "--jq", ".state"], capture_output=True, text=True)
        if done.returncode != 0 or done.stdout.strip() == "OPEN":
            still.append(number)
    return still


def command_preview(args):
    client, server = release_messages(args.cli, args.srv, args.base, args.head)
    mandatory = any(v.lower().startswith("yes") for v in trailer_values(client + server, "Update-Mandatory"))
    minor = [v for v in trailer_values(client + server, "Bump") if v.lower().startswith("minor")]
    advice = "minor" if minor else "patch"
    versions = next_versions(args.last)
    numbers = open_issues(issue_numbers(client, server, args.repo), args.repo)
    deployed = listed(args.deployed)
    baseline = deployed_baseline(args.srv, args.srv_head, deployed)
    raised_now = raised(schemas(args.srv, baseline or args.srv_head), schemas(args.srv, args.srv_head))
    important = text_at(args.srv, args.srv_head, IMPORTANT_PATH)
    data = important.encode("utf-8")
    posted = important_tag(data) in listed(args.posted_important)
    body = notes.next_section(text_at(args.cli, args.head, NOTES_PATH))
    parsed = notes.parse(body or "")
    unposted = [i for i in parsed.all_items() if notes.is_server(i) and "server-note-" + hashlib.sha256(notes.normalize(i).encode()).hexdigest()[:12] not in listed(args.posted_server)]
    out = ["## Выпуск: предпросмотр (ничего не выпущено)", "",
           f"- Последний выпуск: {args.last}. Совет: **{advice}** → {versions[advice]} (patch → {versions['patch']}, minor → {versions['minor']}); "
           f"трейлеров `Bump: minor` с прошлого выпуска: {len(minor)}",
           f"- Обновление обязательное: **{'да' if mandatory else 'нет'}**",
           f"- Issues к закрытию (открытые, по трейлерам клиента и сервера): {', '.join(f'#{n}' for n in numbers) or 'нет'}",
           f"- Вайпы игровых коллекций с прошлого выката сервера: {', '.join(f'{n} {a}→{b}' for n, (a, b) in sorted(raised_now.items())) or 'нет'}"
           f"{'' if baseline else ' (выкат сервера не отмечен: считано от рабочей ветки)'}",
           f"- Пунктов «[сервер]», что ещё не выходили отдельным постом: {len(unposted)}", ""]
    summary = out + [f"- «Важное»: {'нет текста' if not important.strip() else ('уже опубликовано' if posted else 'новый текст, ' + str(len(important_lines(important))) + ' строк')}",
                     f"- Заметки: {', '.join(f'{title} {len(parsed.items(title))}' for title in notes.SECTIONS if parsed.items(title)) or 'нет'}",
                     "", "Полный текст заметок и «Важного» - в зашифрованном артефакте `preview` (age)."]
    with open(args.summary, "w", encoding="utf-8") as file:
        file.write("\n".join(summary) + "\n")
    out += ["### «Важное»", ""]
    if not important.strip():
        out += ["Текста нет.", ""]
    else:
        out += [("Уже опубликовано (тег есть), новый пост не выйдет." if posted else f"Выйдет при выкате сервера, заголовок «Важное в обновлении {versions[advice]} · дата»."), "", "```", important.strip(), "```", ""]
    out += ["### Заметки", ""]
    if body is None:
        out += ["Раздела «Следующая версия» нет: выпуск не начнётся.", ""]
    for title in [*notes.SECTIONS, ""]:
        items = parsed.items(title)
        if items:
            out += [f"**{title or 'Вне подразделов'}**", *[f"- {item}" for item in items], ""]
    for problem in notes.problems(body or ""):
        out.append(f"> Заметки: {problem}")
    with open(args.out, "w", encoding="utf-8") as file:
        file.write("\n".join(out) + "\n")
    say(f"preview: advice {advice}, {len(numbers)} issue(s), mandatory {'yes' if mandatory else 'no'}")
    return 0


def command_issues(args):
    client, server = release_messages(args.cli, args.srv, args.base, args.head)
    print(" ".join(str(n) for n in issue_numbers(client, server, args.repo)))
    return 0


def command_server_issues(args):
    print(" ".join(str(n) for n in issue_numbers([], messages(args.srv, args.base, args.head), args.repo)))
    return 0


def command_trailer(args):
    client, server = release_messages(args.cli, args.srv, args.base, args.head)
    values = trailer_values(client + server, args.name)
    print("\n".join(values))
    return 0 if values else 1


def command_baseline(args):
    print(deployed_baseline(args.srv, args.head, listed(args.deployed)))
    return 0


def parser():
    root = argparse.ArgumentParser()
    sub = root.add_subparsers(dest="command", required=True)

    def add(name, handler, *options):
        p = sub.add_parser(name)
        for option in options:
            p.add_argument(f"--{option}", default="")
        p.set_defaults(handler=handler)

    add("check", command_check, "cli", "srv", "cli-wip", "cli-work", "srv-wip", "srv-work", "posted-important", "deployed")
    add("preview", command_preview, "cli", "srv", "base", "head", "srv-head", "last", "repo", "out", "summary", "posted-important", "posted-server", "deployed")
    add("issues", command_issues, "cli", "srv", "base", "head", "repo")
    add("server-issues", command_server_issues, "srv", "base", "head", "repo")
    p = sub.add_parser("trailer")
    p.add_argument("name")
    for option in ("cli", "srv", "base", "head"):
        p.add_argument(f"--{option}", default="")
    p.set_defaults(handler=command_trailer)
    add("baseline", command_baseline, "srv", "head", "deployed")
    return root


def main():
    args = parser().parse_args()
    sys.exit(args.handler(args))


if __name__ == "__main__":
    main()
