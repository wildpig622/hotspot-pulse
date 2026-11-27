"""Small, persistent candidate feeds. No network, database, or verification writes.

v1/v2 remain authoritative for their own contracts. This additive sidecar uses
their existing membership/aliases, and stores every dated or undated observation.
"""
import argparse
import copy
import hashlib
import html
import json
import os
import re
import tempfile
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
STATES = {'observed', 'announced', 'ticket_on_sale', 'sold_out', 'extra_show', 'postponed', 'cancelled'}
FIELDS = {'event_id', 'event_name', 'event_type', 'city_name', 'scope_level', 'venue_name',
          'start_at', 'end_at', 'sessions', 'source_url', 'short_evidence', 'date_review_required',
          'source_published_at', 'observed_at', 'observation_type', 'signal_kind', 'discovery_lane'}


def read(path, fallback):
    return json.loads(path.read_text(encoding='utf8')) if path.exists() else copy.deepcopy(fallback)


def stamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timezone_required')
    return parsed.astimezone(timezone.utc)


def validate(row):
    if set(row) - FIELDS:
        raise ValueError('unknown_or_protected_import_fields')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', row.get('event_id', '')):
        raise ValueError('stable_event_id_required')
    if not row.get('event_name') or len(row['event_name']) > 200:
        raise ValueError('short_event_name_required')
    stamp(row['observed_at'])
    url = urlsplit(row.get('source_url', ''))
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.fragment:
        raise ValueError('public_https_source_required')
    # Reject contacts rather than silently altering quoted evidence.
    text = json.dumps(row, ensure_ascii=False)
    text = unicodedata.normalize('NFKC', html.unescape(re.sub(r'<[^>]*>', '', text)))
    if re.search(r'[\w.+-]+[@＠][\w.-]+\.[A-Za-z]{2,}|(?<!\d)1[3-9]\d{9}(?!\d)|(?<!\d)0\d{2,3}[- ]\d{7,8}(?!\d)', text):
        raise ValueError('contact_details_not_allowed')
    quotes = row.get('short_evidence', [])
    if not isinstance(quotes, list) or not 1 <= len(quotes) <= 3 or any(not isinstance(q, str) or not q or len(q) > 160 for q in quotes):
        raise ValueError('short_literal_evidence_required')
    if row.get('observation_type', 'observed') not in STATES:
        raise ValueError('unsupported_observation_type')
    if row.get('signal_kind', 'scheduled' if row.get('start_at') else 'unscheduled') not in {'scheduled', 'unscheduled', 'status_change', 'market_signal'}:
        raise ValueError('unsupported_signal_kind')
    if row.get('scope_level') in {'national', 'province'} and row.get('city_name'):
        raise ValueError('national_or_province_scope_is_not_local_test_site')
    if row.get('end_at') and not row.get('start_at'):
        raise ValueError('start_required')
    if row.get('start_at'):
        a = date.fromisoformat(row['start_at'])
        b = date.fromisoformat(row.get('end_at') or row['start_at'])
        if b < a:
            raise ValueError('reversed_dates')
    for session in row.get('sessions', []):
        # Explicit dates only; an interval is never expanded into daily shows.
        if isinstance(session, str):
            date.fromisoformat(session)
        elif isinstance(session, dict) and set(session) <= {'start_at', 'end_at'} and session.get('start_at'):
            a = date.fromisoformat(session['start_at'])
            b = date.fromisoformat(session.get('end_at') or session['start_at'])
            if b < a:
                raise ValueError('reversed_session')
        else:
            raise ValueError('explicit_session_dates_required')
    if row.get('source_published_at'):
        date.fromisoformat(row['source_published_at'][:10])
    return copy.deepcopy(row)


def relevance(row):
    if row.get('review_status') == 'rejected' or row.get('event_status') in {'cancelled', 'postponed'}:
        priority = 'exclude'
    elif re.search('常规|每周|脱口秀|驻场', row.get('event_name', '')):
        priority = 'routine_local'
    elif row.get('event_type') == 'holiday':
        priority = 'origin_market_review'
    elif not row.get('city_name'):
        priority = 'scope_review'
    elif row.get('event_type') in {'exam', 'conference', 'exhibition', 'sports'} or re.search('体育馆|体育场|大剧院', row.get('venue_name', '')):
        priority = 'priority_review'
    else:
        priority = 'unknown'
    return {'review_priority': priority, 'audience_scale': None, 'lodging_increment_grade': 'unknown', 'revenue_impact': None}


