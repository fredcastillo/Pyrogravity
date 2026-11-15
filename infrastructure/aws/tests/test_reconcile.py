import json
import os
import unittest
from unittest.mock import MagicMock, patch

from infrastructure.aws import reconcile


class ReconcileTests(unittest.TestCase):
    def run_case(self, published, runs):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = published.encode()
        with patch.dict(os.environ, GITHUB_REPOSITORY="fredcastillo/Pyrogravity"), \
             patch.object(reconcile, "urlopen", return_value=response), \
             patch.object(reconcile, "gh", side_effect=[json.dumps({"object": {"sha": "a" * 40}}), json.dumps({"workflow_runs": runs}), ""]) as gh:
            reconcile.main()
            return gh.call_args_list

    def test_current_release_never_dispatches(self):
        calls = self.run_case('/assets/releases/' + 'a' * 40 + '/demo.js', [])
        self.assertEqual(len(calls), 1)

    def test_missing_release_dispatches_ci(self):
        calls = self.run_case('old page', [])
        self.assertEqual(calls[-1].args[:3], ('workflow', 'run', 'ci.yml'))

    def test_active_run_prevents_duplicate(self):
        calls = self.run_case('old', [{"head_sha": "a" * 40, "event": "push", "status": "in_progress"}])
        self.assertEqual(len(calls), 2)

    def test_failed_build_has_bounded_retries(self):
        run = {"head_sha": "a" * 40, "event": "push", "status": "completed", "run_attempt": 3}
        with self.assertRaises(SystemExit):
            self.run_case('old', [run])
