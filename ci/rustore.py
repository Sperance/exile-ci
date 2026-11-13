#!/usr/bin/env python3
"""RuStore public API: загрузка APK, черновик версии, отправка на модерацию с автопубликацией и чтение статусов версий.

Секреты: RUSTORE_KEY_ID и RUSTORE_PRIVATE_KEY (закрытый ключ из консоли RuStore: PEM или base64 DER; значения нигде не печатаются).
Нужны пакеты requests и cryptography (.github/actions/store-tools). Пакет приложения - APP_ID из ci/build-tasks.env. Весь вывод
скрипта перехватывает ci/quiet.sh.

«Что нового» версии - выжимка ci/notes.py store_summary (целые пункты «Нового», «Изменений», «Исправлений», остаток - «…и ещё N изменений в игре») не длиннее
меньшего из NOTES_LIMIT скрипта (4000) и 500 знаков (store_common.WHATS_NEW_LIMIT, как в Play).

Запуск (из каталога с распакованным APK):
    python3 ci/rustore.py upload <app.apk> <update.json>
"""
import base64
import datetime
import json
import os
import sys

import net
from store_common import fail, load_update, say, short_notes

BASE = "https://public-api.rustore.ru"
NOTES_LIMIT = 4000
# Версия в магазине у игроков: ACTIVE - опубликована; остальные статусы (DRAFT, MODERATION, APPROVED до публикации, REJECTED) - ещё нет
LIVE = {"ACTIVE", "PUBLISHED"}
# Не на модерации: черновик, отказ, снятая с публикации или живая версия; остальное (MODERATION, APPROVED до публикации) - ждёт магазина
SETTLED = LIVE | {"DRAFT", "REJECTED", "DECLINED", "ARCHIVED", "INACTIVE"}
# priorityUpdate коммита версии: 0..5, обязательный релиз - наибольший
MANDATORY_PRIORITY = 5
# Код выхода «магазин требует ручной загрузки»: новое чувствительное разрешение в APK объявляется только в консоли RuStore
MANUAL_UPLOAD_EXIT = 3


class RuStoreError(RuntimeError):
    def __init__(self, message, reason=""):
        super().__init__(message)
        self.reason = reason


class Queued(Exception):
    """Магазин модерирует другую версию: эта не отправляется и уйдёт после её публикации."""


class ManualUploadNeeded(RuStoreError):
    """APK несёт новое чувствительное разрешение: API его не примет, пока разрешение не объявлено в консоли."""


def load_key(text):
    from cryptography.hazmat.primitives import serialization

    text = text.strip()
    if "BEGIN" in text:
        return serialization.load_pem_private_key(text.encode(), None)
    raw = base64.b64decode(text)
    try:
        return serialization.load_der_private_key(raw, None)
    except ValueError:
        # base64 от PEM-файла
        return serialization.load_pem_private_key(raw, None)


