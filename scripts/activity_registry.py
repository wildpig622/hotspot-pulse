"""Build source-backed activity records separately from discovered news leads."""
from __future__ import annotations

import copy
import hashlib
import json
import re
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
        evidence_sources = [source] + entry.get('additional_sources', [])
        for evidence in evidence_sources:
            parsed_url = urlparse(evidence['url'])
            if parsed_url.scheme != 'https' or not parsed_url.hostname or parsed_url.username or parsed_url.password:
                raise ValueError('Evidence must use a public HTTPS source URL')
            if evidence.get('access_status') not in {'body_read', 'historical_body_read', 'official_listing_read'}:
                raise ValueError('An unread source cannot supply a calendar date')
            checked = datetime.fromisoformat(evidence['checked_at'].replace('Z', '+00:00'))
            if checked.tzinfo is None:
                raise ValueError('Evidence check time needs a timezone')
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
            'source_url': evidence['url'], 'publisher': evidence['publisher'],
            'source_type': evidence['source_type'], 'source_published_at': evidence.get('published_at'),
            'source_published_date': evidence.get('published_date'),
            'source_published_display': evidence.get('published_display'),
            'observed_at': evidence['checked_at'], 'last_observed_at': evidence['checked_at'],
            'checked_at': evidence['checked_at'], 'access_status': evidence['access_status'],
            'authority_note': evidence.get('authority_note', ''),
            'verification_status': 'unverified',
        } for evidence in evidence_sources]
        urls = {evidence['url'] for evidence in evidence_sources}
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
            'last_evidence_check_at': max((item['checked_at'] for item in evidence_sources), key=lambda value: datetime.fromisoformat(value.replace('Z', '+00:00'))),
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


INTERNAL_MEETING = re.compile(r'股东大会|董事会会议|业绩说明会|职工代表大会|军训动员|迎新大会')


def build_discovery_candidates(leads: list[dict[str, Any]], activities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project dated news into the calendar without asserting event identity or body evidence.

    Keep dates outside today's window too: the client applies its current date.
    Only explicit links remove a lead; similar titles never silently merge it.
    """
    try:
        from . import collect
    except ImportError:
        import collect
    linked = {key for row in activities for key in row.get('related_lead_ids', [])}
    result = []
    for lead in leads:
        if (lead.get('event_id') in linked or lead.get('review_status') != 'pending'
                or lead.get('city_match') != 'text_confirmed' or lead.get('event_date_role') != 'event'
                or lead.get('date_precision') != 'day' or INTERNAL_MEETING.search(lead.get('event_name', ''))
                or not collect.is_upcoming_event(lead, date.min)):
            continue
        row = copy.deepcopy(lead)
        row.update(record_kind='discovery_candidate', evidence_level='title_or_rss_summary',
                   candidate_note='新闻候选：日期来自标题或摘要，尚未核对正文，可能与其他记录重复。')
        result.append(row)
    return sorted(result, key=lambda row: (row['start_at'], row['city_name'], row['event_id']))


def build_registry_payload(root: Path, leads: list[dict[str, Any]], cities: list[dict[str, Any]],
                           generated_at: str, today: date, previous: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    registry = json.loads((root / 'config/activity-registry.json').read_text(encoding='utf-8'))
    historical = json.loads((root / 'docs/activity-evidence-2026-10-30.json').read_text(encoding='utf-8'))
    entries = historical_entries(historical['groups'], leads) + [
        dict(row, source=registry['sources'][row['source_key']],
             additional_sources=[registry['sources'][key] for key in row.get('additional_source_keys', [])]) for row in registry['data']
    ]
    configured_names = {city['city_name'] for city in cities}
    entries = [row for row in entries if row['city_name'] in configured_names]
    rows = build_activities(entries, cities, leads, previous)
    candidates = build_discovery_candidates(leads, rows)
    signals = []
    for signal in registry.get('source_market_signals', []):
        if not any(name in configured_names for name in signal['impact_destination_cities']):
            continue
        signal_city = {'city_name': signal['city_name'], 'city_slug': signal['source_city_slug']}
        built = build_activities([dict(signal, source=registry['sources'][signal['source_key']])], [signal_city], [])[0]
        built.update(event_id='sig_' + built['event_id'][4:], record_kind='source_market_signal',
                     impact_destination_cities=signal['impact_destination_cities'])
        signals.append(built)
    return {'meta': {
        'api_version': 'v1', 'schema_version': '1.3', 'generated_at': generated_at,
        'discovery_candidate_count': len(candidates),
        'future_discovery_candidate_count': sum(activity_is_future(row, today) for row in candidates),
        'coverage_status': 'partial', 'activity_count': len(rows), 'source_market_signal_count': len(signals),
        'future_activity_count': sum(activity_is_future(row, today) for row in rows),
        'pending_count': sum(row['review_status'] == 'pending' for row in rows),
        'verified_count': sum(row['review_status'] == 'verified' for row in rows),
        'data_note': '按明确活动身份登记，新闻在hotspots.json保留；来源检查时间逐条保留，未自动核验。',
    }, 'data': rows, 'discovery_candidates': candidates, 'backlog': registry.get('backlog', []),
        'backlog_resolutions': registry.get('backlog_resolutions', []), 'source_market_signals': signals}


def build_coverage(cities: list[dict[str, Any]], topics: list[dict[str, Any]], leads: list[dict[str, Any]],
                   activities: list[dict[str, Any]], feed_results: list[dict[str, Any]], generated_at: str,
                   candidates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    status = {(row['city_name'], row.get('topic')): row['status'] for row in feed_results}
    cells = []
    for city in cities:
        for topic in topics:
            selected = [row for row in activities if row['city_name'] == city['city_name'] and row['event_type'] == topic['key']]
            cells.append({'city_name': city['city_name'], 'topic': topic['key'], 'label': topic['label'],
                          'news_count': sum(row.get('city_name') == city['city_name'] and row.get('event_type') == topic['key'] for row in leads),
                          'activity_count': len(selected),
                          'dated_news_candidate_count': sum(row['city_name'] == city['city_name'] and row['event_type'] == topic['key'] for row in candidates or []),
                          'last_evidence_check_at': max((row['last_evidence_check_at'] for row in selected), default=None),
                          'discovery_status': status.get((city['city_name'], topic['key']), 'not_run'),
                          'coverage_status': 'partial' if selected else 'not_assessed'})
    return {'meta': {'api_version': 'v1', 'generated_at': generated_at, 'coverage_status': 'partial',
                     'city_count': len(cities), 'topic_count': len(topics), 'expected_cells': len(cells),
                     'note': '零条或检索成功均不代表该城市没有活动。'}, 'data': cells}
