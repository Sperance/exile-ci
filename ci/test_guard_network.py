"""Сторож сети: путь файла в журнале и в ci/net-allowlist.txt - всегда через прямой слэш.

os.path.relpath на Windows вернул бы ci\net.py, и ни одна запись allowlist не совпала бы: локальный прогон precheck
на Windows красил бы вручную допущенные сетевые вызовы. Тест держит нормализацию, на Linux он тоже проходит."""
import importlib.util
import os
import unittest

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guard-network.py")
SPEC = importlib.util.spec_from_file_location("guard_network", PATH)
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)


class Slashed(unittest.TestCase):
    def test_nested_path_uses_forward_slashes(self):
        self.assertEqual("ci/net.py", GUARD.slashed(os.path.join("repo", "ci", "net.py"), "repo"))

    def test_workflow_path_uses_forward_slashes(self):
        self.assertEqual(".github/workflows/check-wip.yml",
                         GUARD.slashed(os.path.join("repo", ".github", "workflows", "check-wip.yml"), "repo"))


if __name__ == "__main__":
    unittest.main()
