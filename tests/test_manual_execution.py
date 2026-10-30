import contextlib
import io
import json
import unittest
from unittest.mock import patch

from scripts.check_manual_execution import CONFIRMATIONS, main, request_errors


class ManualExecutionTests(unittest.TestCase):
    sha = "a" * 40

    def request(self, action="collect", **changes):
        return {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
                "GITHUB_SHA": self.sha, "REQUESTED_SHA": self.sha,
                "REQUEST_CONFIRMATION": CONFIRMATIONS[action], **changes}

    def test_each_action_accepts_only_an_explicit_manual_request_for_its_commit(self):
        for action in CONFIRMATIONS:
            self.assertEqual(request_errors(action, self.request(action)), [])

    def test_automatic_events_are_denied_even_with_all_confirmation_fields(self):
        for event in ("push", "schedule", "pull_request", "workflow_run", "repository_dispatch", ""):
            for action in CONFIRMATIONS:
                with self.subTest(event=event, action=action):
                    self.assertIn("manual_dispatch_required", request_errors(action, self.request(action, GITHUB_EVENT_NAME=event)))

    def test_other_branches_and_tags_are_denied(self):
        for ref in ("refs/heads/fix/manual-audit-regressions", "refs/tags/main", "refs/pull/2/merge", "main", ""):
            self.assertIn("main_branch_required", request_errors("collect", self.request(GITHUB_REF=ref)))

    def test_blank_abbreviated_stale_or_decorated_commits_are_denied(self):
        for value in ("", "a" * 7, "b" * 40, "main", "a" * 40 + "\n", " a" * 20, "$(echo approved)"):
            with self.subTest(value=value):
                self.assertTrue(request_errors("collect", self.request(REQUESTED_SHA=value)))
        self.assertIn("invalid_workflow_sha", request_errors("collect", self.request(GITHUB_SHA="main")))

    def test_confirmation_is_action_specific_and_cannot_be_a_boolean_or_whitespace(self):
        for action in CONFIRMATIONS:
            for value in ("", "true", "yes", CONFIRMATIONS[action] + " ", "DEPLOY_REVIEWED_SITE" if action == "collect" else "COLLECT_PENDING_ONLY"):
                self.assertIn("explicit_action_confirmation_required", request_errors(action, self.request(action, REQUEST_CONFIRMATION=value)))
        self.assertEqual(request_errors("unknown", self.request()), ["unknown_action"])

    def test_cli_denial_is_nonzero_and_reports_only_reasons(self):
        output = io.StringIO()
        with patch.dict("os.environ", {}, clear=True), contextlib.redirect_stdout(output):
            self.assertEqual(main(["collect"]), 1)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "DENIED")
        self.assertEqual(len(result["reasons"]), 5)

    def test_successful_cli_checks_inputs_without_executing_collection_or_deployment(self):
        for action in CONFIRMATIONS:
            output = io.StringIO()
            with patch.dict("os.environ", self.request(action), clear=True), contextlib.redirect_stdout(output):
                self.assertEqual(main([action]), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["status"], "REQUEST_VALIDATED")
            self.assertFalse(result["execution_performed"])


if __name__ == "__main__":
    unittest.main()
