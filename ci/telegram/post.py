"""Пост об обновлении в тему группы Telegram: заметки релиза (RELEASE_NOTES.md из тела релиза) с баннером крупным превью над
текстом и кнопками RuStore, Google Play и APK. Пост не закрепляется: тема и так только для обновлений.

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
import urllib.request

LIMIT = 4096
MANDATORY = re.compile(r"^обновление обязательное\.?$", re.I)
LEAD = re.compile(r"^(?P<lead>[^:.!?]{2,40}):\s+(?P<rest>.+)$")
PACKAGE = "com.sperance.exileforge"


class TelegramError(Exception):
    pass


def text_length(text):
    """Длина, как её считает Telegram: видимый текст без разметки, в единицах UTF-16."""
    return len(html.unescape(re.sub(r"<[^>]+>", "", text)).encode("utf-16-le")) // 2


def bullet(item):
    """Пункт: короткая шапка до двоеточия - жирным; «Техническое» - курсивом целиком, это строка не для всех."""
    m = LEAD.match(item)
    if not m:
        return f"▸ {html.escape(item)}"
    if m["lead"].lower().startswith("техническ"):
        return f"<i>{html.escape(item)}</i>"
    return f"▸ <b>{html.escape(m['lead'])}</b>: {html.escape(m['rest'])}"


def compose(header, notes, release_url):
    """Текст поста. Обязательность - сразу под заголовком; не влезает в лимит - пункты с конца уходят, внизу ссылка на релиз."""
    items = [ln.strip()[2:].strip() for ln in notes.splitlines() if ln.strip().startswith("- ")]
    mandatory = any(MANDATORY.match(i) for i in items)
    body = [bullet(i) for i in items if not MANDATORY.match(i)]
    head = [f"<b>{html.escape(header)}</b>"] + (["❗ <b>Обновление обязательное</b>"] if mandatory else [])
    more = f'<a href="{release_url}">Все изменения</a>'
    text = "\n\n".join(head + body)
    while text_length(text) > LIMIT and body:
        body.pop()
        text = "\n\n".join(head + body + [more])
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
        """Вызов Bot API. 429 - до пяти попыток с паузой, что просит Telegram; сбои сети и сервера Telegram - до трёх; прочее - сразу."""
        data = json.dumps(params).encode()
        failures = 0
        for attempt in range(5):
            request = urllib.request.Request(f"https://api.telegram.org/bot{self._token}/{method}", data,
                                             {"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    return json.load(response)["result"]
            except urllib.error.HTTPError as e:
                reply = json.loads(e.read() or b"{}")
                error = TelegramError(f"{method}: {reply.get('description', f'HTTP {e.code}')}")
                retry_after = reply.get("parameters", {}).get("retry_after")
                if retry_after:
                    time.sleep(retry_after + 1)
                    continue
                failures += 1
                if e.code < 500 or failures == 3:
                    raise error from None
            except (urllib.error.URLError, TimeoutError) as e:
                error = TelegramError(f"{method}: {getattr(e, 'reason', e)}")
                failures += 1
                if failures == 3:
                    raise error from None
            time.sleep(5 * failures)
        raise error


def wait_for_image(url, timeout=180):
    """Pages выкладывает файл не мгновенно: превью, снятое до появления картинки, Telegram запомнит пустым."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                if response.headers.get_content_type().startswith("image/"):
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
