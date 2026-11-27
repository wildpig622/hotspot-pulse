"""Offline compact Phase4 tables; outputs never include full source bodies."""
import json
from datetime import date,timedelta
from pathlib import Path
from . import collect
from .phase3_discovery import ROOT
from .event_observations import build_ledger


def build():
    out=ROOT/'docs/phase4-review-2026-11-27';load=lambda p:json.loads(p.read_text(encoding='utf8'))
    rows=load(out/'high-value-review.json');cases=load(ROOT/'config/phase4-agent-decisions.json')['data']
    findings={r['event_id']:r['status_findings'] for r in cases}
    by_id={r['event_id']:r for r in cases}
    assessments={r['event_id']:r for r in load(out/'source-assessments.json')}
    fresh=load(out/'traditional_collector.json');prior=load(ROOT/'docs/phase3-evidence-2026-11-26/discovered-events.json')
    needles={'p4_naying_xian':['那英'],'p4_xuliang_jinan':['徐良'],'p4_laolang_tianjin':['老狼'],
        'p4_huyanbin_jinan':['胡彦斌'],'p4_linzhixuan_tianjin':['林志炫'],'p4_nj_tianjin':['NJ'],
        'p4_industry_jinan':['工业','自动化'],'p4_medical_jinan':['医疗器械'],'p4_solar_jinan':['光储'],
        'p4_jinan_civil_public':['公务员'],'p4_iccll_regression':['ICCLL'],'p4_yeshirong_extra':['叶世荣']}
    def matches(a,b):
        return a.get('city_name')==b.get('city_name') and a.get('start_at')==b.get('start_at') and bool(a.get('start_at')) and all(t in b.get('event_name','') for t in needles.get(a['event_id'],['__no_automatic_match__']))
    comparison=[]
    for row in cases:
        comparison.append({'event_id':row['event_id'],'evaluation_partition':row['evaluation_partition'],
            'matching_fresh_traditional_ids':[r['event_id'] for r in fresh if matches(row,r)],
            'matching_phase3_frozen_ids':[r['event_id'] for r in prior if matches(row,r)],
            'identity_review':'diagnostic title/date/city match only; not a canonical merge or human judgement'})
    collect.write_json(out/'incremental-comparison.json',comparison)
    initial=[]
    for city in ['西安','济南','天津']:
        for intent in ['最近7天 演唱会 官宣 加场 2026 11月','2027 重大 演唱会 官方','2026 12月 2027 1月 考试 招录 考点 公告','学校 寒假 秋假 客源地 2026 2027 校历','2026 12月 2027 大型 会展 会议 体育赛事 官方','最近一周 漫展 应援 粉丝 聚集 文旅 热点 2026 11月']:
            initial.append(city+' '+intent)
    collect.write_json(out/'agent-trace.json',{'execution':'live assistant web-search/read/verification loop in this chat, then decision replay with direct public-body checks',
        'initial_queries':initial,'initial_query_count':18,'adaptive_query_count':8,'targeted_query_count':9,'discovered_entity_verification_queries':1,
        'web_search_tool_invocations':10,'web_document_open_attempts':18,
        'adaptive_queries':['西安 2026年12月 体育馆 演唱会 官宣 开票','天津 2026年12月31日 演唱会 官方','西安 2027 研究生 报考点 西安电子科技大学 12月19日','济南 2027 研究生 考点 12月19日'],
        'no_initial_activity_names':True,'specific_name_followups':'regression or verification only, never initial discovery inputs',
        'standalone_status':'Bing RSS alternative actually tested but unavailable; not claiming a validated unattended web-tool service',
        'paid_api_provisioning':False,'search_currency_cost':None,'assistant_token_cost':None,'human_acceptance':'pending'})
    collect.write_json(out/'recency-followup.json',{'queries_with_recency_7_filter':['西安 演唱会 官宣 加场 开票','济南 演唱会 官宣 加场 开票','天津 演唱会 官宣 加场 开票','天津 济南 西安 体育 赛事 会展 官宣'],
        'discovered_url':'https://feng.ifeng.com/c/8yKyFYwjxpn','followup_entity':'叶世荣天津加场',
        'verification_urls':['https://www.sina.cn/news/detail/5368771845818684.html','https://www.sina.cn/news/detail/5368758589195685.html'],
        'finding':'2026-11-24发布加场，新增2027-01-17；不把开票11月29日混为演出日；仍未独立人工验收。'})
    observed=[]
    for r in rows:
        if r['event_id'] not in findings:continue
        stamp=min(s['checked_at'] for s in assessments[r['event_id']]['sources'])
        observed.append({**r,'source_url':r['source_urls'][0],'first_seen_at':stamp,'last_seen_at':stamp,
            'source_published_date':r.get('source_published_at'),'source_published_at':None,
            'observation_type':by_id[r['event_id']].get('observation_type','observed'),
            'date_evidence':[{'quote':q} for q in r['short_evidence']]})
        for followup in by_id[r['event_id']].get('followup_observations',[]):
            access=next(s for s in assessments[r['event_id']]['sources'] if s['url']==followup['source_url'])
            observed.append({**r,**followup,'first_seen_at':access['checked_at'],'last_seen_at':access['checked_at'],
                'source_published_at':None,'date_evidence':[{'quote':followup['quote']}],
                'signal_kind':'status_change'})
    collect.write_json(out/'observations.json',build_ledger(observed))
    lines=['# 三城高价值住宿需求候选','',
      '观察日期2026-11-27。此表是复核优先级，全部保持原核验状态；所有人数、跨城观众比例、住宿增量与收益影响均未知。日期范围不保证逐日都有场次。','',
      '| 城市/范围 | 日期 | 候选 | 来源与本轮证据 | 经营复核方向 |','|---|---|---|---|---|']
    for row in sorted(rows,key=lambda r:(r.get('city_name') or '',r.get('start_at') or '9999',r['event_name'])):
        start=row.get('start_at');end=row.get('end_at') or start;day=(start+'至'+end) if start else '未定档/范围线索'
        urls=row.get('source_urls',[]);url=urls[0] if urls else ''
        status='短证据已在直接正文匹配' if row.get('evidence_read_this_run') else '旧证据保留/索引或正文仍需复核'
        direction=row['operating_relevance_candidate']['review_priority']
        lines.append(f"| {row.get('city_name') or '全国，未推定地方'} | {day} | {row['event_name']} | [来源]({url})；{status} | {direction}；规模未知 |")
    (out/'high-value-list.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    holdout=load(ROOT/'tests/fixtures/phase4-holdout.json')
    collect.write_json(out/'business-acceptance.json',{'status':'NOT_ACCEPTED','independent_human_reviewed':0,
        'open_decisions':sum(r['evaluation_partition']=='open_discovery' for r in cases),
        'open_dated_candidates':sum(r['evaluation_partition']=='open_discovery' and bool(r.get('start_at')) for r in cases),
        'open_recent7_supported_extra_show_claims':sum(r['evaluation_partition']=='open_discovery' and r.get('observation_type')=='extra_show' and assessments[r['event_id']]['recent_7_day_publication'] and any(s['matching_short_quotes'] for s in assessments[r['event_id']]['sources']) for r in cases),'open_recent7_independently_human_verified':0,
        'targeted_cases_excluded_from_open_rate':True,'holdout_positive_count':len(holdout['positives']),'negative_control_count':len(holdout['negative_controls']),
        'blind_test_limit':'Query-level separation using pre-existing independent permission references, not independent human blind adjudication.',
        'recall':None,'date_accuracy':None,'city_accuracy':None,'false_positive_rate':None,'duplicate_rate':None})
    print({'review_rows':len(rows),'open_decisions':sum(r['evaluation_partition']=='open_discovery' for r in cases)})

if __name__=='__main__':build()
