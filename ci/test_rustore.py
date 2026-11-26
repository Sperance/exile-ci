import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rustore
from rustore import blocking, in_review, standing_of, status_of, submitted, write_state

# Список версий магазина после выпуска 0.25.0: версия, залитая через консоль (code -1, имени нет), стала PREVIOUS_ACTIVE.
# Из-за неё выкладка 0.26.0 молча не уходила: статус не был в списке «не мешает», и версия считалась ждущей навсегда.
STORE_AFTER_025 = [
    {"versionId": 2064939106, "versionName": "0.25.0", "versionCode": 437, "versionStatus": "ACTIVE"},
    {"versionId": 2064938317, "versionName": "0.24.0", "versionCode": 433, "versionStatus": "ARCHIVED"},
    {"versionId": 2064875332, "versionName": None, "versionCode": -1, "versionStatus": "PREVIOUS_ACTIVE"},
]


class StatusTest(unittest.TestCase):
    def test_status_is_upper_case(self):
        self.assertEqual(status_of({"versionStatus": "moderation"}), "MODERATION")
        self.assertEqual(status_of({}), "")

    def test_only_review_statuses_block(self):
        self.assertTrue(in_review({"versionStatus": "MODERATION"}))
        self.assertTrue(in_review({"versionStatus": "APPROVED"}))
        self.assertTrue(in_review({"versionStatus": "READY_FOR_PUBLICATION"}))
        self.assertTrue(in_review({"versionStatus": "PENDING_PUBLICATION"}))
        self.assertFalse(in_review({"versionStatus": "ACTIVE"}))
        self.assertFalse(in_review({"versionStatus": "PREVIOUS_ACTIVE"}))
        self.assertFalse(in_review({"versionStatus": "ARCHIVED"}))
        self.assertFalse(in_review({"versionStatus": "DRAFT"}))

    def test_previous_active_does_not_block_the_store(self):
        self.assertEqual(blocking(STORE_AFTER_025), [])
        self.assertEqual(blocking(STORE_AFTER_025 + [{"versionId": 1, "versionName": "0.26.1", "versionCode": 439, "versionStatus": "MODERATION"}]),
                         [{"versionId": 1, "versionName": "0.26.1", "versionCode": 439, "versionStatus": "MODERATION"}])

    def test_submitted_ignores_draft_and_archived(self):
        versions = [{"versionCode": 438, "versionStatus": "DRAFT"}, {"versionCode": 437, "versionStatus": "ARCHIVED"}]
        self.assertFalse(submitted(versions, 438))
        self.assertFalse(submitted(versions, 437))
        self.assertTrue(submitted(versions + [{"versionCode": 438, "versionStatus": "MODERATION"}], 438))

    def test_standing_counts_live_and_waiting_only(self):
        live, waiting = standing_of(STORE_AFTER_025)
        self.assertEqual(live, 2064939106)
        self.assertEqual(waiting, [])
        live, waiting = standing_of(STORE_AFTER_025 + [{"versionId": 9, "versionName": "0.26.1", "versionCode": 439, "versionStatus": "MODERATION"}])
        self.assertEqual(live, 2064939106)
        self.assertEqual(waiting, [439])

    def test_standing_of_empty_store(self):
        self.assertEqual(standing_of([]), (0, []))


class StateFileTest(unittest.TestCase):
    def test_state_carries_the_reason(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "rustore-state.json")
            write_state(path, 438, 2064939106, [437], rustore.REASON_BUSY)
            with open(path, encoding="utf-8") as file:
                state = json.load(file)
        self.assertEqual(state["code"], 438)
        self.assertEqual(state["live"], 2064939106)
        self.assertEqual(state["waiting"], [437])
        self.assertEqual(state["reason"], "busy")


if __name__ == "__main__":
    unittest.main()
