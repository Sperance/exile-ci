import os
import subprocess
import sys
import tempfile
import unittest

GUARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guard-permissions.py")

CALLED = """
name: Called
on:
  workflow_call:
jobs:
  release:
    runs-on: ubuntu-24.04
    permissions:
      contents: write
      packages: write
"""

CALLED_WITH_PAGES = """
name: Called with pages
on:
  workflow_call:
jobs:
  release:
    runs-on: ubuntu-24.04
    permissions:
      contents: write
      pages: write
      id-token: write
"""


def caller(rights, target="telegram.yml", step="bash ci/dispatch-wait.sh telegram.yml main"):
    return f"""
name: Caller
on:
  workflow_dispatch:
jobs:
  run:
    runs-on: ubuntu-24.04
    permissions:
{rights}
    steps:
      - run: {step}
"""


class PermissionsGuardTest(unittest.TestCase):
    def run_guard(self, files):
        with tempfile.TemporaryDirectory() as root:
            folder = os.path.join(root, ".github", "workflows")
            os.makedirs(folder)
            for name, text in files.items():
                with open(os.path.join(folder, name), "w", encoding="utf-8") as out:
                    out.write(text)
            done = subprocess.run([sys.executable, "-I", GUARD, root], capture_output=True, text=True, encoding="utf-8")
            return done.returncode, done.stdout + done.stderr

    def test_called_workflow_without_the_rights_is_red(self):
        code, output = self.run_guard({
            "caller.yml": """
name: Caller
on:
  workflow_dispatch:
jobs:
  run:
    uses: ./.github/workflows/telegram.yml
    permissions:
      contents: write
""",
            "telegram.yml": CALLED,
        })
        self.assertEqual(code, 1, output)
        self.assertIn("packages: write", output)

    def test_called_workflow_with_the_rights_is_green(self):
        code, output = self.run_guard({
            "caller.yml": """
name: Caller
on:
  workflow_dispatch:
jobs:
  run:
    uses: ./.github/workflows/telegram.yml
    permissions:
      contents: write
      packages: write
""",
            "telegram.yml": CALLED,
        })
        self.assertEqual(code, 0, output)

    def test_started_workflow_keeps_its_own_rights(self):
        code, output = self.run_guard({
            "caller.yml": caller("      actions: write"),
            "telegram.yml": CALLED_WITH_PAGES,
        })
        self.assertEqual(code, 0, output)

    def test_start_without_the_right_to_start_is_red(self):
        code, output = self.run_guard({
            "caller.yml": caller("      contents: write"),
            "telegram.yml": CALLED,
        })
        self.assertEqual(code, 1, output)
        self.assertIn("actions: write", output)


if __name__ == "__main__":
    unittest.main()
