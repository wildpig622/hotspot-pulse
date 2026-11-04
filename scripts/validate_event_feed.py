"""Validate the stable public consumer contract without accessing the network."""
import argparse
import json
import re
from datetime import date,datetime
from pathlib import Path

def validate(events,changes):
    errors=[];ids=set();members=set()
    meta=events.get('meta',{})
    if meta.get('api_version')!='v2' or meta.get('schema_version')!='2.0':errors.append('unsupported_contract_version')
    for row in events.get('data',[]):
        key=row.get('event_id','')
        if not re.fullmatch(r'hp_[0-9a-f]{16}',key) or key in ids:errors.append('invalid_or_duplicate_canonical_id')
        ids.add(key)
        if row.get('review_status') not in {'pending','verified','rejected'}:errors.append('invalid_review_status')
        if not row.get('city_name') or not row.get('event_name'):errors.append('missing_identity_fields')
        if not row.get('member_record_ids'):errors.append('missing_provenance_members')
        for member in row.get('member_record_ids',[]):
            if member in members:errors.append('source_record_in_multiple_events')
            members.add(member)
        if not row.get('sources') or any(not str(s.get('source_url','')).startswith('https://') for s in row.get('sources',[])):errors.append('missing_or_unsafe_sources')
        if not row.get('sessions'):errors.append('missing_occurrences')
        occurrences=set()
        for session in row.get('sessions',[]):
            occurrence=session.get('occurrence_id')
            if not occurrence or occurrence in occurrences:errors.append('duplicate_or_missing_occurrence_id')
            occurrences.add(occurrence)
            try:
                if date.fromisoformat(session['end_at']) < date.fromisoformat(session['start_at']):errors.append('reversed_dates')
            except (ValueError,KeyError,TypeError):errors.append('invalid_dates')
    if meta.get('event_count')!=len(events.get('data',[])):errors.append('event_count_mismatch')
    for field in ('generated_at','last_successful_collection_at','expires_at'):
        try:
            if datetime.fromisoformat(meta[field].replace('Z','+00:00')).tzinfo is None:errors.append('naive_timestamp')
        except (KeyError,ValueError,TypeError,AttributeError):errors.append('invalid_'+field)
    cursors=[r.get('cursor') for r in changes.get('data',[])]
    if any(type(c) is not int for c in cursors) or cursors!=sorted(set(cursors)):errors.append('invalid_change_cursors')
    if meta.get('cursor')!=changes.get('meta',{}).get('cursor'):errors.append('cursor_mismatch')
    return {'status':'FAIL' if errors else 'PASS','errors':errors,'event_count':len(ids),'source_record_count':len(members)}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--snapshot-dir',type=Path,default=Path(__file__).resolve().parents[1]/'site/api/v2');args=p.parse_args()
    r=validate(json.loads((args.snapshot_dir/'events.json').read_text(encoding='utf8')),json.loads((args.snapshot_dir/'changes.json').read_text(encoding='utf8')))
    print(json.dumps(r));raise SystemExit(r['status']!='PASS')
