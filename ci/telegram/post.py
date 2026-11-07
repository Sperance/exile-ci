"""Пост об обновлении в тему группы Telegram: заметки релиза (RELEASE_NOTES.md из тела релиза) с баннером крупным превью над
текстом и кнопками RuStore, Google Play и APK. Новый пост закрепляется в теме вместо прошлых.

Повтор без дублей: номер поста версии хранится в файле состояния (кэш Actions по тегу) - есть номер, пост правится, а не выходит
снова. Сбой - предупреждение в журнале и код 0: релиз уже вышел, пост повторяет ручной запуск (Release → telegram).
Окружение: TELEGRAM_BOT_TOKEN (секрет), TELEGRAM_CHAT (@группа), TELEGRAM_TOPIC (номер темы - последнее число ссылки t.me/группа/N),
GITHUB_SERVER_URL и GITHUB_REPOSITORY (их ставит Actions).
Использование: python3 post.py <тег> <файл заметок> <URL баннера> <файл состояния>
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
        """Вызов Bot API; 429 и сбои сети или сервера Telegram - до трёх попыток, остальные ошибки - сразу."""
        data = json.dumps(params).encode()
        for attempt in range(3):
            request = urllib.request.Request(f"https://api.telegram.org/bot{self._token}/{method}", data,
                                             {"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    return json.load(response)["result"]
            except urllib.error.HTTPError as e:
                reply = json.loads(e.read() or b"{}")
                description = reply.get("description", f"HTTP {e.code}")
                retry_after = reply.get("parameters", {}).get("retry_after")
                if attempt == 2 or not (retry_after or e.code >= 500):
                    raise TelegramError(f"{method}: {description}") from None
                time.sleep(retry_after or 5 * (attempt + 1))
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt == 2:
                    raise TelegramError(f"{method}: {getattr(e, 'reason', e)}") from None
                time.sleep(5 * (attempt + 1))


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


def publish(bot, chat, topic, text, banner_url, markup, known_id):
    """Правит пост known_id, если он есть и не удалён; иначе отправляет новый и закрепляет его один в теме. Возвращает номер поста."""
    content = {
        "text": text,
        "parse_mode": "HTML",
        "link_preview_options": {"url": banner_url, "prefer_large_media": True, "show_above_text": True},
        "reply_markup": markup,
    }
    if known_id:
        try:
            bot.call("editMessageText", chat_id=chat, message_id=known_id, **content)
            return known_id, "edited"
        except TelegramError as e:
            if "message is not modified" in str(e):
                return known_id, "unchanged"
            if "message to edit not found" not in str(e):
                raise
    message_id = bot.call("sendMessage", chat_id=chat, message_thread_id=topic, **content)["message_id"]
    bot.call("unpinAllForumTopicMessages", chat_id=chat, message_thread_id=topic)
    # Пост уже прозвенел - закреп без второго уведомления
    bot.call("pinChatMessage", chat_id=chat, message_id=message_id, disable_notification=True)
    return message_id, "posted"


def main(tag, notes_file, banner_url, state_file):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("::warning::TELEGRAM_BOT_TOKEN is not set: no Telegram post")
        return
    releases = f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/releases"
    with open(notes_file, encoding="utf-8") as f:
        text = compose(f"Обновление {tag.removeprefix('v')}", f.read(), f"{releases}/tag/{tag}")
    markup = keyboard(f"{releases}/download/{tag}/ExileForge-{tag}.apk")
    state = json.loads(open(state_file).read()) if os.path.exists(state_file) else {}
    try:
        wait_for_image(banner_url)
        message_id, result = publish(Bot(token), os.environ["TELEGRAM_CHAT"], int(os.environ["TELEGRAM_TOPIC"]), text, banner_url,
                                     markup, state.get("message_id"))
    except TelegramError as e:
        print(f"::warning::Telegram post of {tag} failed: {e}. Repeat: Release → telegram")
        return
    with open(state_file, "w") as f:
        json.dump({"message_id": message_id}, f)
    print(f"telegram: {result} {tag}, {text_length(text)} of {LIMIT} characters")


if __name__ == "__main__":
    main(*sys.argv[1:5])
