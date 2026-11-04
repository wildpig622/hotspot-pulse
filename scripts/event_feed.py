"""Versioned consumer feed: conservative identity, provenance and change cursors."""
from __future__ import annotations
import copy
import hashlib
import json
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

API_VERSION = 'v2'
SCHEMA_VERSION = '2.0'
BASE_URL = 'https://wildpig622.github.io/hotspot-pulse/api/v2/'


def normalized(value):
    return re.sub(r'[\W_]+', '', unicodedata.normalize('NFKC', str(value or '')).lower())


def ranges(row):
    return row.get('sessions') or [{'start_at': row.get('start_at'), 'end_at': row.get('end_at') or row.get('start_at')}]


def signature(row):
    fields = ('event_name', 'city_name', 'event_type', 'venue_name', 'sessions', 'event_status',
              'availability', 'review_status', 'date_review_required', 'member_record_ids')
    value={k:row.get(k) for k in fields}
    value['source_urls']=sorted(s.get('source_url','') for s in row.get('sources',[]))
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def freshness(last_success, now, hours=18):
    try:
        stamp = datetime.fromisoformat(last_success.replace('Z', '+00:00'))
        expires = stamp + timedelta(hours=hours)
        return {'last_successful_collection_at': last_success, 'expires_at': expires.isoformat().replace('+00:00', 'Z'),
                'is_stale': now > expires, 'age_hours': round(max(0, (now-stamp).total_seconds()/3600), 2)}
    except (AttributeError, ValueError, TypeError):
        return {'last_successful_collection_at': None, 'expires_at': None, 'is_stale': True, 'age_hours': None}


