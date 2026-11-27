"""Offline acceptance packet: no network, deployment, production writes or gold seeds."""
from __future__ import annotations
import argparse
import collections
import copy
import gzip
import hashlib
import json
import re
from datetime import date,datetime,timedelta
from pathlib import Path
from . import collect
from .event_feed import normalized,build_feed
from .event_observations import build_ledger,v2_candidates
from .phase2_acceptance import git_bytes
from .phase3_discovery import ROOT,safe_output,archive_bytes
from .phase3_platform_signals import extract_signals
from .phase3_public import parse_cosgo
from .source_calendar import parse_listing

TARGETS={'西安市','济南市','天津市'}

def read(path):return json.loads(path.read_text(encoding='utf8'))


def reference_metrics(rows,gold,source_ids=()):
    """Evaluate only frozen references; unmatched output is unknown, never FP."""
    results=[];sources=sorted({r.get('source_id','showstart') for r in rows}|set(source_ids))
    by_source={s:set() for s in sources}
    for b in gold:
        def match(r):
            if r.get('city_name')!=b['city']:return False
            urls={r.get('source_url'),r.get('event_detail_url')}
            return b['url'] in urls or all(normalized(t) in normalized(r.get('event_name')) for t in b['terms'])
        matches=[r for r in rows if match(r)]
        dated=[r for r in matches if r.get('start_at')]
        correct=[r for r in dated if r['start_at']==b['start'] and (r.get('end_at') or r['start_at'])==b['end']]
        for r in correct:by_source[r.get('source_id','showstart')].add(b['id'])
        # Independent date/city diagnostic: URL/title matching without city gate.
        identity=[r for r in rows if b['url'] in {r.get('source_url'),r.get('event_detail_url')}]
        results.append({'benchmark_id':b['id'],'reference_name':b['name'],'category':b['category'],'basis':b['basis'],
            'human_reviewed':False,'candidate_discovered':bool(matches),'dated_outputs':len(dated),'valid_discovery':bool(correct),
            'correct_date_records':len(correct),'wrong_date_records':sum(r['start_at']!=b['start'] or (r.get('end_at') or r['start_at'])!=b['end'] for r in dated),
            'wrong_city_records':sum(b['city'] is not None and r.get('city_name') is not None and r.get('city_name')!=b['city'] for r in identity),
            'city_unresolved_records':sum(b['city'] is not None and r.get('city_name') is None for r in identity),
            'url_city_evaluated':sum(b['city'] is not None and r.get('city_name') is not None for r in identity),
            'matching_record_ids':sorted({r['event_id'] for r in matches}),'sources':sorted({r.get('source_id','showstart') for r in correct})})
        results[-1]['correct_record_ids']=sorted({r['event_id'] for r in correct})
    union=set().union(*by_source.values()) if by_source else set();cumulative=set();source_metrics=[]
    for s,found in by_source.items():
        others=set().union(*(v for k,v in by_source.items() if k!=s)) if len(by_source)>1 else set()
        source_metrics.append({'source_id':s,'valid_reference_ids':sorted(found),'independent_discoveries':len(found),
            'reference_recall':round(len(found)/len(gold),4) if gold else None,'unique_contribution':len(found-others),
            'incremental_in_alphabetic_source_order':len(found-cumulative)})
        cumulative|=found
    denomin=sum(r['dated_outputs'] for r in results);correct=sum(r['correct_date_records'] for r in results)
    strict=[b['id'] for b in gold if b['basis']!='independent_secondary_calendar']
    basis_metrics=[]
    for basis in sorted({b['basis'] for b in gold}):
        ids={b['id'] for b in gold if b['basis']==basis}
        basis_metrics.append({'basis':basis,'references':len(ids),'valid_discoveries':len(ids&union),'rate':round(len(ids&union)/len(ids),4)})
    city_den=sum(r['url_city_evaluated'] for r in results);wrong_cities=sum(r['wrong_city_records'] for r in results)
    return {'method':'diagnostic_reference_comparison_not_independent_human_acceptance','references':len(gold),
        'reference_families':len({b.get('family',b['id']) for b in gold}),'human_reviewed_references':0,
        'secondary_only_reference_count':len(gold)-len(strict),'union_valid_reference_ids':sorted(union),
        'by_reference_basis':basis_metrics,
        'union_recall':round(len(union)/len(gold),4) if gold else None,'non_secondary_recall':round(len(union&set(strict))/len(strict),4) if strict else None,
        'date_accuracy_on_matched_dated_records':{'correct':correct,'evaluated':denomin,'rate':round(correct/denomin,4) if denomin else None},
        'wrong_date_records':sum(r['wrong_date_records'] for r in results),'wrong_city_records':sum(r['wrong_city_records'] for r in results),
        'city_accuracy_on_url_matched_records':{'correct':city_den-wrong_cities,'evaluated':city_den,'rate':round((city_den-wrong_cities)/city_den,4) if city_den else None},
        'false_positive_rate':None,'false_positive_note':'Incomplete reference set; unreferenced output has not been independently adjudicated.',
        'sources':source_metrics,'data':results}


