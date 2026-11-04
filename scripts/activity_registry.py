"""Build source-backed activity records separately from discovered news leads."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def _calendar_day(value: str) -> str:
    return date.fromisoformat(value).isoformat()


def historical_entries(groups: list[dict[str, Any]], leads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Import previously read body evidence without refreshing its checked_at."""
    by_id = {row['event_id']: row for row in leads}
    entries = []
    for group in groups:
        observations = [group.get('current_observation') or {}] + group.get('prior_source_observations', [])
        body = next((item for item in observations if 'body_read' in item.get('access_status', '') and item.get('url') and item.get('checked_at')), None)
        if not body or not group.get('start_date'):
            continue
        related = [value for value in group['event_ids'] if value in by_id]
        inferred_type = 'sports' if 'marathon' in group['group_id'] else 'exhibition' if any(term in group['group_id'] for term in ('auto', 'aviation', 'expo')) else 'other'
        entries.append({
            'registry_id': group['group_id'], 'event_name': group['event_name'],
            'city_name': group['city_name'],
            'event_type': by_id[related[0]].get('event_type', inferred_type) if related else inferred_type,
            'sessions': [{'start_at': group['start_date'], 'end_at': group.get('end_date') or group['start_date']}],
            'related_lead_ids': related, 'scope_note': '公告日期；不代表已实际举办或所有报道细节均已核验。',
            'source': {'url': body['url'], 'publisher': body.get('issuer') or body.get('source_type', '历史权威来源'),
                       'source_type': body.get('source_type', 'historical_primary_body'),
                       'checked_at': body['checked_at'], 'access_status': 'historical_body_read',
                       'published_at': None},
        })
    return entries