def merge(previous, rows, now, v2_state=None, v2_events=None):
    state = copy.deepcopy(previous or {'schema_version': 'business-state-1', 'events': {}, 'observations': []})
    membership = (v2_state or {}).get('membership', {})
    aliases = (v2_state or {}).get('aliases', {})
    def canonical(key):
        key = membership.get(key, key)
        visited = set()
        while key in aliases:
            if key in visited:
                raise ValueError('identity_alias_cycle')
            visited.add(key)
            key = aliases[key]
        return key
    # Rebind retained records too, when v2 later learns their canonical identity.
    rebound = {}
    for key, event in state['events'].items():
        target = canonical(key)
        if target in rebound and rebound[target].get('city_name') != event.get('city_name'):
            raise ValueError('identity_city_conflict')
        if target not in rebound or (rebound[target].get('review_status') not in {'verified', 'rejected'} and
                                     (event.get('review_status') in {'verified', 'rejected'} or stamp(event['last_observed_at']) > stamp(rebound[target]['last_observed_at']))):
            rebound[target] = event
        rebound[target]['event_id'] = target
    state['events'] = rebound
    for observation in state['observations']:
        observation['event_id'] = canonical(observation['event_id'])
    humans = {r['event_id']: r for r in (v2_events or {}).get('data', []) if r.get('review_status') in {'verified', 'rejected'}}
    def apply_human(event, human):
        for field in ('review_status', 'event_name', 'event_type', 'city_name', 'scope_level', 'venue_name', 'sessions', 'start_at', 'end_at', 'event_status'):
            if field in human:
                event[field] = copy.deepcopy(human[field])
        if human['review_status'] == 'verified':
            event['date_review_required'] = human.get('date_review_required', False)
    for key, event in state['events'].items():
        if key in humans:
            apply_human(event, humans[key])
    known = {o['observation_id'] for o in state['observations']}
    for raw in rows:
        row = validate(raw)
        if stamp(row['observed_at']) > now + timedelta(minutes=5):
            raise ValueError('future_observation_time')
        key = canonical(row['event_id'])
        digest = hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
        if digest in known:
            continue
        is_new = key not in state['events']
        event = state['events'].setdefault(key, {'event_id': key, 'review_status': 'pending', 'first_seen_at': row['observed_at']})
        if key in humans:
            apply_human(event, humans[key])
        if event.get('city_name') and row.get('city_name') and event['city_name'] != row['city_name']:
            raise ValueError('identity_city_conflict')
        observation = dict(row, event_id=key, record_id=row['event_id'], observation_id=digest,
                           change_kind='new_record' if is_new else 'evidence_recheck' if row.get('observation_type', 'observed') == 'observed' else 'status_change')
        state['observations'].append(observation)
        known.add(digest)
        # Human review is carried independently; newer evidence cannot erase it.
        if not event.get('last_observed_at') or stamp(row['observed_at']) >= stamp(event['last_observed_at']):
            if event.get('review_status') not in {'verified', 'rejected'}:
                conflict = bool(event.get('start_at') and row.get('start_at') and
                                (event['start_at'], event.get('end_at') or event['start_at']) !=
                                (row['start_at'], row.get('end_at') or row['start_at']))
                for field in ('event_name', 'event_type', 'city_name', 'scope_level', 'venue_name', 'start_at', 'end_at', 'sessions', 'date_review_required', 'signal_kind'):
                    if row.get(field) is not None and not (conflict and field in {'start_at', 'end_at', 'sessions'}):
                        event[field] = copy.deepcopy(row[field])
                if conflict:
                    event['date_review_required'] = True
                if row.get('observation_type') in {'cancelled', 'postponed'}:
                    event['event_status'] = row['observation_type']
            event['last_observed_at'] = row['observed_at']
            event['source_url'] = row['source_url']
            event['short_evidence'] = row['short_evidence']
            if row.get('observation_type', 'observed') != 'observed' or not event.get('observation_type'):
                event['observation_type'] = row.get('observation_type', 'observed')
        if stamp(row['observed_at']) < stamp(event['first_seen_at']):
            event['first_seen_at'] = row['observed_at']
    # v2 decisions are authoritative, including decisions made since last refresh.
    for key, human in humans.items():
        if key in state['events']:
            apply_human(state['events'][key], human)
    return state