def replay_tickets(folder,today):
    if not (folder/'run.json').exists():return [],{}
    run=read(folder/'run.json');rows=[]
    for c in run['checks']:
        if c['status']!='ok' or not c.get('raw_file'):continue
        raw=archive_bytes(folder,c)
        if raw is None:raise ValueError('archived_response_missing: '+c['url'])
        body=gzip.decompress(raw).decode(c.get('encoding','utf8'),errors='replace')
        if c['url'].startswith('https://www.showstart.com/event/list?'):
            code=re.search(r'cityCode=(\d+)',c['url'])[1];city_name={'29':'西安市','531':'济南市','22':'天津市'}[code]
            city=next(c for c in collect.configured_cities() if c['city_name']==city_name)
            for row in parse_listing(body,city,c['url'],c['checked_at'],today,horizon_days=365):
                row['source_id']='showstart';rows.append(row)
        elif c['url']=='https://cosgo.cn/conventions/':rows.extend(parse_cosgo(body,c['url'],c['checked_at'],today))
    return rows,run


def run(output):
    output=safe_output(output);today=date(2026,11,26)
    production={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'site').rglob('*') if p.is_file()}
    official=read(output/'discovery/events.json');discovery=read(output/'discovery/run.json')
    all_rows=list(official);public_runs=[]
    for folder in ['public','public-repeat']:
        rows,meta=replay_tickets(output/folder,today);all_rows.extend(rows);public_runs.append({'folder':folder,**meta})
    signals=[];platform_status=[];platform_cost=[]
    for folder in ['platforms','platforms-focused']:
        index=read(output/folder/'runs.json')
        for job in index['runs']:
            payload=read(output/folder/job['stdout_file']);platform_cost.append({'folder':folder,'elapsed_seconds':job['elapsed_seconds'],'checked_at':job['checked_at']})
            if 'source_status' not in payload:continue
            signals.extend(extract_signals(payload,job['checked_at']))
            platform_status.append({'query':job['args'][0],'checked_at':job['checked_at'],'source_status':payload['source_status']})
    # Observations from repeat crawls stay separate, stable records deduplicate.
    unique={}
    for r in all_rows:
        key=r['event_id']
        if key not in unique:unique[key]=r
    rows=list(unique.values());dated=[r for r in rows if r.get('start_at')]
    scheduled=[r for r in dated if r.get('city_name') in TARGETS]
    primary=[r for r in scheduled if r.get('evidence_level')!='secondary_listing']
    secondary=[r for r in scheduled if r.get('evidence_level')=='secondary_listing']
    previous_v2={key:read(ROOT/'site/api/v2'/(key+'.json')) for key in ('events','state','changes')}
    ledger=build_ledger([r for r in all_rows if r.get('start_at')]+signals,v2=previous_v2)
    collect.write_json(output/'observation-ledger.json',ledger)
    collect.write_json(output/'market-signals.json',signals)
    collect.write_json(output/'discovered-events.json',dated)
    collect.write_json(output/'v2-compatible-pending-candidates.json',v2_candidates(dated))
    within=lambda r,n:r['start_at']<=(today+timedelta(days=n)).isoformat() and (r.get('end_at') or r['start_at'])>=today.isoformat()
    collect.write_json(output/'next-90-days.json',{'as_of':today.isoformat(),'review_status':'pending','primary_source_candidates':[r for r in primary if within(r,90)],'secondary_source_leads':[r for r in secondary if within(r,90)],'not_a_pricing_instruction':True})
    listing=['# 三城未来90天候选清单','', '观察窗口：2026-11-26起90天。全部 pending；开始日不等于完整演期，规模、住宿转化与主办方状态尚待核验。全国考试未推定为三城现场需求。','', '| 城市 | 日期 | 名称 | 证据层级 | 来源 |','|---|---|---|---|---|']
    for r in sorted([r for r in scheduled if within(r,90)],key=lambda r:(r['city_name'],r['start_at'],r['event_name'])):
        name=r['event_name'].replace('|',' / ').replace('\n',' ');url=r.get('event_detail_url') or r.get('source_url')
        label='二手日历，未读票务正文' if r.get('evidence_level')=='secondary_listing' else '官方正文' if r.get('record_kind')=='official_candidate' else '票务列表同卡片'
        listing.append(f"| {r['city_name']} | {r['start_at']}–{r.get('end_at') or r['start_at']} | {name} | {label} | [证据]({url}) |")
    (output/'next-90-days.md').write_text('\n'.join(listing)+'\n',encoding='utf8')
    collect.write_json(output/'distant-91-365-days.json',[r for r in scheduled if not within(r,90) and within(r,365)])
    # Only now load evaluation references; no benchmark URL is a crawl input.
    benchmark_path=ROOT/'tests/fixtures/phase3-benchmark.json';gold=read(benchmark_path)
    metrics=reference_metrics(rows,gold['data'],[r['source_id'] for r in discovery['routes']]+['showstart','bilibili-search','damai-index','bilibili-ticket-index','cosgo-public-calendar','tianjin-local-acg','weibo','xiaohongshu','douyin','baidu-web','toutiao-search'])
    collect.write_json(output/'benchmark-results.json',metrics)
    by_id={b['id']:b for b in gold['data']}
    collect.write_json(output/'known-misses.json',[by_id[r['benchmark_id']] for r in metrics['data'] if not r['valid_discovery']])
    duplicate_groups=collections.defaultdict(list)
    for row in scheduled:
        duplicate_groups[(normalized(row['event_name']),row.get('city_name'),row.get('venue_name'),row.get('start_at'),row.get('end_at'))].append(row['event_id'])
    duplicates=[{'record_ids':ids,'reason':'same_normalized_title_city_venue_session','adjudicated':False} for ids in duplicate_groups.values() if len(ids)>1]
    duplicates.extend({'benchmark_id':r['benchmark_id'],'record_ids':r['correct_record_ids'],'reason':'multiple_source_records_match_same_reference','adjudicated':False} for r in metrics['data'] if len(r['correct_record_ids'])>1)
    collect.write_json(output/'possible-duplicates.json',duplicates)
    baseline=read(ROOT/'site/api/v1/activities.json')
    trial=copy.deepcopy(baseline);pending=v2_candidates(dated);pending_by_id={r['event_id']:r for r in pending};replaced=set()
    for key in ['data','source_candidates','official_candidates','discovery_candidates']:
        for i,r in enumerate(trial.get(key,[])):
            if r['event_id'] in pending_by_id:trial[key][i]=pending_by_id[r['event_id']];replaced.add(r['event_id'])
    trial.setdefault('official_candidates',[]).extend(r for k,r in pending_by_id.items() if k not in replaced)
    cutoff=max(r.get('last_seen_at') or r.get('first_seen_at') for r in all_rows+signals)
    feed=build_feed(trial,read(ROOT/'site/api/v1/hotspots.json')['meta'],read(ROOT/'site/api/v1/health.json'),datetime.fromisoformat(cutoff.replace('Z','+00:00')),previous_v2,links=read(ROOT/'config/event-links.json')['groups'])
    membership=previous_v2['state']['membership'];new_membership=feed['state']['membership']
    overlap=[r['event_id'] for r in pending if r['event_id'] in membership]
    changed=[k for k in overlap if membership[k]!=new_membership[k]]
    old_reviews={r['event_id']:r.get('review_status') for r in previous_v2['events']['data']}
    promoted=[r['event_id'] for r in feed['events']['data'] if r.get('review_status')=='verified' and old_reviews.get(r['event_id'])!='verified']
    collect.write_json(output/'v2-compatibility.json',{'observation_cutoff':cutoff,'existing_source_record_ids_evaluated':len(overlap),
        'unexpected_canonical_id_changes':changed,'automatic_verified_promotions':promoted,
        'consumer_api_version':feed['events']['meta']['api_version'],'not_written_to_site':True,
        'note':'Full original calendar plus isolated candidates passed through existing build_feed in memory; this does not replace production.'})
    old={r['event_id']:r for key in ['data','source_candidates','official_candidates','discovery_candidates'] for r in baseline.get(key,[]) if r.get('city_name') in TARGETS and r.get('start_at') and within(r,365)}
    collect.write_json(output/'incremental-comparison.json',{'as_of':today.isoformat(),'limitation':'Old frozen production snapshot is not a simultaneous live baseline; this is identity overlap, not a causal discovery uplift.',
        'baseline_commit':'c4c2c52','old_events':list(old.values()),'new_record_ids_not_in_frozen_snapshot':[r['event_id'] for r in scheduled if r['event_id'] not in old],
        'same_record_ids':[r['event_id'] for r in scheduled if r['event_id'] in old]})
    checks=discovery['checks']+[c for x in public_runs for c in x.get('checks',[])]
    unavailable=[c for c in checks if c['status']!='ok']
    collect.write_json(output/'source-availability.json',{'official_routes':discovery['routes'],'request_checks':checks,'platform_searches':platform_status,
        'not_covered':['anonymous Weibo search','anonymous Xiaohongshu search','anonymous Douyin search','primary Bilibili ticket details','calendar multi-schedule extraction','autonomous large-convention structured schedule','confirmed sudden/extra/cancelled concert discovery'],
        'interpretation':'HTTP success, diagnostic availability, retrieval relevance and verified event discovery are different measures.'})
    held=[]
    for row in official:
        if row.get('start_at'):continue
        dates=row.get('date_evidence',[])
        if not dates:reason='no_date_mentions_in_extracted_text'
        elif re.search(r'网上在线课程|开课通知|新闻通气会|汇总|一览|日历|周历|校历',row['event_name']):reason='online_or_multi_event_or_report_requires_review'
        elif not any(e['parsed'].get('event_date_role')=='event' for e in dates):reason='only_non_event_or_ambiguous_dates'
        elif not any(e['parsed'].get('date_confidence')=='explicit_year' and e['parsed'].get('event_date_role')=='event' for e in dates):reason='no_explicit_year_event_date'
        else:reason='past_outside_horizon_or_multiple_windows'
        held.append({'event_id':row['event_id'],'event_name':row['event_name'],'source_url':row['source_url'],'reason':reason,'human_adjudicated':False})
    collect.write_json(output/'official-funnel.json',{'method':'measured_parser_stages_not_manual_activity_truth','roots':len(discovery['routes']),
        'index_pages_attempted':sum(r.get('index_pages_attempted',0) for r in discovery['routes']),
        'relevant_links_per_source_sum':sum(r.get('article_links_found',0) for r in discovery['routes']),
        'article_attempts':sum(r.get('articles_attempted',0) for r in discovery['routes']),
        'extracted_article_records':len(official),'scheduled_records':len(official)-len(held),
        'held_record_reasons':dict(collections.Counter(r['reason'] for r in held)), 'held_records':held})
    sample=read(output/'date-sample/sample-200.json');followup=read(output/'date-followup/annotations.json')
    numeric_new=role_new=0
    for item in followup['data']:
        draft=item.get('draft')
        if not draft or not item['evidence_gate']['passed']:continue
        matched=[e for e in item['rule_extraction']['date_evidence'] if e['parsed'].get('start_at')==draft['start_at'] and (e['parsed'].get('end_at') or e['parsed'].get('start_at'))==draft['end_at']]
        numeric_new+=not matched;role_new+=not any(e['parsed'].get('event_date_role')=='event' for e in matched)
    historical=json.loads(git_bytes('site/api/v1/hotspots.json',ref='c4c2c52'))['data']
    sample_strata=collections.Counter((r['stratum']['city'],r['stratum']['topic']) for r in sample['data'])
    collect.write_json(output/'date-audit-summary.json',{'baseline_commit':'c4c2c52','historical_rows':len(historical),
        'missing_start_at_rows':sum(not r.get('start_at') for r in historical),'sample_size':sample['sample_size'],'seed':sample['seed'],
        'sample_strata':[{'city':k[0],'topic':k[1],'sample_count':v} for k,v in sorted(sample_strata.items())],
        'direct_original_bodies':sample['original_body_read_count'],'human_completed':0,'body_existence_unknown':sample['sample_size'],
        'independent_followup_articles':sum(bool(r['body_text']) for r in followup['data']),
        'labels_required':['no_event_date_in_original','rss_missing_body_has_date','parser_rule_miss','non_event_date','historical_or_undetermined'],
        'llm_body_increment':{'cases':len(followup['data']),'literal_evidence_gate_passes':sum(x['evidence_gate']['passed'] for x in followup['data']),
                              'numeric_date_proposals_not_parsed_by_rule':numeric_new,'additional_event_role_proposals':role_new,
                              'date_accuracy':None,'independent_human_labels':0,'note':'Three historical date proposals and one undetermined historical report. Not a representative accuracy estimate or new future events.'}})
    cost={'archived_discovery_and_ticket_checks':len(checks),'archived_successes':sum(c['status']=='ok' for c in checks),'archived_failed_or_blocked':len(unavailable),
          'archived_bytes':sum(c.get('bytes',0) for c in checks),'summed_request_elapsed_seconds':round(sum(c.get('elapsed_seconds',0) for c in checks),3),
          'third_party_cli_elapsed_seconds':round(sum(c['elapsed_seconds'] for c in platform_cost),3),'third_party_query_runs':len(platform_status),
          'paid_external_llm_calls':0,'paid_data_services':0,'currency_cost':None,
          'cost_limitations':'Archived request timings exclude discarded crash attempts, web research, assistant tokens and benchmark validation. No exact total monetary-cost or production reliability claim.',
          'public_repeats':[{'folder':x['folder'],'routes':x.get('routes'), 'elapsed_seconds':x.get('elapsed_seconds')} for x in public_runs]}
    collect.write_json(output/'cost-stability.json',cost)
    production_after={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'site').rglob('*') if p.is_file()}
    unchanged=production==production_after
    base_differences=[path for path in production if git_bytes(path,ref='c4c2c52').replace(b'\r\n',b'\n')!=(ROOT/path).read_bytes().replace(b'\r\n',b'\n')]
    collect.write_json(output/'production-integrity.json',{'before':production,'after':production_after,'unchanged':unchanged,
        'comparison_base':'c4c2c52','line_endings_normalized_for_git_reference':True,'changed_site_paths_since_phase2':base_differences,
        'identical_to_phase2_base':not base_differences,'main_comparison_note':'PR already contains Phase1 changes to public API/site relative to main. Phase3 does not regenerate or modify those snapshots.'})
    summary={'as_of':today.isoformat(),'business_acceptance':'NOT_PASSED','official_roots':len(discovery['routes']),
        'official_article_records':len(official),'official_dated_records':sum(bool(r.get('start_at')) for r in official),
        'official_held_for_review':sum(not r.get('start_at') for r in official),'distinct_source_records':len(rows),'dated_distinct_source_records':len(dated),
        'local_primary_candidates':len(primary),'local_secondary_leads':len(secondary),'national_or_unresolved_dated_candidates':len(dated)-len(scheduled),
        'next90_primary_candidates':sum(within(r,90) for r in primary),'next90_secondary_leads':sum(within(r,90) for r in secondary),
        'distant91_365':sum(not within(r,90) and within(r,365) for r in scheduled),'unique_social_signals':len({r['event_id'] for r in signals}),
        'social_signal_observations':len(signals),'potential_duplicate_groups':len(duplicates),'benchmark':{k:v for k,v in metrics.items() if k not in {'sources','data'}},
        'date_sample':{'sample_size':sample['sample_size'],'direct_original_bodies':sample['original_body_read_count'],'independently_rediscovered_articles':sum(bool(x['body_text']) for x in followup['data']),
                       'human_completed':0,'assistant_evidence_gated_drafts':sum(x['evidence_gate']['passed'] for x in followup['data'])},
        'production_unchanged':unchanged,'production_identical_to_phase2_base':not base_differences,'benchmark_sha256':hashlib.sha256(benchmark_path.read_bytes()).hexdigest()}
    collect.write_json(output/'summary.json',summary)
    print(json.dumps(summary,ensure_ascii=True))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args();run(args.output)
