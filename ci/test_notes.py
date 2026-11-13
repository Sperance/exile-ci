import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import notes

FULL = """## Следующая версия
### Новое
- Новый герой
- [сервер] Серверное новшество
### Изменения
- Баланс огня
### Исправления
- Падение в меню
### Техническое
- Рефакторинг
"""


class StoreSummaryTest(unittest.TestCase):
    def test_fits_fully_without_server_and_technical(self):
        self.assertEqual(notes.store_summary(FULL, 500), "- Новый герой\n- Баланс огня\n- Падение в меню")

    def test_truncates_by_whole_items_with_counted_suffix(self):
        text = "### Новое\n- " + "а" * 100 + "\n- " + "б" * 100 + "\n### Исправления\n- " + "в" * 100
        result = notes.store_summary(text, 230)
        self.assertEqual(result, "- " + "а" * 100 + "\n…и ещё 2 изменения в игре")
        self.assertLessEqual(len(result), 230)
        self.assertLessEqual(len(notes.store_summary(text, 100)), 100)

    def test_order_is_new_changes_fixes(self):
        text = "### Исправления\n- ф\n### Новое\n- н\n### Изменения\n- и\n"
        self.assertEqual(notes.store_summary(text, 500), "- н\n- и\n- ф")

    def test_plural_forms(self):
        forms = {1: "изменение", 2: "изменения", 4: "изменения", 5: "изменений", 11: "изменений", 12: "изменений", 21: "изменение", 22: "изменения", 111: "изменений", 100: "изменений"}
        for count, form in forms.items():
            self.assertEqual(notes.plural_changes(count), form, count)

    def test_no_sections(self):
        self.assertEqual(notes.store_summary("- Раз\n- Два\nТехническое: внутреннее\n- Обновление обязательное.", 500), "- Раз\n- Два")

    def test_empty(self):
        self.assertEqual(notes.store_summary("### Техническое\n- Только для своих\n", 500), "")

    def test_limit_never_exceeded(self):
        text = "### Новое\n" + "\n".join(f"- пункт номер {i} с текстом" for i in range(60))
        for limit in (40, 120, 500):
            self.assertLessEqual(len(notes.store_summary(text, limit)), limit)


if __name__ == "__main__":
    unittest.main()