def build(api, now=None, imports=None, collection_ok=True, bootstrap=False, seed_path=None):
    """api is the v1 directory. Last-good state is read before any output changes."""
    api = Path(api)
    now = now or datetime.now(timezone.utc)
    output = api.parent / 'business'
    state_file = output / 'state.json'
    previous = read(state_file, {})
    if state_file.exists() and (previous.get('schema_version') != 'business-state-1' or not isinstance(previous.get('events'), dict) or not isinstance(previous.get('observations'), list)):
        raise ValueError('invalid_existing_business_state_keep_last_good')
    rows = list(imports or [])
    seeded = False
    if bootstrap and not state_file.exists():
        batch = read(Path(seed_path) if seed_path else ROOT / 'config/business-seed.json', {})
        if batch.get('schema_version') != 'agent-import-1' or not batch.get('data'):
            raise ValueError('reviewed_business_seed_required')
        rows = batch['data'] + rows
        seeded = True
    skipped = 0
    # Only official date assertions enter automatically; general news remains v1.
    if collection_ok:
        for row in read(api / 'activities.json', {}).get('official_candidates', []):
            quote = row.get('date_evidence') or row.get('short_evidence') or [row.get('evidence_excerpt', '')]
            if isinstance(quote, str):
                quote = [quote]
            quote = [q if isinstance(q, str) else q.get('quote', '') for q in quote]
            draft = {k: row[k] for k in FIELDS if k in row}
            draft.update(source_url=row.get('source_url') or row.get('event_detail_url') or next((s.get('source_url') for s in row.get('sources', []) if s.get('source_url')), None),
                         short_evidence=[q[:160] for q in quote if q][:3],
                         observed_at=row.get('last_seen_at') or row.get('checked_at') or row.get('first_seen_at'),
                         observation_type=row.get('event_status') if row.get('event_status') in {'cancelled', 'postponed'} else 'observed')
            try:
                rows.append(validate(draft))
            except (ValueError, TypeError, KeyError):
                # Unsupported source shape is a visible coverage gap, not guessed.
                skipped += 1
                continue
    state = merge(previous, rows, now, read(api.parent / 'v2/state.json', {}), read(api.parent / 'v2/events.json', {}))
    all_rows = []
    for row in state['events'].values():
        row['operating_relevance_candidate'] = relevance(row)
        row['source_presence'] = 'retained_until_explicit_change'
        all_rows.append(row)
    today = now.astimezone(timezone(timedelta(hours=8))).date().isoformat()
    horizon = (date.fromisoformat(today) + timedelta(days=365)).isoformat()
    active = [r for r in all_rows if r.get('review_status') != 'rejected' and r.get('event_status') not in {'cancelled', 'postponed'}]
    dated = [r for r in active if r.get('start_at') and (r.get('end_at') or r['start_at']) >= today and r['start_at'] <= horizon and not r.get('date_review_required')]
    undated = [r for r in active if not r.get('start_at') or r.get('date_review_required')]
    dated.sort(key=lambda r: (r['operating_relevance_candidate']['review_priority'] == 'routine_local', r['start_at'], r['event_id']))
    meta = {'schema_version': 'business-1', 'generated_at': now.isoformat(), 'default_days': 90, 'horizon_days': 365,
            'last_observed_at': max((r['last_observed_at'] for r in all_rows), default=None),
            'collection_ok': collection_ok, 'search_mode': 'manual_agent_import',
            'official_rows_not_adapted': skipped,
            'bootstrap_applied_this_build': seeded,
            'gaps': ['搜索尚非无人值守服务；需人工触发检索并导入', '三城和类别覆盖不完整；全国考试不代表当地考点', '日期冲突不进入日历；候选未经人工核验']}
    changes = sorted((o for o in state['observations'] if o.get('change_kind') != 'evidence_recheck'), key=lambda o: stamp(o['observed_at']), reverse=True)[:200]
    payloads = {'state': state, 'focus': {'meta': meta, 'data': [r for r in dated if r['operating_relevance_candidate']['review_priority'] in {'priority_review', 'origin_market_review'}]},
                'calendar': {'meta': meta, 'data': dated}, 'intelligence': {'meta': meta, 'data': undated},
                'changes': {'meta': meta, 'data': changes}, 'status': {'meta': meta, 'event_count': len(all_rows), 'observation_count': len(state['observations'])}}
    output.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf8', dir=output, delete=False) as temp:
            json.dump(payload, temp, ensure_ascii=False, indent=2)
            temp.write('\n')
        os.replace(temp.name, output / (name + '.json'))
    return payloads


def main():
    parser = argparse.ArgumentParser(description='Import manually gathered, minimal candidate intelligence into an isolated API copy.')
    parser.add_argument('--snapshot-dir', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    args = parser.parse_args()
    if args.snapshot_dir.resolve().is_relative_to(ROOT / 'site'):
        parser.error('Use an isolated review copy; production snapshots cannot be imported here.')
    batch = read(args.input, {})
    if batch.get('schema_version') != 'agent-import-1' or not isinstance(batch.get('data'), list):
        parser.error('agent-import-1 envelope required')
    result = build(args.snapshot_dir, imports=batch['data'], bootstrap=True)
    print(json.dumps(result['status'], ensure_ascii=False))


if __name__ == '__main__':
    main()
