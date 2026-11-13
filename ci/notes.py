"""Заметки выпуска: разбор RELEASE_NOTES.md на разделы. Общий для bump-release, release-files, магазинов, постов Telegram и проверок.

Раздел выпуска начинается с `## Следующая версия` (после выпуска - `## <версия>`), внутри - подразделы `### Новое`, `### Изменения`,
`### Исправления`, `### Техническое` (последний), в них пункты «- ». Пункт с меткой «[сервер]» в начале - изменение сервера: его
отдельным постом выкладывает Release → server, а в посте версии он идёт блоком «Уже в игре». Подраздел «Техническое» и пункты с
прежним началом «Техническое:» - только для персонала игры: в магазины и игроку они не идут. HTML-комментарии (метка `<!-- quiet -->`)
в разбор не входят. Только стандартная библиотека; в журнал ничего не пишет.
"""
import re

NEXT_HEADING = "## Следующая версия"
SECTIONS = ("Новое", "Изменения", "Исправления", "Техническое")
STAFF_SECTION = "Техническое"
SERVER_MARK = "[сервер]"
LEGACY_STAFF = re.compile(r"^Техническое:\s*", re.IGNORECASE)
MANDATORY = re.compile(r"^обновление обязательное\.?$", re.IGNORECASE)
COMMENT = re.compile(r"<!--.*?(-->|$)", re.DOTALL)
BULLET = re.compile(r"^[-*]\s+")


class Notes:
    """Пункты по разделам в порядке файла. Ключ "" - пункты вне подразделов (прежний плоский вид)."""

    def __init__(self):
        self.sections = {}
        self.unknown = []
        self.order = []

    def add(self, section, item):
        if section not in self.sections:
            self.sections[section] = []
        self.sections[section].append(item)

    def items(self, section):
        return self.sections.get(section, [])

    def all_items(self):
        return [item for items in self.sections.values() for item in items]


def is_server(item):
    return item.startswith(SERVER_MARK)


def strip_server(item):
    return item[len(SERVER_MARK):].strip() if is_server(item) else item


def strip_staff(item):
    return LEGACY_STAFF.sub("", item)


def is_staff(section, item):
    return section == STAFF_SECTION or LEGACY_STAFF.match(item) is not None


def normalize(item):
    """Вид пункта для сравнения: без метки сервера и прежнего «Техническое:», пробелы сжаты, регистр не важен."""
    return re.sub(r"\s+", " ", strip_staff(strip_server(item.strip()))).strip().casefold()


def parse(text):
    """Разбор тела раздела (заголовок `## ` и комментарии пропускаются)."""
    notes = Notes()
    section = ""
    for raw in COMMENT.sub("", text).splitlines():
        line = raw.strip()
        if not line or line.startswith("## "):
            continue
        if line.startswith("### "):
            section = line[4:].strip()
            notes.order.append(section)
            if section not in SECTIONS:
                notes.unknown.append(section)
            continue
        item = BULLET.sub("", line).strip()
        if item:
            notes.add(section, item)
    return notes


def next_section(text):
    """Тело раздела `## Следующая версия` файла (без заголовка) или None, если его нет."""
    lines = text.split("\n")
    starts = [i for i, line in enumerate(lines) if line.strip() == NEXT_HEADING]
    if len(starts) != 1:
        return None
    end = next((i for i in range(starts[0] + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[starts[0] + 1:end])


def problems(text):
    """Что не так с разделом выпуска: неизвестный или повторный подраздел, «Техническое» не последним, пункты вне подразделов."""
    notes = parse(text)
    found = []
    for title in notes.unknown:
        found.append(f"unknown subsection '{title}' (allowed: {', '.join(SECTIONS)})")
    if len(set(notes.order)) != len(notes.order):
        found.append("a subsection is repeated")
    known = [title for title in notes.order if title in SECTIONS]
    if known != sorted(known, key=SECTIONS.index):
        found.append(f"subsections must go in the order {', '.join(SECTIONS)}")
    if notes.items(""):
        found.append("items outside subsections")
    for title, items in notes.sections.items():
        if title and not items:
            found.append(f"subsection '{title}' is empty")
    return found


def public_items(notes):
    """Пункты для игрока и магазинов в порядке разделов: без «Техническое», обязательности и пунктов сервера."""
    ordered = [title for title in SECTIONS if title != STAFF_SECTION] + [""]
    return [item for title in ordered for item in notes.items(title)
            if not is_staff(title, item) and not is_server(item) and not MANDATORY.match(item)]


def plural_changes(count):
    tail, hundreds = count % 10, count % 100
    if tail == 1 and hundreds != 11:
        return "изменение"
    if 2 <= tail <= 4 and not 12 <= hundreds <= 14:
        return "изменения"
    return "изменений"


def store_summary(text, limit):
    """Выжимка для «Что нового» магазинов не длиннее limit знаков: публичные пункты (public_items: «Новое», «Изменения», «Исправления»,
    потом пункты вне подразделов; без «Техническое», пунктов сервера и обязательности) целыми строками «- пункт», пока влезают; не влезло -
    последней строкой «…и ещё N изменений в игре» (она входит в предел). Пункт не режется: первый невлезший и все после него уходят в N."""
    items = public_items(parse(text))
    lines = [f"- {item}" for item in items]
    full = "\n".join(lines)
    if len(full) <= limit:
        return full
    for kept in range(len(lines) - 1, -1, -1):
        left = len(lines) - kept
        tail = f"…и ещё {left} {plural_changes(left)} в игре"
        candidate = "\n".join(lines[:kept] + [tail])
        if len(candidate) <= limit:
            return candidate
    return tail[:limit]


def rewrite_without_empty(text):
    """Раздел выпуска без пустых подразделов (при выпуске заголовки без пунктов не остаются)."""
    lines = text.split("\n")
    out = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("### "):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("### ") and not lines[j].startswith("## "):
                j += 1
            block = lines[i + 1:j]
            if any(BULLET.match(line.strip()) for line in block):
                out.extend(lines[i:j])
            i = j
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)
