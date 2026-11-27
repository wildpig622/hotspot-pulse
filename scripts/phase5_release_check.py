"""Explicit isolated release exercise. Never called by refresh_service or CI."""
import concurrent.futures
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from .business_service import ROOT, FIELDS, build
from .phase3_discovery import Reader, document

OUT = ROOT / 'docs/phase5-release-2026-11-27'
PRIVATE = ROOT / 'review/phase5'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf8')


def prepare():
    site = PRIVATE / 'site'
    site.mkdir(parents=True, exist_ok=True)
    for path in (ROOT / 'site').iterdir():
        if path.is_file():
            shutil.copy2(path, site / path.name)
    # Legacy snapshots copied solely to the ignored local isolated preview.
    shutil.copytree(ROOT / 'site/api', site / 'api', dirs_exist_ok=True)
    prior = json.loads((ROOT / 'docs/phase4-review-2026-11-27/high-value-review.json').read_text(encoding='utf8'))
    official = {r['event_id']: r for r in json.loads((ROOT / 'docs/phase2-evidence-2026-11-26/official-events.json').read_text(encoding='utf8'))}
    for old in prior:
        original = official.get(old['event_id'], {})
        old['first_seen_at'] = old.get('first_seen_at') or old.get('last_evidence_check_at')
        if not old.get('short_evidence') and original.get('evidence_excerpt'):
            old['short_evidence'] = [original['evidence_excerpt'][:160]]
    rows = []
    for old in prior:
        row = {k: old[k] for k in FIELDS if k in old}
        row.update(source_url=old['source_urls'][0], observed_at=old['first_seen_at'], observation_type='observed')
        # Phase4 deliberately retained ambiguous multi-day bounds, not inferred sessions.
        if not row.get('short_evidence'):
            continue
        rows.append(row)
    batch = {'schema_version': 'agent-import-1', 'method': 'Explicit migration of previously reviewed evidence, NOT new autonomous discovery or human verification.', 'data': rows}
    ledger = json.loads((ROOT / 'docs/phase4-review-2026-11-27/observations.json').read_text(encoding='utf8'))
    for observation in ledger['observations']:
        if observation['observation_type'] == 'observed':
            continue
        base = next((r for r in rows if r['event_id'] == observation['record_id']), None)
        quotes = [q.get('quote', '') for q in observation.get('date_evidence', []) if isinstance(q, dict)]
        if base and quotes:
            followup = dict(base, observation_type=observation['observation_type'], observed_at=observation['observed_at'],
                            source_url=observation['source_url'], short_evidence=quotes, signal_kind='status_change')
            rows.append(followup)
    write(OUT / 'agent-import-example.json', batch)
    result = build(site / 'api/v1', imports=rows)
    return prior, result


def live(prior, number):
    # Independent reader/cache and actual requests in each invocation.
    output = PRIVATE / ('run-' + str(number) + '-' + datetime.now(timezone.utc).strftime('%H%M%S'))
    reader = Reader(output, interval=1)
    official_ids = {'off_1cf212722b4c', 'off_04f5d5bcf753', 'off_29537fcfce98'}
    targets = [r for r in prior if r['event_id'] in official_ids]
    # Also exercise actual structured-source collector parsing, without invoking production.
    targets += [r for r in prior if r['event_id'] in {'p4_industry_jinan', 'p4_yeshirong_extra'}]
    def visit(row):
        body, check = reader.fetch(row['source_urls'][0], 'release_evidence_recheck')
        _, text, _ = document(body)
        quotes = [q for q in row['short_evidence'] if q and q in text]
        compact = {k: check[k] for k in ('url', 'status', 'error', 'error_type', 'http_status', 'checked_at', 'sha256', 'bytes', 'elapsed_seconds') if k in check}
        compact.update(event_id=row['event_id'], literal_evidence_matched=bool(quotes), short_evidence=quotes[:2], review_status='pending')
        # A body match is evidence freshness only. It cannot confirm a changed date/status.
        return compact
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        checks = list(pool.map(visit, targets))
    provider = []
    for city in ('西安', '济南', '天津'):
        query = city + ' 最近7天 演唱会 官宣 加场'
        body, check = reader.fetch('https://www.bing.com/search?' + urlencode({'format': 'rss', 'q': query}), 'independent_search_provider_probe')
        provider.append({'query': query, 'check': {k: v for k, v in check.items() if k not in {'raw_file', 'encoding'}}, 'result_body_available': bool(body), 'quality_accepted': False})
    write(output / 'run.json', {'checks': reader.checks})
    # Feed incremental real observations only where literal existing evidence recurs.
    lookup = {r['event_id']: r for r in prior}
    imports = []
    for check in checks:
        if check['status'] == 'ok' and check['literal_evidence_matched']:
            old = lookup[check['event_id']]
            row = {k: old[k] for k in FIELDS if k in old}
            row.update(source_url=check['url'], observed_at=check['checked_at'], short_evidence=check['short_evidence'], observation_type='observed')
            imports.append(row)
    result = build(PRIVATE / 'site/api/v1', imports=imports)
    report = {'run': number, 'completed_at': datetime.now(timezone.utc).isoformat(), 'scope': 'Bounded evidence rechecks of existing three-city official/organizer records, NOT full production collection or fresh discovery.',
              'checks': checks, 'provider': provider, 'actual_request_count_including_robots': len(reader.checks),
              'download_bytes': sum(c.get('bytes', 0) for c in reader.checks), 'request_seconds': round(sum(c.get('elapsed_seconds', 0) for c in reader.checks), 3),
              'status': result['status'], 'fresh_observations_added': len(imports),
              'configured_provider_credentials': {name: bool(os.environ.get(name)) for name in ('BRAVE_SEARCH_API_KEY', 'TAVILY_API_KEY', 'SERPER_API_KEY')},
              'paid_api_calls': 0, 'autonomous_search_accepted': False}
    write(OUT / ('live-run-' + str(number) + '.json'), report)
    return report


def main():
    prior, initial = prepare()
    reports = [live(prior, 1), live(prior, 2)]
    api = PRIVATE / 'site/api/business'
    for name in ('focus', 'calendar', 'intelligence', 'changes', 'status'):
        shutil.copy2(api / (name + '.json'), OUT / ('api-' + name + '.json'))
    write(OUT / 'isolated-integrity.json', {'production_api_sha256': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / 'site/api').rglob('*.json')},
                                          'initial_events': initial['status']['event_count'], 'runs': [r['status'] for r in reports]})
    print(json.dumps({'initial_events': initial['status']['event_count'], 'runs': [{'requests': r['actual_request_count_including_robots'], 'fresh_observations': r['fresh_observations_added']} for r in reports]}))


if __name__ == '__main__':
    main()
