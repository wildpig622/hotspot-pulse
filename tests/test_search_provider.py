import io
import json
import unittest
import urllib.error
from scripts.search_provider import search


class ProviderTests(unittest.TestCase):
    def test_keyless_only_bounded_minimal_results_and_no_raw_body(self):
        requests = []
        class Response(io.BytesIO):
            status = 200
        def transport(request, timeout):
            requests.append(request)
            return Response(json.dumps({'results': [{'title': '公告', 'url': 'https://example.org/1', 'content': 'x'*300, 'raw_content': 'private'}]}).encode())
        result = search('西安 最近7天 活动官宣', transport)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(len(result['results'][0]['snippet']), 160)
        self.assertNotIn('raw_content', result['results'][0])
        self.assertNotIn('Authorization', requests[0].headers)
        self.assertFalse(json.loads(requests[0].data)['include_raw_content'])

    def test_rate_limit_stops_without_retry_or_paid_fallback(self):
        calls = []
        def transport(request, timeout):
            calls.append(request)
            raise urllib.error.HTTPError(request.full_url, 429, 'limited', {}, None)
        result = search('天津 未来90天 考试', transport)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['error'], 'rate_limited_no_retry')
        self.assertEqual(result['paid_api_calls'], 0)
