"""Produce review-queue batches for an existing importer; never auto verify.

This module is intentionally pure. Credentials and destination URLs belong to
the consuming dashboard environment, never the public collector repository.
"""
import hashlib
import json
import re
from difflib import SequenceMatcher
from datetime import datetime,timezone
from urllib.parse import urlsplit,urlunsplit,quote


def build_import_batch(snapshot, *, cities=None, existing_events=None, bound_occurrences=None, limit=100, now=None):
    now=now or datetime.now(timezone.utc)
    meta=snapshot['meta']
    if meta.get('api_version')!='v2' or meta.get('schema_version')!='2.0':raise ValueError('Unsupported source contract')
    if meta.get('using_cached_data') or meta.get('is_stale') or now>datetime.fromisoformat(meta['expires_at'].replace('Z','+00:00')):raise ValueError('Fresh successful source snapshot required')
    existing_events=existing_events or []
    bound_occurrences=set(bound_occurrences or [])
    blocked={(e.get('event_name','').strip().lower(),e.get('city_name')) for e in existing_events if e.get('review_status')=='verified'}
    out=[];held=[]
    for row in snapshot['data']:
        key=row['event_id']
        if cities and row['city_name'] not in cities:continue
        if row.get('review_status')=='rejected' or row.get('availability') in {'expired','needs_date_review','not_recently_observed'}:continue
        if row.get('date_confidence') not in {'source_body','source_listing','structured_official'}:continue
        if (row['event_name'].strip().lower(),row['city_name']) in blocked:
            held.append({'event_id':key,'reason':'existing_verified_identity_requires_review'});continue
        normalized=lambda name:re.sub(r'[\W_]+|20\d{2}', '', name).lower()
        name=normalized(row['event_name'])
        possible=[]
        for existing in existing_events:
            if existing.get('city_name')!=row['city_name'] or existing.get('event_type')!=row['event_type']:continue
            other=normalized(existing.get('event_name',''))
            same_dates=any(s['start_at'] <= (existing.get('end_at') or existing.get('start_at') or '') and (existing.get('start_at') or '9999') <= s['end_at'] for s in row['sessions'])
            similar=min(len(name),len(other))>=5 and (name in other or other in name or SequenceMatcher(None,name,other).ratio()>=0.5)
            if similar and (same_dates or name==other):possible.append(existing['event_id'])
        if possible and not any(s['occurrence_id'] in bound_occurrences for s in row['sessions']):
            held.append({'event_id':key,'reason':'possible_existing_identity_requires_binding','existing_event_ids':possible});continue
        if row.get('date_changes') and not any(s['occurrence_id'] in bound_occurrences for s in row['sessions']):
            held.append({'event_id':key,'reason':'reschedule_binding_requires_review'});continue
        for session in row['sessions']:
            if len(out)>=limit:break
            occurrence=session['occurrence_id']
            identity=row['identity_url']+'&occurrence='+occurrence
            # A provider's shared city/listing URL must not become the importer's
            # strong URL identity, or unrelated events would collapse together.
            sources=[{'source_url':identity,'publisher':'Hotspot Pulse stable event record','source_type':'aggregator',
                      'verification_status':'unverified','evidence_summary':json.dumps({'canonical_id':key,'occurrence_id':occurrence,
                         'member_record_ids':row['member_record_ids'],'source_observed_at':row.get('last_seen_at'),
                         'source_first_seen_at':row.get('first_seen_at'),'upstream_review_status':row.get('review_status')},ensure_ascii=False)}]
            for source in row.get('sources',[]):
                # Preserve original links as evidence, not a shared identity key.
                original=source['source_url'];parts=urlsplit(original)
                # The importer indexes ALL sources, not only its first lookup URL.
                # Isolate their identity per occurrence while the link still opens
                # the original page. Keep its untouched URL in the evidence.
                url=urlunsplit(parts._replace(fragment=(parts.fragment+'&' if parts.fragment else '')+'hp_occurrence='+quote(occurrence)))
                sources.append({**{k:source.get(k) for k in ('publisher','source_type','source_published_at')},'source_url':url,
                                'verification_status':'unverified','evidence_summary':json.dumps({'original_source_url':original,'checked_at':source.get('checked_at') or source.get('observed_at'),'authority_note':source.get('authority_note','')},ensure_ascii=False)})
            out.append({'seed_record_id':occurrence,'event_name':row['event_name'],'city_name':row['city_name'],'event_type':row['event_type'],
                        'venue_name':row.get('venue_name'),'venue_location':None,'start_at':session['start_at'],'end_at':session['end_at'],
                        'date_precision':'day','event_status':row.get('event_status','unknown'),'review_status':'pending',
                        'series_key':key,'session_hint':None if occurrence in bound_occurrences else 'new_session','sources':sources})
    content=json.dumps(out,ensure_ascii=False,sort_keys=True).encode()
    batch={'batch':{'source_of_batch':'hotspot_pulse_v2','filename':'events-v2.json','file_sha256':hashlib.sha256(content).hexdigest(),
                    'submitted_by':'hotspot_pulse_adapter','notes':'Pending-only review batch; upstream timestamps remain evidence, not retroactive database knowable time.'},'events':out}
    return {'p_batch':batch,'report':{'events':len(out),'held':held,'limit':limit,'automatic_verified_promotions':0}}
