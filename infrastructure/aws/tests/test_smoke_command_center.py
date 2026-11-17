import io
import json
import unittest
from unittest.mock import patch
from uuid import UUID

from infrastructure.aws.smoke_command_center import verify


class SmokeCommandCenterTests(unittest.TestCase):
    def exercise(self, supported=False, split_bundle=False):
        requests = []

        def open_url(request, timeout):
            if isinstance(request, str):
                resources = {
                    'https://example.test': '<a href="/assets/command-center/index.html">open</a>',
                    'https://example.test/assets/command-center/index.html': '<div id="root"></div><script src="app.js"></script>',
                    'https://example.test/assets/command-center/app.js': '/api/v1/ai/query',
                }
                if split_bundle:
                    resources['https://example.test/assets/command-center/index.html'] += (
                        '<link rel="modulepreload" crossorigin href="chat.js">'
                    )
                    resources['https://example.test/assets/command-center/app.js'] = 'import "./chat.js"'
                    resources['https://example.test/assets/command-center/chat.js'] = '/api/v1/ai/query'
                return io.BytesIO(resources[request].encode())
            payload = json.loads(request.data)
            requests.append(payload)
            body = {"id": payload["id"], "status": "supported" if supported else "insufficient_evidence",
                    "citations": [], "charts": []}
            response = io.BytesIO(json.dumps(body).encode())
            response.headers = {"X-Request-Id": payload["id"]}
            return response

        with patch('infrastructure.aws.smoke_command_center.urlopen', side_effect=open_url):
            verify('https://example.test')
        return requests

    def test_probe_can_be_mapped_to_the_live_uuid_contract(self):
        payload, = self.exercise()
        self.assertEqual(str(UUID(payload['id'])), payload['id'])
        self.assertIn('antimateria', payload['question'])
        self.assertEqual(payload['experiment_ids'], [])

    def test_probe_rejects_unsupported_claims_about_missing_evidence(self):
        with self.assertRaises(AssertionError):
            self.exercise(supported=True)

    def test_probe_finds_api_path_in_preloaded_chat_module(self):
        self.assertEqual(len(self.exercise(split_bundle=True)), 1)
