"""Пост об обновлении в тему группы Telegram: заметки релиза (RELEASE_NOTES.md из тела релиза) с баннером крупным превью над
текстом и кнопками RuStore, Google Play и APK. Пост не закрепляется: тема и так только для обновлений.

Текст по подразделам заметок (ci/notes.py): «Новое», «Изменения», «Исправления», блок «Уже в игре» (пункты с меткой «[сервер]»: их
сервер уже выложил) и «Техническое» последним. Не влезает в лимит - пункты уходят с конца, так что «Техническое» первым.

Повтор без дублей: номер поста версии хранится в файле состояния (кэш Actions по тегу) - есть номер, пост правится, а не выходит
снова. Сбой - предупреждение в журнале и код 0: релиз уже вышел, пост повторяет ручной запуск (Release → telegram).
Окружение: TELEGRAM_BOT_TOKEN (секрет), TELEGRAM_CHAT (@группа), TELEGRAM_TOPIC (номер темы - последнее число ссылки t.me/группа/N),
GITHUB_SERVER_URL и GITHUB_REPOSITORY (их ставит Actions).
Использование: python3 post.py <тег> <файл заметок> <URL баннера> <файл состояния> [номер поста в теме]
"""
import html
import json
import os
import re
import sys
import time
import urllib.error
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import net
import notes as release_notes

LIMIT = 4096
IDEMPOTENT_METHODS = {"editMessageText"}
MANDATORY = release_notes.MANDATORY
SERVER_BLOCK = "Уже в игре"
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря")
LEAD = re.compile(r"^(?P<lead>[^:.!?]{2,40}):\s+(?P<rest>.+)$")
PACKAGE = "com.sperance.exileforge"


class TelegramError(Exception):
    pass


def text_length(text):
    """Длина, как её считает Telegram: видимый текст без разметки, в единицах UTF-16."""
    return len(html.unescape(re.sub(r"<[^>]+>", "", text)).encode("utf-16-le")) // 2


def bullet(item):
    """Пункт: короткая шапка до двоеточия - жирным; пункт «Техническое» - курсивом целиком, это строка не для всех."""
    m = LEAD.match(item)
    if not m:
        return f"▸ {html.escape(item)}"
    if m["lead"].lower().startswith("техническ"):
        return f"<i>{html.escape(item)}</i>"
    return f"▸ <b>{html.escape(m['lead'])}</b>: {html.escape(m['rest'])}"


def russian_date(now=None):
    moment = now or datetime.now(ZoneInfo("Europe/Moscow"))
    return f"{moment.day} {MONTHS[moment.month - 1]}"


def blocks(parsed):
    """Блоки поста по порядку: (заголовок, [готовые строки]). Пункты вне подразделов (прежний вид заметок) идут без заголовка."""
    result = []
    for title in release_notes.SECTIONS[:-1]:
        shown = [bullet(i) for i in parsed.items(title) if not release_notes.is_server(i) and not MANDATORY.match(i)]
        if shown:
            result.append((title, shown))
    already = [bullet(release_notes.strip_server(i)) for i in parsed.all_items() if release_notes.is_server(i)]
    if already:
        result.append((SERVER_BLOCK, already))
    loose = [i for i in parsed.items("") if not MANDATORY.match(i)]
    plain = [bullet(i) for i in loose if not release_notes.is_staff("", i)]
    if plain:
        result.insert(0, ("", plain))
    staff = [f"<i>{html.escape(release_notes.strip_staff(i))}</i>" for i in parsed.items(release_notes.STAFF_SECTION)]
    staff += [bullet(i) for i in loose if release_notes.is_staff("", i)]
    if staff:
        result.append((release_notes.STAFF_SECTION, staff))
    return result


def units(parsed):
    """Плоский список абзацев поста: заголовок подраздела и его пункты по одному. Обрезка снимает абзацы с конца."""
    flat = []
    for title, shown in blocks(parsed):
        if title:
            flat.append(("title", f"<b>{html.escape(title)}</b>"))
        flat.extend(("item", line) for line in shown)
    return flat


def compose(header, notes_text, release_url):
    """Текст поста. Обязательность - сразу под заголовком; не влезает в лимит - абзацы с конца уходят (пустой заголовок подраздела тоже),
    внизу ссылка на релиз."""
    parsed = release_notes.parse(notes_text)
    mandatory = any(MANDATORY.match(i) for i in parsed.all_items())
    head = [f"<b>{html.escape(header)}</b>"] + (["❗ <b>Обновление обязательное</b>"] if mandatory else [])
    more = f'<a href="{release_url}">Все изменения</a>'
    body = units(parsed)

    text = "\n\n".join(head + [t for _, t in body])
    while text_length(text) > LIMIT and body:
        body = body[:-1]
        while body and body[-1][0] == "title":
            body = body[:-1]
        text = "\n\n".join(head + [t for _, t in body] + [more])
    return text


