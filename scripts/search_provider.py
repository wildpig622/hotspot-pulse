"""Standalone, explicit free keyless search probe; no paid/account fallback.

Search results are leads, never event facts. Not scheduled by the service.
"""
import argparse
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def search(query, transport=None):
    if not isinstance(query, str) or not query.strip() or len(query) > 300:
        raise ValueError('bounded_query_required')
    request = urllib.request.Request('https://api.tavily.com/search',
        data=json.dumps({'query': query, 'max_results': 5, 'search_depth': 'basic',
                         'include_answer': False, 'include_raw_content': False}).encode(),
        headers={'Content-Type': 'application/json', 'X-Tavily-Access-Mode': 'keyless'}, method='POST')
    start = time.monotonic()
    result = {'provider': 'tavily_keyless', 'query': query, 'checked_at': datetime.now(timezone.utc).isoformat(),
              'paid_api_calls': 0, 'scheduled_service': False, 'quality_accepted': False}
    try:
        with (transport or urllib.request.urlopen)(request, timeout=15) as response:
            raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ValueError('response_size_limit')
            payload = json.loads(raw)
            if not isinstance(payload.get('results'), list):
                raise ValueError('provider_response_not_search_results')
            def short(value):
                value = re.sub(r'[\w.+-]+[@＠][\w.-]+\.[A-Za-z]{2,}|(?<!\d)1[3-9]\d{9}(?!\d)|(?<!\d)0\d{2,3}[- ]\d{7,8}(?!\d)', '[CONTACT_REMOVED]', str(value))
                return value[:160]
            result.update(status='ok', http_status=response.status,
                          results=[{'title': short(r.get('title')), 'url': r.get('url'), 'snippet': short(r.get('content'))} for r in payload['results'][:5]])
    except Exception as exc:
        result.update(status='failed', http_status=getattr(exc, 'code', None), error_type=type(exc).__name__,
                      error='rate_limited_no_retry' if getattr(exc, 'code', None) == 429 else str(exc)[:160], results=[])
    result['elapsed_seconds'] = round(time.monotonic() - start, 3)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--query', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(Path(__file__).resolve().parents[1] / 'site'):
        parser.error('Use an isolated report path, not the production site.')
    result = search(args.query)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'status': result['status'], 'results': len(result['results']), 'paid_api_calls': 0}))


if __name__ == '__main__':
    main()
