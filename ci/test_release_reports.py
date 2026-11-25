import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
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

    def test_new_qa_reference_requires_an_explicit_queue(self):
        client = ["Issue: #32"]
        with self.assertRaisesRegex(release_state.Unreadable, "no Report-Queue"):
            release_state.qualified_issue_numbers(client, [], "owner/client", "test", require_queue=True)
        self.assertEqual(release_state.qualified_issue_numbers(client, [], "owner/client", "test"), [])

    def test_ambiguous_origin_and_unreadable_history_fail_closed(self):
        with self.assertRaises(release_state.Unreadable):
            release_state.qualified_issue_numbers(["Issue: #42\nReport-Queue: test\nReport-Queue: prod"], [], "owner/client", "test")
        with patch.object(release_state, "run", return_value=None):
            with self.assertRaises(release_state.Unreadable):
                release_state.messages("client", "base", "head", strict=True)

    def close_report(self, before=None, after=None, written=None, test=False):
        with tempfile.TemporaryDirectory() as scratch:
            posted = Path(scratch) / "posted"
            result = subprocess.run(
                ["bash", "-eu", "-c", """
source "$1"
posted=$2 before=$3 after=$4 written=$5 test=$6
qa_in_release() { [[ $1 == 6353 ]] || return 2; }
netcall() {
  case $1 in
    read)
      reply=$before
      if [[ -e $posted ]]; then reply=$after; fi
      [[ -n $reply ]] || return 22
      printf '%s\n' "$reply"
      ;;
    idem)
      touch "$posted"
      [[ -n $written ]] || return 22
      printf '%s\n' "$written"
      ;;
    *) return 1 ;;
  esac
}
REPORTS_WORK_TOKEN=fixture close_issues https://example.test "$test" v1.2.3 42
""", "fixture", os.path.join(os.path.dirname(__file__), "issues-lib.sh"), str(posted),
                 *(json.dumps({"data": value}) if value is not None else "" for value in (before, after, written)),
                 "true" if test else "false"],
                capture_output=True, text=True, check=False,
            )
            return result, posted.exists()

    def test_release_closure_accepts_omitted_open_state(self):
        result, posted = self.close_report(
            before={"summary": {"number": 42, "revision": 9, "labels": ["ready"]}},
            written={"number": 42, "state": "closed", "stateReason": "completed", "labels": ["v1.2.3"]},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(posted)
        self.assertIn("closed in v1.2.3", result.stdout)

    def test_release_closure_defers_work_and_new_author_replies(self):
        for fields, detail in (
            ({"labels": ["disputed"]}, {}),
            ({"labels": ["in-progress"]}, {}),
            ({"workId": "active"}, {}),
            ({"labels": ["verified"], "readyBuild": 6353}, {"authorReplyAfterVerificationAt": 100}),
        ):
            with self.subTest(fields=fields, detail=detail):
                result, posted = self.close_report(
                    before={"summary": {"number": 42, "test": True, "revision": 9, **fields}, **detail}, test=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("keeping the report open", result.stdout)
                self.assertFalse(posted)

    def test_release_closure_skips_prod_reports_without_ready_stage(self):
        for labels in ([], ["in-progress"], ["verified"], ["ready", "in-progress"]):
            with self.subTest(labels=labels):
                result, posted = self.close_report(before={"summary": {"number": 42, "revision": 9, "labels": labels}})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("keeping the report open", result.stdout)
                self.assertFalse(posted)

    def test_release_closure_does_not_write_without_matching_queue_and_build(self):
        for fields in ({}, {"test": True}):
            with self.subTest(fields=fields):
                result, posted = self.close_report(
                    before={"summary": {"number": 42, "revision": 9, "labels": ["ready"], **fields}}, test=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("could not verify release closure", result.stderr)
                self.assertFalse(posted)

    def test_release_closure_rechecks_when_author_returns_fix_during_write(self):
        result, posted = self.close_report(
            before={"summary": {"number": 42, "test": True, "revision": 9, "labels": ["ready"], "readyBuild": 6353}},
            after={"summary": {"number": 42, "test": True, "revision": 10, "labels": ["disputed"]}},
            test=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(posted)
        self.assertIn("keeping the report open", result.stdout)

    def test_release_closure_reports_when_the_queue_cannot_be_verified(self):
        ready = {"summary": {"number": 42, "test": True, "revision": 9, "labels": ["ready"], "readyBuild": 6353}}
        for before in (None, ready):
            with self.subTest(before=before):
                result, posted = self.close_report(before=before, test=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(posted, before is not None)
                self.assertIn("could not verify release closure", result.stderr)