def keyboard(apk_url):
    return {"inline_keyboard": [
        [{"text": "RuStore", "url": f"https://www.rustore.ru/catalog/app/{PACKAGE}"},
         {"text": "Google Play", "url": f"https://play.google.com/store/apps/details?id={PACKAGE}"}],
        [{"text": "Скачать APK", "url": apk_url}],
    ]}


class Bot:
    def __init__(self, token):
        self._token = token

    def call(self, method, **params):
        """Вызов Bot API. sendMessage не повторяется вслепую (дубль поста): ONCE, повтор только до отправки; правка поста идемпотентна.
        429 Telegram отклонил запрос целиком - до пяти попыток с паузой, что он просит; прочий отказ - сразу."""
        data = json.dumps(params).encode()
        mode = net.IDEMPOTENT if method in IDEMPOTENT_METHODS else net.ONCE
        url = f"https://api.telegram.org/bot{self._token}/{method}"
        for _ in range(5):
            try:
                return json.loads(net.fetch(url, method="POST", data=data, headers={"Content-Type": "application/json"}, timeout=30, mode=mode).body)["result"]
            except urllib.error.HTTPError as e:
                reply = json.loads(e.read() or b"{}")
                retry_after = reply.get("parameters", {}).get("retry_after")
                if not retry_after:
                    raise TelegramError(f"{method}: {reply.get('description', f'HTTP {e.code}')}") from None
                time.sleep(retry_after + 1)
            except (urllib.error.URLError, TimeoutError) as e:
                raise TelegramError(f"{method}: {getattr(e, 'reason', e)}") from None
        raise TelegramError(f"{method}: flood control did not clear")


def wait_for_image(url, timeout=180):
    """Pages выкладывает файл не мгновенно: превью, снятое до появления картинки, Telegram запомнит пустым."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            if net.fetch(url, timeout=20, delays=()).headers.get_content_type().startswith("image/"):
                return
        except urllib.error.URLError:
            pass
        if time.monotonic() > deadline:
            raise TelegramError("the banner did not appear on GitHub Pages")
        time.sleep(10)


def publish(bot, chat, topic, content, known_id, remember):
    """Правит пост known_id, если он есть и не удалён, иначе отправляет новый (его номер уходит в remember). Возвращает итог."""
    if known_id:
        try:
            bot.call("editMessageText", chat_id=chat, message_id=known_id, **content)
            return "edited"
        except TelegramError as e:
            if "message is not modified" in str(e):
                return "unchanged"
            if "message to edit not found" not in str(e):
                raise
    remember(bot.call("sendMessage", chat_id=chat, message_thread_id=topic, **content)["message_id"])
    return "posted"


def main(tag, notes_file, banner_url, state_file, message_id=""):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("::warning::TELEGRAM_BOT_TOKEN is not set: no Telegram post")
        return
    releases = f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/releases"
    with open(notes_file, encoding="utf-8") as f:
        text = compose(f"Обновление {tag.removeprefix('v')}", f.read(), f"{releases}/tag/{tag}")
    content = {
        "text": text,
        "parse_mode": "HTML",
        "link_preview_options": {"url": banner_url, "prefer_large_media": True, "show_above_text": True},
        "reply_markup": keyboard(f"{releases}/download/{tag}/ExileForge-{tag}.apk"),
    }

    def remember(new_id):
        with open(state_file, "w") as f:
            json.dump({"message_id": new_id}, f)

    # Номер, заданный вручную, - пост этой версии, что уже есть в теме: его правим и запоминаем
    known_id = int(message_id) if message_id else None
    if known_id:
        remember(known_id)
    elif os.path.exists(state_file):
        with open(state_file) as f:
            known_id = json.load(f)["message_id"]
    try:
        wait_for_image(banner_url)
        result = publish(Bot(token), os.environ["TELEGRAM_CHAT"], int(os.environ["TELEGRAM_TOPIC"]), content, known_id, remember)
    except TelegramError as e:
        print(f"::warning::Telegram post of {tag} failed: {e}. Repeat: Release → telegram")
        return
    print(f"telegram: {result} {tag}, {text_length(text)} of {LIMIT} characters")


if __name__ == "__main__":
    main(*sys.argv[1:6])