class RuStore:
    def __init__(self, key_id, private_key, package):
        self.package = package
        self.http = net.session()
        self.http.headers["Public-Token"] = self._token(key_id, load_key(private_key))

    def _token(self, key_id, key):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")
        signature = base64.b64encode(key.sign((key_id + stamp).encode(), padding.PKCS1v15(), hashes.SHA512())).decode()
        response = net.send(None, "POST", f"{BASE}/public/auth/", mode=net.IDEMPOTENT,
                            json={"keyId": key_id, "timestamp": stamp, "signature": signature}, timeout=60)
        return self._body(response, "auth")["jwe"]

    @staticmethod
    def _body(response, what):
        # Тело ответа - только в перехваченный вывод (зашифрованный журнал), в публичный журнал идёт лишь код
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code >= 300 or data.get("code") != "OK":
            print(response.text)
            # Причина отказа магазина - его же короткий текст (без данных игры): видна в публичном журнале без расшифровки
            reason = str(data.get("message") or "")[:200] if isinstance(data, dict) else ""
            if "sensitive permission" in reason.lower():
                raise ManualUploadNeeded(f"{what}: HTTP {response.status_code}", reason)
            if reason:
                say(f"::error::RuStore {what}: {reason}")
            raise RuStoreError(f"{what}: HTTP {response.status_code}", reason)
        return data.get("body")

    def _app(self, suffix=""):
        return f"{BASE}/public/v1/application/{self.package}/version{suffix}"

    def versions(self):
        """Версии приложения: список словарей с versionId, versionName, versionCode, versionStatus."""
        body = self._body(net.send(self.http, "GET", self._app(), params={"size": 50}, timeout=60), "versions")
        return body.get("content", []) if isinstance(body, dict) else (body or [])

    def newest(self):
        """Версия с наибольшим versionCode или None."""
        return max((v for v in self.versions() if v.get("versionCode")), key=lambda v: int(v["versionCode"]), default=None)

    def standing(self):
        """Что в магазине сейчас: наибольший versionId живой версии (0 - нет) и коды версий, ждущих модерации или публикации.
        Живую версию отмечаем по versionId, а не по versionCode: у версий, загруженных через консоль, магазин отдаёт versionCode -1."""
        versions = self.versions()
        live = max((int(v["versionId"]) for v in versions if str(v.get("versionStatus", "")).upper() in LIVE and v.get("versionId")), default=0)
        waiting = sorted(int(v.get("versionCode") or 0) for v in versions if str(v.get("versionStatus", "")).upper() not in SETTLED)
        return live, waiting

    @staticmethod
    def availability(version):
        return 1.0 if str(version.get("versionStatus", "")).upper() in LIVE else 0.0

    def submit(self, apk, version_code, notes, mandatory=False):
        """Черновик версии, APK и отправка на модерацию; публикация сразу после неё (publishType INSTANTLY)."""
        existing = self.versions()
        if any(str(v.get("versionCode")) == str(version_code) and str(v.get("versionStatus", "")).upper() not in {"DRAFT", "ARCHIVED"} for v in existing):
            say(f"RuStore: version {version_code} is already submitted")
            return
        # Новая версия поверх ждущей модерации отправляет ту в архив, и до игроков не доходит ни одна: пока магазин модерирует
        # другую версию, эта ждёт; после публикации почасовая store-status сама отправит самую свежую (rustore_manual.retry)
        busy = [v for v in existing if str(v.get("versionStatus", "")).upper() not in SETTLED]
        if busy:
            say(f"::notice::RuStore: {busy[0].get('versionName')} is still in review, {version_code} waits and goes out after its publication")
            raise Queued()
        # Черновик не правится, только удаляется: брошенный прошлым прогоном уходит перед новым
        for draft in (v for v in existing if str(v.get("versionStatus", "")).upper() == "DRAFT"):
            self._body(net.send(self.http, "DELETE", self._app(f"/{draft['versionId']}"), timeout=60), "draft delete")
        draft = {"whatsNew": short_notes(notes, NOTES_LIMIT), "publishType": "INSTANTLY"}
        contacts = developer_contacts()
        if contacts:
            draft["developerContacts"] = contacts
        version_id = self._body(net.send(self.http, "POST", self._app(), json=draft, timeout=60), "draft create")
        try:
            with open(apk, "rb") as file:
                self._body(net.send(self.http, "POST", self._app(f"/{version_id}/apk"), params={"isMainApk": "true", "servicesType": "Unknown"},
                                          files={"file": (os.path.basename(apk), file, "application/vnd.android.package-archive")},
                                          timeout=1800), "apk upload")
        except RuStoreError:
            # Черновик без APK в консоли выглядит как «версия без пакета»: убираем его, а не оставляем пустым
            self._drop_draft(version_id)
            raise
        priority = MANDATORY_PRIORITY if mandatory else 0
        self._body(net.send(self.http, "POST", self._app(f"/{version_id}/commit"), params={"priorityUpdate": priority}, timeout=60), "commit")

    def _drop_draft(self, version_id):
        try:
            self._body(net.send(self.http, "DELETE", self._app(f"/{version_id}"), timeout=60), "draft delete")
        except (RuStoreError, OSError):
            say("::warning::RuStore: the empty draft could not be deleted, remove it in the console")


def developer_contacts():
    """Контакты разработчика для карточки RuStore из переменных репозитория (RUSTORE_CONTACT_EMAIL обязателен для магазина,
    сайт и сообщество ВКонтакте - по желанию); пусто - поле не шлётся, магазин берёт заполненные в консоли."""
    fields = {"email": "RUSTORE_CONTACT_EMAIL", "website": "RUSTORE_CONTACT_WEBSITE", "vkCommunity": "RUSTORE_CONTACT_VK"}
    contacts = {key: os.environ.get(name, "").strip() for key, name in fields.items()}
    return {key: value for key, value in contacts.items() if value}


def main():
    if len(sys.argv) != 4 or sys.argv[1] != "upload":
        fail("usage: rustore.py upload <app.apk> <update.json>")
    apk, update = sys.argv[2], load_update(sys.argv[3])
    store = RuStore(os.environ["RUSTORE_KEY_ID"].strip(), os.environ["RUSTORE_PRIVATE_KEY"], os.environ["APP_ID"])
    try:
        store.submit(apk, update["versionCode"], update.get("notes", ""), bool(update.get("mandatory")))
    except Queued:
        return
    except ManualUploadNeeded as error:
        say(f"::warning::RuStore needs a manual upload of {update['versionName']}: {error.reason}")
        # Для шага выдачи APK: ждёт ли магазин модерации прошлой версии (тогда руками ничего не нужно) и что живо сейчас
        state = os.environ.get("RUSTORE_STATE", "").strip()
        if state:
            live, waiting = store.standing()
            with open(state, "w") as file:
                json.dump({"code": int(update["versionCode"]), "live": live, "waiting": waiting}, file)
            return
        sys.exit(MANUAL_UPLOAD_EXIT)
    say(f"RuStore: {update['versionName']} ({update['versionCode']}) sent to review with auto-publish")


if __name__ == "__main__":
    main()
