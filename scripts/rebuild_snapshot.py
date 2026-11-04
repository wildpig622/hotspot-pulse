#!/usr/bin/env python3
"""Normalize a snapshot and prepare a reviewed activity calendar, fully offline."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path

try:
    from . import collect
    from .activity_registry import build_registry_payload, build_coverage
except ImportError:
    import collect
    from activity_registry import build_registry_payload, build_coverage


def rebuild(snapshot: dict, cities: list[dict], health: dict, today: date, generated_at: str,
            previous_activities: list[dict] | None = None, previous_calendar: dict | None = None) -> tuple[dict[str, dict], dict]:
    original = copy.deepcopy(snapshot)
    rows = [collect.enrich_existing_event(copy.deepcopy(row), today) for row in snapshot['data']]
    activity_payload = build_registry_payload(collect.ROOT, rows, cities, generated_at, today, previous_activities)
    if previous_calendar and 'source_candidates' in previous_calendar:
        activity_payload.update(source_candidates=copy.deepcopy(previous_calendar['source_candidates']), source_checks=copy.deepcopy(previous_calendar.get('source_checks', [])))
        activity_payload['meta'].update(schema_version='1.4', source_candidate_count=len(activity_payload['source_candidates']))
    linked = {lead_id: row['event_id'] for row in activity_payload['data'] for lead_id in row['related_lead_ids']}
    for row in rows:
        if row['event_id'] in linked:
            row['activity_id'] = linked[row['event_id']]
    changes = []
    for before, after in zip(original['data'], rows):
        if before['event_id'] != after['event_id']:
            raise ValueError('Migration changed a lead identity')
        for protected in ('review_status', 'event_status', 'sources', 'first_seen_at', 'last_seen_at', 'knowable_at'):
            if before.get(protected) != after.get(protected):
                raise ValueError('Migration changed protected field: ' + protected)
        fields = {key: {'before': before.get(key), 'after': after.get(key)}
                  for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
        if fields:
            changes.append({'event_id': before['event_id'], 'event_name': before['event_name'], 'fields': fields})
    meta = copy.deepcopy(snapshot.get('meta', {}))
    meta.update({
        'api_version': 'v1', 'schema_version': '1.2', 'generated_at': generated_at,
        'normalized_at': generated_at,
        'last_collection_at': meta.get('last_collection_at') or meta.get('generated_at') or health.get('last_run_at'),
        'coverage_status': 'partial', 'monitoring_horizon_days': collect.SCOPE['monitoring_horizon_days'],
        'candidate_count': len(rows), 'structured_activity_count': len(activity_payload['data']),
        'dated_candidate_count': sum(bool(row.get('start_at')) and row.get('date_precision') == 'day' for row in rows),
        'future_event_candidate_count': sum(collect.is_upcoming_event(row, today) for row in rows),
        'pending_count': sum(row.get('review_status') == 'pending' for row in rows),
        'verified_count': sum(row.get('review_status') == 'verified' for row in rows),
        'data_note': '新闻线索与activities.json活动日历分开。旧数据仅规范化；源采集时间不变，未自动核验。',
    })
    # generated_at describes this file; last_collection_at remains the RSS time.
    coverage = build_coverage(cities, list(collect.FEED_TOPICS), rows, activity_payload['data'], health.get('feed_results', []), generated_at, activity_payload['discovery_candidates'], activity_payload.get('source_candidates', []))
    city_payload = {'meta': {'api_version': 'v1', 'generated_at': generated_at, 'city_count': len(cities)}, 'data': [
        dict(city, candidate_count=sum(row.get('city_slug') == city['city_slug'] for row in rows),
             activity_count=sum(row['city_slug'] == city['city_slug'] for row in activity_payload['data'])) for city in cities
    ]}
    outputs = {'hotspots.json': {'meta': meta, 'data': rows}, 'activities.json': activity_payload,
               'coverage.json': coverage, 'cities.json': city_payload, 'health.json': copy.deepcopy(health)}
    report = {
        'status': 'OFFLINE_REBUILD_PENDING_REVIEW', 'as_of': today.isoformat(), 'generated_at': generated_at,
        'lead_count_before': len(original['data']), 'lead_count_after': len(rows),
        'lead_review_status_changes': 0, 'original_source_timestamp_changes': 0,
        'date_values_changed': sum(a.get('start_at') != b.get('start_at') or a.get('end_at') != b.get('end_at') for a, b in zip(original['data'], rows)),
        'date_starts_cleared': sum(bool(a.get('start_at')) and not b.get('start_at') for a, b in zip(original['data'], rows)),
        'structured_activity_count': len(activity_payload['data']),
        'future_structured_activity_count': activity_payload['meta']['future_activity_count'],
        'activity_type_counts': dict(Counter(row['event_type'] for row in activity_payload['data'])),
        'coverage_cells': len(coverage['data']), 'coverage_result': 'PARTIAL',
        'live_collection_run': False, 'automatic_verified_promotions': 0, 'changes': changes,
    }
    return outputs, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--today', type=date.fromisoformat)
    parser.add_argument('--generated-at')
    args = parser.parse_args()
    if args.output_dir.resolve() == args.snapshot.parent.resolve() or (args.output_dir / 'hotspots.json').resolve() == args.snapshot.resolve() or args.report.resolve() == args.snapshot.resolve():
        parser.error('Rebuild to a separate review directory; the original snapshot must remain intact.')
    now = collect.now_utc()
    today = args.today or now.astimezone(collect.BEIJING).date()
    generated_at = args.generated_at or collect.iso_utc(now)
    datetime.fromisoformat(generated_at.replace('Z', '+00:00'))
    raw = args.snapshot.read_bytes()
    snapshot = json.loads(raw)
    cities = json.loads(collect.CITIES_FILE.read_text(encoding='utf-8'))
    health = collect.load_json(args.snapshot.parent / 'health.json', {'api_version': 'v1', 'status': 'not_run'})
    previous = collect.load_json(args.snapshot.parent / 'activities.json', {})
    outputs, report = rebuild(snapshot, cities, health, today, generated_at, previous.get('data', []), previous)
    report['source_snapshot_sha256'] = hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest()
    report['source_checkout_sha256'] = hashlib.sha256(raw).hexdigest()
    for filename, payload in outputs.items():
        collect.write_json(args.output_dir / filename, payload)
    collect.write_json(args.report, report)
    print(json.dumps({key: value for key, value in report.items() if key != 'changes'}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