def build_activities(entries: list[dict[str, Any]], cities: list[dict[str, Any]],
                     leads: list[dict[str, Any]], previous: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    cities_by_name = {city['city_name']: city for city in cities}
    leads_by_id = {row['event_id']: row for row in leads}
    old = {row['event_id']: row for row in previous or []}
    seen = set()
    linked_identities: dict[str, str] = {}
    result = []
    for entry in entries:
        key = entry['registry_id']
        if key in seen:
            raise ValueError('Duplicate activity registry identity: ' + key)
        seen.add(key)
        city = cities_by_name.get(entry['city_name'])
        if city is None:
            raise ValueError('Registry city is outside the operating catalogue: ' + entry['city_name'])
        if entry.get('review_status', 'pending') != 'pending':
            raise ValueError('Registry cannot automatically verify records')
        source = entry['source']
        parsed_url = urlparse(source['url'])
        if parsed_url.scheme != 'https' or not parsed_url.hostname or parsed_url.username or parsed_url.password:
            raise ValueError('Evidence must use a public HTTPS source URL')
        if source.get('access_status') not in {'body_read', 'historical_body_read', 'official_listing_read'}:
            raise ValueError('An unread source cannot supply a calendar date')
        datetime.fromisoformat(source['checked_at'].replace('Z', '+00:00'))
        sessions = []
        for supplied in entry['sessions']:
            start = _calendar_day(supplied['start_at'])
            end = _calendar_day(supplied.get('end_at') or start)
            if end < start:
                raise ValueError('Reversed activity session')
            sessions.append({'start_at': start, 'end_at': end})
        if not sessions:
            raise ValueError('A structured activity needs at least one dated session')
        sessions.sort(key=lambda row: (row['start_at'], row['end_at']))
        event_id = 'act_' + hashlib.sha256(key.encode('utf-8')).hexdigest()[:12]
        related = entry.get('related_lead_ids', [])
        # Linking is explicit. Similar titles, same dates or same cities alone
        # never merge two events or silently attach an unknown news item.
        linked = [leads_by_id[value] for value in related if value in leads_by_id]
        for row in linked:
            if row.get('city_name') != city['city_name']:
                raise ValueError('Activity/news city conflict: ' + row['event_id'])
            if row['event_id'] in linked_identities:
                raise ValueError('A lead cannot silently belong to two activity identities: ' + row['event_id'])
            linked_identities[row['event_id']] = key
        sources = [{
            'source_url': source['url'], 'publisher': source['publisher'],
            'source_type': source['source_type'], 'source_published_at': source.get('published_at'),
            'source_published_date': source.get('published_date'),
            'observed_at': source['checked_at'], 'last_observed_at': source['checked_at'],
            'checked_at': source['checked_at'], 'access_status': source['access_status'],
            'verification_status': 'unverified',
        }]
        urls = {source['url']}
        for row in linked:
            for evidence in row.get('sources', []):
                if evidence.get('source_url') and evidence['source_url'] not in urls:
                    sources.append(copy.deepcopy(evidence)); urls.add(evidence['source_url'])
        activity = {
            'event_id': event_id, 'registry_id': key, 'record_kind': 'activity',
            'event_name': entry['event_name'], 'event_type': entry['event_type'],
            'city_name': city['city_name'], 'city_slug': city['city_slug'], 'city_match': 'text_confirmed',
            'venue_name': entry.get('venue_name'), 'start_at': sessions[0]['start_at'],
            'end_at': max(row['end_at'] for row in sessions), 'sessions': sessions,
            'date_precision': 'day', 'date_confidence': 'source_body', 'event_date_role': 'event',
            'content_kind': 'event_announcement', 'event_status': 'unknown', 'review_status': 'pending',
            'event_confirmation': 'unknown', 'scope_note': entry.get('scope_note', ''),
            'travel_windows': copy.deepcopy(entry.get('travel_windows', [])),
            'related_lead_ids': [row['event_id'] for row in linked],
            'first_seen_at': source['checked_at'], 'last_seen_at': source['checked_at'],
            'knowable_at': max([source['checked_at']] + ([source['published_at']] if source.get('published_at') else []), key=lambda value: datetime.fromisoformat(value.replace('Z', '+00:00'))),
            'source_count': len(sources), 'sources': sources,
            'last_evidence_check_at': source['checked_at'],
            'candidate_note': '来源正文日期；仍待核验，不代表真实住宿需求增量。',
        }
        for window in activity['travel_windows']:
            if _calendar_day(window['end_at']) < _calendar_day(window['start_at']):
                raise ValueError('Reversed travel window')
        # Source registry refreshes cannot overwrite a human-reviewed record.
        prior = old.get(event_id)
        if prior:
            activity['first_seen_at'] = prior.get('first_seen_at') or activity['first_seen_at']
            activity['event_status'] = prior.get('event_status', 'unknown')
            activity['event_confirmation'] = prior.get('event_confirmation', 'unknown')
        if prior and prior.get('review_status') == 'verified':
            activity = copy.deepcopy(prior)
        result.append(activity)
    present = {row['event_id'] for row in result}
    for row in old.values():
        if row['event_id'] not in present:
            retained = copy.deepcopy(row)
            if retained.get('review_status') != 'verified':
                retained['registry_presence'] = 'retained_not_refreshed'
            result.append(retained)
    return sorted(result, key=lambda row: (row['start_at'], row['city_name'], row['event_name']))


def activity_is_future(activity: dict[str, Any], today: date, horizon: int = 90) -> bool:
    if activity.get('event_status') in {'cancelled', 'postponed'}:
        return False
    upper = (today + timedelta(days=horizon)).isoformat()
    sessions = activity.get('sessions') or [{'start_at': activity['start_at'], 'end_at': activity.get('end_at') or activity['start_at']}]
    return any(row['end_at'] >= today.isoformat() and row['start_at'] <= upper for row in sessions)


def build_registry_payload(root: Path, leads: list[dict[str, Any]], cities: list[dict[str, Any]],
                           generated_at: str, today: date, previous: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    registry = json.loads((root / 'config/activity-registry.json').read_text(encoding='utf-8'))
    historical = json.loads((root / 'docs/activity-evidence-2026-10-30.json').read_text(encoding='utf-8'))
    entries = historical_entries(historical['groups'], leads) + [
        dict(row, source=registry['sources'][row['source_key']]) for row in registry['data']
    ]
    configured_names = {city['city_name'] for city in cities}
    entries = [row for row in entries if row['city_name'] in configured_names]
    rows = build_activities(entries, cities, leads, previous)
    return {'meta': {
        'api_version': 'v1', 'schema_version': '1.2', 'generated_at': generated_at,
        'coverage_status': 'partial', 'activity_count': len(rows),
        'future_activity_count': sum(activity_is_future(row, today) for row in rows),
        'pending_count': sum(row['review_status'] == 'pending' for row in rows),
        'verified_count': sum(row['review_status'] == 'verified' for row in rows),
        'data_note': '按明确活动身份登记，新闻在hotspots.json保留；来源检查时间逐条保留，未自动核验。',
    }, 'data': rows, 'backlog': registry.get('backlog', [])}


def build_coverage(cities: list[dict[str, Any]], topics: list[dict[str, Any]], leads: list[dict[str, Any]],
                   activities: list[dict[str, Any]], feed_results: list[dict[str, Any]], generated_at: str) -> dict[str, Any]:
    status = {(row['city_name'], row.get('topic')): row['status'] for row in feed_results}
    cells = []
    for city in cities:
        for topic in topics:
            selected = [row for row in activities if row['city_name'] == city['city_name'] and row['event_type'] == topic['key']]
            cells.append({'city_name': city['city_name'], 'topic': topic['key'], 'label': topic['label'],
                          'news_count': sum(row.get('city_name') == city['city_name'] and row.get('event_type') == topic['key'] for row in leads),
                          'activity_count': len(selected),
                          'last_evidence_check_at': max((row['last_evidence_check_at'] for row in selected), default=None),
                          'discovery_status': status.get((city['city_name'], topic['key']), 'not_run'),
                          'coverage_status': 'partial' if selected else 'not_assessed'})
    return {'meta': {'api_version': 'v1', 'generated_at': generated_at, 'coverage_status': 'partial',
                     'city_count': len(cities), 'topic_count': len(topics), 'expected_cells': len(cells),
                     'note': '零条或检索成功均不代表该城市没有活动。'}, 'data': cells}
