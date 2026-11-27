"""Isolated demand-review helpers. No changes to verification or public v2."""
import copy
import re
from datetime import date
from .phase3_public_evidence import redact


def retain_official(current, previous, today):
    """Absence from discovery never retracts a still-valid official record."""
    result={r['event_id']:copy.deepcopy(r) for r in current}
    for old in previous:
        end=old.get('end_at') or old.get('start_at')
        if not end or end<today.isoformat():continue
        key=old['event_id']
        if key not in result:
            result[key]=copy.deepcopy(old)
            result[key].update(source_presence='retained_not_rediscovered',freshness='previous_evidence_only')
        else:
            row=result[key]
            row['review_status']=old.get('review_status','pending')
            row['first_seen_at']=old.get('first_seen_at') or row.get('first_seen_at')
            if row.get('evidence_read_this_run') is not True:
                for field in ['start_at','end_at','sessions','last_evidence_check_at']:
                    if field in old:row[field]=copy.deepcopy(old[field])
                row['freshness']='previous_evidence_only'
            elif (row.get('start_at'),row.get('end_at'))!=(old.get('start_at'),old.get('end_at')):
                row['date_review_required']=True
                row['previous_sessions']=copy.deepcopy(old.get('sessions',[]))
    return list(result.values())


def operating_relevance(row):
    title=row.get('event_name','');kind=row.get('event_type');venue=row.get('venue_name','')
    if row.get('review_status')=='rejected' or row.get('event_status') in {'cancelled','postponed'}:
        priority='exclude';reason='rejected_cancelled_or_postponed'
    elif re.search(r'常规|每周|脱口秀|驻场',title):priority='routine_local';reason='routine_entertainment'
    elif kind=='holiday':priority='origin_market_review';reason='school_population_movement_direction_unknown'
    elif not row.get('city_name'):priority='scope_review';reason='no_confirmed_local_test_area_or_venue'
    elif kind in {'exam','conference','exhibition','sports'} or re.search(r'体育馆|体育场|大剧院',venue):
        priority='priority_review';reason='exam_or_destination_event_requires_lodging_check'
    else:priority='unknown';reason='insufficient_demand_evidence'
    return {'review_priority':priority,'reason':reason,'audience_scale':None,'scale_evidence':row.get('scale_evidence'),
            'cross_city_attendance':row.get('cross_city_attendance_evidence'),
            'lodging_increment_grade':'unknown','revenue_impact':None,
            'note':'Candidate screening only; venue capacity and tour cities do not establish attendance or hotel demand.'}


def recent_announcement(published,as_of,days=7):
    try:delta=(as_of-date.fromisoformat(published[:10])).days
    except (TypeError,ValueError):return False
    return 0<=delta<days


def compact_event(row):
    fields=['event_id','event_name','event_type','city_name','city_slug','scope_level','venue_name','start_at','end_at',
            'sessions','review_status','event_status','source_presence','freshness','first_seen_at','last_evidence_check_at',
            'discovery_lane','evaluation_partition','source_published_at','evidence_read_this_run','date_review_required']
    result={k:copy.deepcopy(row[k]) for k in fields if k in row}
    result['review_status']=row.get('review_status','pending')
    result['source_urls']=list(dict.fromkeys([u for u in row.get('source_urls',[row.get('source_url')]) if u and u.startswith('https://')]))
    result['short_evidence']=[redact(q)[0][:160] for q in row.get('short_evidence',[])][:3]
    result['operating_relevance_candidate']=operating_relevance(row)
    return result


def source_contributions(lanes):
    identities={name:{r['event_id'] for r in rows} for name,rows in lanes.items()}
    union=set().union(*identities.values()) if identities else set()
    result={}
    for name,ids in identities.items():
        others=set().union(*(v for k,v in identities.items() if k!=name)) if len(identities)>1 else set()
        result[name]={'records':len(lanes[name]),'unique_ids':len(ids),'duplicate_observations':len(lanes[name])-len(ids),
                      'unique_contribution':len(ids-others),'overlap_with_other_lanes':len(ids&others)}
    return {'union_records':len(union),'by_lane':result,'discovery_recall':None,'date_accuracy':None,
            'acceptance':'awaiting_independent_human_review','identity_note':'Cross-source duplicates require explicit identity links; counts are record IDs, not population event totals.'}
