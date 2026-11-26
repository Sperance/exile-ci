import importlib.util
import os
import unittest

FOLDER = os.path.dirname(os.path.abspath(__file__))


def load():
    path = os.path.join(FOLDER, "test-history.py")
    spec = importlib.util.spec_from_file_location("test_history_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


history = load()


class GameCommitTest(unittest.TestCase):
    def test_game_types(self):
        self.assertTrue(history.GAME_TYPES.match("feat: a new hero"))
        self.assertTrue(history.GAME_TYPES.match("fix(core): a crash"))
        self.assertTrue(history.GAME_TYPES.match("perf: a faster fight"))
        self.assertFalse(history.GAME_TYPES.match("chore: pin the server"))
        self.assertFalse(history.GAME_TYPES.match("docs: record the cause"))

    def test_release_commit_is_a_service_commit(self):
        self.assertTrue(history.is_service("feat: release 0.26.0", "Server-Update: yes\nVerified: ci\n"))
        self.assertTrue(history.is_service("feat: release 0.26.0", ""))
        self.assertTrue(history.is_service("chore: something of the ci", "Verified: ci\n"))

    def test_game_commit_is_not_a_service_commit(self):
        self.assertFalse(history.is_service("feat: a new hero", "Issue: #12\n"))
        self.assertFalse(history.is_service("fix: a crash", "Verified: diff read\n"))
        self.assertFalse(history.is_service("feat: a new hero", ""))


if __name__ == "__main__":
    unittest.main()
