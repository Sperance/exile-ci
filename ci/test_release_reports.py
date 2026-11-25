import os
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import release_state


class ReleaseReportTest(unittest.TestCase):
    def test_numbers_from_different_queues_never_share_a_release_target(self):
        repo = "owner/client"
        client = ["Issue: #42\nReport-Queue: test", "Issue: #43\nReport-Queue: prod", "Issue: #44"]
        server = ["Refs owner/client#42\nReport-Queue: prod", "Refs owner/client#45\nReport-Queue: test"]
        self.assertEqual(release_state.qualified_issue_numbers(client, server, repo, "test"), [42, 45])
        self.assertEqual(release_state.qualified_issue_numbers(client, server, repo, "prod"), [42, 43])
        self.assertEqual(release_state.issue_numbers(client, server, repo), [42, 43, 44, 45])

    def test_historical_fix_is_selected_only_for_closure(self):
        client = ["Report-Release: #42\nIssue: #43\nReport-Queue: test"]
        self.assertEqual(release_state.qualified_issue_numbers(client, [], "owner/client", "test"), [43])
        self.assertEqual(release_state.qualified_issue_numbers(client, [], "owner/client", "test", closing=True), [42, 43])

    def test_ambiguous_origin_and_unreadable_history_fail_closed(self):
        with self.assertRaises(release_state.Unreadable):
            release_state.qualified_issue_numbers(["Issue: #42\nReport-Queue: test\nReport-Queue: prod"], [], "owner/client", "test")
        with patch.object(release_state, "run", return_value=None):
            with self.assertRaises(release_state.Unreadable):
                release_state.messages("client", "base", "head", strict=True)

    def test_release_closure_accepts_omitted_open_state(self):
        result = subprocess.run(
            ["bash", "-eu", "-c", """
source "$1"
netcall() {
  case $1 in
    read) echo '{"data":{"summary":{"number":42,"revision":9}}}' ;;
    idem) echo '{"data":{"number":42,"state":"closed","stateReason":"completed","labels":["v1.2.3"]}}' ;;
    *) return 1 ;;
  esac
}
REPORTS_WORK_TOKEN=fixture close_issues https://example.test false v1.2.3 42
""", "fixture", os.path.join(os.path.dirname(__file__), "issues-lib.sh")],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("closed in v1.2.3", result.stdout)
