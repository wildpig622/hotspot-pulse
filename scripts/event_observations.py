"""Isolated observation ledger, using existing v2 membership without changing v2.

An observation is not a verified event. Unknown dates and market signals remain
in this sidecar; only dated, city-established records can be offered to v2.
"""
from __future__ import annotations
import copy
import hashlib
import json
from datetime import date, datetime

KINDS={'scheduled','unscheduled','status_change','market_signal'}
STATES={'observed','announced','ticket_on_sale','sold_out','extra_show','cancelled','postponed'}


def evidence_gate(draft, body):
    """Validate LLM/date drafts against literal evidence, never infer missing facts.

    Passing this gate means a proposal has a quote, not that it is correct.
    The extractor must supply literal ISO/Chinese date tokens for both bounds;
    a separate contextual year quote is required for yearless day tokens.
    """
    quote=draft.get('quote','')
    if not quote or quote not in body: return False,'quote_not_in_body'
    if draft.get('date_role')!='event': return False,'not_event_date'
    for field in ('start_at','end_at'):
        value=draft.get(field) or draft.get('start_at')
        try: day=date.fromisoformat(value)
        except (TypeError,ValueError): return False,'invalid_date'
        token=draft.get(field+'_token','')
        if not token or token not in quote: return False,'date_token_missing'
        import re
        patterns=[rf'{day.year}[-/.]0?{day.month}[-/.]0?{day.day}(?!\d)',rf'(?:{day.year}年)?0?{day.month}月0?{day.day}日']
        abbreviated_end=(field=='end_at' and token==str(day.day)+'日'
                         and draft.get('start_at','')[:7]==value[:7]
                         and re.search(re.escape(draft.get('start_at_token',''))+r'[至—–-]'+re.escape(token),quote))
        if not abbreviated_end and not any(re.fullmatch(p,token) for p in patterns): return False,'date_token_mismatch'
        if not re.search(str(day.year),token):
            year_quote=draft.get('year_quote','')
            if not year_quote or year_quote not in body or str(day.year) not in year_quote: return False,'year_evidence_missing'
    if draft.get('end_at') and draft['end_at']<draft['start_at']: return False,'reversed_range'
    return True,'proposal_pending_review'


def preserve_record_ids(records,previous_rows):
    """Bind only unique article+city+exact-session matches, never shared indexes.

    Ambiguous or rescheduled articles require an explicit reviewer identity link.
    Prior rows are identity state, never discovery seeds or expected results.
    """
    def key(row):
        url=row.get('source_url') or row.get('event_detail_url')
        if not url or not row.get('start_at'):return None
        return url,row.get('city_name'),row['start_at'],row.get('end_at') or row['start_at']
    old={};new={}
    for r in previous_rows:
        if key(r):old.setdefault(key(r),[]).append(r)
    for r in records:
        if key(r):new.setdefault(key(r),[]).append(r)
    rows=copy.deepcopy(records);links=[]
    for r in rows:
        matches=old.get(key(r),[])
        if len(matches)==1 and len(new.get(key(r),[]))==1:
            prior=matches[0];links.append({'discovered_record_id':r['event_id'],'retained_record_id':prior['event_id'],'reason':'unique_article_city_exact_session'})
            r['event_id']=prior['event_id']
    return rows,links


def build_ledger(records, previous=None, v2=None):
    ledger=copy.deepcopy(previous or {'schema_version':'observations-1','events':{},'observations':[]})
    membership=dict((v2 or {}).get('state',{}).get('membership',{}))
    human_reviews={e['event_id']:e.get('review_status','pending') for e in (v2 or {}).get('events',{}).get('data',[])}
    aliases=(v2 or {}).get('state',{}).get('aliases',{})
    # Existing canonical/member relationships are the authority for identity.
    for event in (v2 or {}).get('events',{}).get('data',[]):
        for member in event.get('member_record_ids',[]):membership={**membership,member:event['event_id']}
    known={o['observation_id'] for o in ledger['observations']}
    for row in records:
        record_id=row.get('event_id')
        if not record_id: raise ValueError('existing_record_id_required')
        canonical=membership.get(record_id,record_id)
        visited=set()
        while canonical in aliases:
            if canonical in visited:raise ValueError('identity_alias_cycle')
            visited.add(canonical);canonical=aliases[canonical]
        stamp=row.get('last_seen_at') or row.get('first_seen_at')
        if not stamp: raise ValueError('observed_at_required')
        parsed_stamp=datetime.fromisoformat(stamp.replace('Z','+00:00'))
        if parsed_stamp.tzinfo is None: raise ValueError('timezone_required')
        state=row.get('observation_type') or (row.get('event_status') if row.get('event_status') in STATES else 'observed')
        if state not in STATES: raise ValueError('unsupported_observation_type')
        kind=row.get('signal_kind') or ('status_change' if state not in {'announced','observed'} else 'scheduled' if row.get('start_at') else 'unscheduled')
        if kind not in KINDS: raise ValueError('unsupported_signal_kind')
        if kind=='scheduled' and not row.get('start_at'): raise ValueError('scheduled_date_required')
        observation={'canonical_id':canonical,'record_id':record_id,'source_record_id':row.get('source_record_id'),
                     'observed_at':stamp,'source_published_at':row.get('source_published_at'),
                     'source_published_date':row.get('source_published_date'),'assertion_text':row.get('source_text'),
                     'kind':kind,'observation_type':state,'source_url':row.get('source_url') or row.get('event_detail_url'),
                     'start_at':row.get('start_at'),'end_at':row.get('end_at'),'city_name':row.get('city_name'),
                     'date_evidence':row.get('date_evidence',[]),'review_status':'pending'}
        digest=hashlib.sha256(json.dumps(observation,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
        observation['observation_id']='obs_'+digest
        if observation['observation_id'] in known: continue
        known.add(observation['observation_id']);ledger['observations'].append(observation)
        event=ledger['events'].setdefault(canonical,{'event_id':canonical,'member_record_ids':[],'review_status':human_reviews.get(canonical,'pending'),'history':[]})
        if record_id not in event['member_record_ids']:event['member_record_ids'].append(record_id)
        event['history'].append(observation['observation_id'])
        # Out-of-order arrival cannot overwrite a more recent observation.
        prior=event.get('last_observed_at')
        if prior is None or parsed_stamp>=datetime.fromisoformat(prior.replace('Z','+00:00')):
            event.update(last_observed_at=stamp,event_name=row.get('event_name'),kind=kind,
                         observation_type=state,start_at=row.get('start_at'),end_at=row.get('end_at'),city_name=row.get('city_name'))
    return ledger


def v2_candidates(records):
    """Preserve input IDs and human review. Never export undated/nonlocal signals."""
    return [copy.deepcopy(r) for r in records if r.get('start_at') and r.get('city_name')
            and r.get('event_date_role')=='event' and r.get('city_match')=='text_confirmed'
            and r.get('signal_kind') not in {'market_signal','unscheduled'}]