def build_feed(calendar, news_meta, health, now, previous=None, links=None):
    previous = previous or {}
    state = previous.get('state', {})
    old = {r['event_id']: r for r in previous.get('events', {}).get('data', [])}
    rows = [copy.deepcopy(r) for key in ('data', 'source_candidates', 'official_candidates', 'discovery_candidates') for r in calendar.get(key, [])]
    by_id = {r['event_id']: r for r in rows}
    parent = {key: key for key in by_id}

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def join(a, b):
        if a not in parent or b not in parent:
            return
        if by_id[a].get('city_name') != by_id[b].get('city_name') or by_id[a].get('event_type') != by_id[b].get('event_type'):
            raise ValueError('Cross-city/type identity link rejected')
        aa, bb = find(a), find(b)
        parent[max(aa, bb)] = min(aa, bb)

    identities = {}
    for row in rows:
        key = row['event_id']
        for related in row.get('related_lead_ids', []):
            join(key, related)
        # A shared listing URL is deliberately NEVER an event identity.
        external = row.get('source_record_id')
        if external:
            identity = (row['city_name'], 'external', external)
            if identity in identities: join(key, identities[identity])
            identities[identity] = key
        venue = normalized(row.get('venue_name'))
        name = normalized(row.get('event_name'))
        if venue and name:
            exact = (row['city_name'], row.get('event_type'), name, venue,
                     tuple((s['start_at'], s.get('end_at') or s['start_at']) for s in ranges(row)))
            if exact in identities: join(key, identities[exact])
            identities[exact] = key
    for group in links or []:
        ids = [key for key in group['member_ids'] if key in parent]
        for key in ids[1:]: join(ids[0], key)

    groups = {}
    for key in parent: groups.setdefault(find(key), []).append(by_id[key])
    membership = dict(state.get('membership', {}))
    aliases = dict(state.get('aliases', {}))
    sequences = dict(state.get('occurrence_sequences', {}))
    def resolved(key):
        seen=set()
        while key in aliases and key not in seen:seen.add(key);key=aliases[key]
        return key
    events = []
    today = now.astimezone(timezone(timedelta(hours=8))).date().isoformat()
    priority = {'source_body': 0, 'source_listing': 1, 'structured_official': 0, 'explicit_year': 2, 'inferred_year': 3}
    for members in groups.values():
        members.sort(key=lambda r: (priority.get(r.get('date_confidence'), 4), r['event_id']))
        prior_ids = {resolved(membership[r['event_id']]) for r in members if r['event_id'] in membership}
        canonical = min(prior_ids, key=lambda k: (old.get(k, {}).get('first_seen_at') or '', k)) if prior_ids else 'hp_' + hashlib.sha256(members[0]['event_id'].encode()).hexdigest()[:16]
        for key in prior_ids - {canonical}: aliases[key] = canonical
        for row in members: membership[row['event_id']] = canonical
        primary = members[0]
        event = copy.deepcopy(primary)
        event.update(event_id=canonical, canonical_id=canonical, record_id=primary['event_id'],
                     identity_url=BASE_URL+'events.json#event_id='+canonical,
                     member_record_ids=sorted(r['event_id'] for r in members),
                     evidence_levels=sorted({r.get('evidence_level') or ('source_body' if r.get('date_confidence')=='source_body' else 'title_or_rss_summary') for r in members}))
        event['sessions'] = copy.deepcopy(ranges(primary))
        prior_sessions=old.get(canonical,{}).get('sessions',[])
        sequence=sequences.get(canonical,0)
        for session in event['sessions']:
            match=next((s for s in prior_sessions if s['start_at']==session['start_at'] and s.get('end_at')==session.get('end_at')),None)
            if match:session['occurrence_id']=match['occurrence_id']
            elif len(prior_sessions)==len(event['sessions'])==1:session['occurrence_id']=prior_sessions[0]['occurrence_id']
            else:
                sequence+=1;session['occurrence_id']=canonical+'_s'+str(sequence)
        sequences[canonical]=sequence
        expected = {(s['start_at'], s.get('end_at') or s['start_at']) for s in ranges(primary)}
        def supported(row):
            return all(any(a <= s['start_at'] and (s.get('end_at') or s['start_at']) <= b for a,b in expected) for s in ranges(row))
        conflict = any(not supported(r) or r.get('date_review_required') for r in members)
        event['date_review_required'] = bool(conflict)
        explicit_status = [r for r in members if r.get('event_status') in {'cancelled','postponed'}]
        if explicit_status:
            latest = max(explicit_status, key=lambda r:r.get('last_evidence_check_at') or r.get('last_seen_at') or '')
            event['event_status'] = latest['event_status']
        # Canonical grouping is not human fact verification.
        event['review_status'] = old.get(canonical, {}).get('review_status', 'pending')
        if all(r.get('review_status') == 'rejected' for r in members): event['review_status']='rejected'
        sources = {}
        for row in members:
            for source in row.get('sources', []):
                url = source.get('source_url')
                if url and (url not in sources or (source.get('checked_at') or '') > (sources[url].get('checked_at') or '')):
                    sources[url] = copy.deepcopy(source)
        event['sources'] = list(sources.values())
        event['source_count'] = len(sources)
        event['first_seen_at'] = old.get(canonical, {}).get('first_seen_at') or min((r.get('first_seen_at') or now.isoformat() for r in members))
        event['last_seen_at'] = max(r.get('last_seen_at') or '' for r in members)
        event['availability'] = ('rejected' if event['review_status']=='rejected' else event.get('event_status') if event.get('event_status') in {'cancelled','postponed'}
                                 else 'needs_date_review' if conflict else 'expired' if all((s.get('end_at') or s['start_at']) < today for s in ranges(event))
                                 else 'not_recently_observed' if all(r.get('source_presence') == 'retained_not_refreshed' for r in members) else 'candidate')
        event['revision'] = old.get(canonical, {}).get('revision', 0) + int(canonical not in old or signature(event) != signature(old[canonical]))
        events.append(event)
    # Keep tombstones for consumers when a source record falls out of retention.
    present = {e['event_id'] for e in events}
    for key,row in old.items():
        if key not in present and key not in aliases:
            retained=copy.deepcopy(row)
            retained['availability']='expired' if all((s.get('end_at') or s['start_at']) < today for s in ranges(row)) else 'not_recently_observed'
            retained['revision']=row.get('revision',1)+int(signature(retained)!=signature(row))
            events.append(retained)
    events.sort(key=lambda r:(r.get('start_at') or '9999',r['city_name'],r['event_id']))
    previous_changes=previous.get('changes', {})
    changes=list(previous_changes.get('data', [])); cursor=int(previous_changes.get('meta',{}).get('cursor',0))
    for row in events:
        before=old.get(row['event_id'])
        if before is None or signature(before)!=signature(row):
            cursor+=1
            changes.append({'cursor':cursor,'event_id':row['event_id'],'revision':row['revision'],
                            'change_type':'created' if before is None else 'updated','observed_at':now.isoformat().replace('+00:00','Z'),
                            'changed_fields':[k for k in ('event_name','city_name','venue_name','sessions','event_status','availability','member_record_ids') if (before or {}).get(k)!=row.get(k)]})
    for alias,target in aliases.items():
        if state.get('aliases',{}).get(alias)!=target:
            cursor+=1;changes.append({'cursor':cursor,'event_id':alias,'change_type':'merged','canonical_id':target,'observed_at':now.isoformat().replace('+00:00','Z')})
    changes=changes[-10000:]
    last_success=health.get('last_successful_collection_at') or news_meta.get('last_collection_at')
    current=freshness(last_success,now)
    meta={'api_version':API_VERSION,'schema_version':SCHEMA_VERSION,'generated_at':now.isoformat().replace('+00:00','Z'),
          'last_collection_at':news_meta.get('last_collection_at'),'collection_status':health.get('status','unknown'),
          'using_cached_data':health.get('status') in {'failed','degraded'} and health.get('data_updated') is False,
          'event_count':len(events),'source_record_count':len(rows),'linked_record_reduction':len(rows)-len(groups),
          'cursor':cursor,'coverage_status':'partial','schedule_local':['08:00','16:00'],'timezone':'Asia/Shanghai',**current}
    return {'events':{'meta':meta,'data':events},
            'changes':{'meta':{'api_version':API_VERSION,'schema_version':SCHEMA_VERSION,'cursor':cursor,'cursor_floor':changes[0]['cursor']-1 if changes else cursor},'data':changes},
            'state':{'membership':membership,'aliases':aliases,'occurrence_sequences':sequences}}


def build_files(api, now=None):
    now=now or datetime.now(timezone.utc).replace(microsecond=0)
    load=lambda p,default:json.loads(p.read_text(encoding='utf8')) if p.exists() else default
    v2=api.parent/'v2'
    prior={key:load(v2/(key+'.json'),{}) for key in ('events','changes','state')}
    linkfile=Path(__file__).resolve().parents[1]/'config/event-links.json'
    links=load(linkfile,{'groups':[]})['groups']
    result=build_feed(load(api/'activities.json',{}),load(api/'hotspots.json',{})['meta'],load(api/'health.json',{}),now,prior,links)
    v2.mkdir(parents=True,exist_ok=True)
    for key,value in result.items():(v2/(key+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--snapshot-dir',type=Path,default=Path(__file__).resolve().parents[1]/'site/api/v1')
    args=parser.parse_args();result=build_files(args.snapshot_dir)
    print(json.dumps(result['events']['meta'],ensure_ascii=False))
