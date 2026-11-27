"""Search-provider experiment and compact review packet, never a production job.

The live assistant search trace is separate from this decision-verification
runner. Replaying named decisions is not counted as autonomous discovery.
"""
import argparse
import collections
import hashlib
import json
import time
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from . import collect
from .demand_candidates import compact_event,retain_official,source_contributions,recent_announcement
from .phase3_discovery import Reader,ROOT,document,safe_output
from .source_calendar import parse_listing
from .phase3_public_evidence import redact

CITIES=['西安','济南','天津']
INTENTS=['最近7天 演唱会 官宣 加场 2026 11月','2027 重大 演唱会 官方',
 '2026 12月 2027 1月 考试 招录 考点 公告','学校 寒假 秋假 客源地 2026 2027 校历',
 '2026 12月 2027 大型 会展 会议 体育赛事 官方','最近一周 漫展 应援 粉丝 聚集 文旅 热点 2026 11月']


def query_plan():return [{'city':c,'intent':i,'query':c+' '+i,'input_activity_names':False} for c in CITIES for i in INTENTS]


class BingRssProvider:
    """Anonymous public endpoint availability probe; obey robots, no login."""
    def __init__(self,reader):self.reader=reader
    def search(self,query):
        url='https://www.bing.com/search?'+urllib.parse.urlencode({'format':'rss','q':query})
        body,check=self.reader.fetch(url,'anonymous_search_probe')
        if not body:return [],check
        try:root=ET.fromstring(body)
        except ET.ParseError:return [],{**check,'search_error':'not_rss_or_dynamic_page'}
        return [{'url':n.findtext('link'),'title':n.findtext('title')} for n in root.findall('./channel/item') if (n.findtext('link') or '').startswith('https://')],check


class SearchAgent:
    def __init__(self,provider,reader,budget=4):self.provider=provider;self.reader=reader;self.budget=budget
    def discover(self,query):
        links,check=self.provider.search(query);observations=[]
        for item in links[:self.budget]:
            body,access=self.reader.fetch(item['url'],'agent_search_body')
            observations.append({'url':item['url'],'title':item['title'],'body_read':bool(body),'access':access})
        return {'query':query,'search_check':check,'results':observations,'benchmark_used':False}


def norm(s):return ''.join(str(s).split())
def public_write(path,value):
    def clean(v):
        if isinstance(v,dict):return {k:clean(x) for k,x in v.items() if k not in {'body_text','raw_file','encoding'}}
        if isinstance(v,list):return [clean(x) for x in v]
        if isinstance(v,str):return redact(v)[0]
        return v
    collect.write_json(path,clean(value))
def run(output,private):
    output=safe_output(output);private=safe_output(private)
    if not private.is_relative_to(ROOT/'review'):raise ValueError('private_response_directory_must_be_ignored_review')
    today=date(2026,11,27);reader=Reader(private,1);started=time.monotonic()
    decisions=json.loads((ROOT/'config/phase4-agent-decisions.json').read_text(encoding='utf8'))['data']
    previous=json.loads((ROOT/'docs/phase2-evidence-2026-11-26/official-events.json').read_text(encoding='utf8'))
    for r in previous:
        r['last_evidence_check_at']=r.get('last_evidence_check_at') or r.get('checked_at')
        r['source_urls']=[r['source_url']];r['short_evidence']=[];r['discovery_lane']='retained_official';r['evaluation_partition']='targeted_regression'
    urls=list(dict.fromkeys([u for r in decisions for u in r['source_urls']]+[r['source_url'] for r in previous]))
    with ThreadPoolExecutor(max_workers=3) as pool:responses=dict(zip(urls,pool.map(lambda url:reader.fetch(url,'decision_crosscheck_not_discovery'),urls)))
    rows=[];assessments=[]
    for r in decisions:
        r=dict(r);checks=[]
        for url in r['source_urls']:
            body,check=responses[url];text=document(body)[1] if body else ''
            supported=[q for q in r['short_evidence'] if norm(q) in norm(text)]
            checks.append({'url':url,'status':check['status'],'checked_at':check.get('checked_at'),
                'direct_body_read':bool(text.strip()),'matching_short_quotes':supported,'sha256':check.get('sha256'),'error':check.get('error')})
        r.update(review_status='pending',event_status='unknown',scope_level=r.get('scope_level','city'),
                 evidence_read_this_run=any(c['matching_short_quotes'] for c in checks),
                 first_seen_at=min(c['checked_at'] for c in checks),last_evidence_check_at=None)
        supported=[c for c in checks if c['matching_short_quotes']]
        if supported:r['last_evidence_check_at']=max(c['checked_at'] for c in supported)
        rows.append(r);assessments.append({'event_id':r['event_id'],'status_findings':r['status_findings'],'sources':checks,
            'recent_7_day_publication':recent_announcement(r.get('source_published_at'),today),
            'cross_source_independent_verification':'not_claimed','human_acceptance':'pending'})
    current=[]
    for old in previous:
        body,check=responses[old['source_url']]
        if body:
            r=dict(old);r.update(evidence_read_this_run=True,source_presence='retained_known_official')
            # Body access alone cannot certify unchanged dates. Keep old
            # fact-check time rather than silently refreshing the schedule.
            r['evidence_read_this_run']=False;r['body_accessed_at']=check['checked_at'];current.append(r)
    official=retain_official(current,previous,today)
    traditional=[];traditional_checks=[]
    for name,code in [('西安市',29),('济南市',531),('天津市',22)]:
        url=f'https://www.showstart.com/event/list?cityCode={code}&pageNo=1';body,check=reader.fetch(url,'traditional_listing')
        traditional_checks.append(check)
        if not body:continue
        city=next(c for c in collect.configured_cities() if c['city_name']==name)
        try:traditional.extend(parse_listing(body,city,url,check['checked_at'],today,horizon_days=365))
        except ValueError:pass
    agent=SearchAgent(BingRssProvider(reader),reader,budget=2)
    probes=[agent.discover(c+' 未来365天 演唱会 官方') for c in CITIES]
    lanes={'traditional_collector':traditional,'search_agent':rows,
        'official_notice':[r for r in rows if r['discovery_lane']=='official_notice']+official,
        'social_signal':[r for r in rows if r['discovery_lane']=='social_signal']}
    all_rows=[compact_event(r) for r in rows+official]
    for lane,data in lanes.items():public_write(output/(lane+'.json'),[compact_event(r) for r in data])
    public_write(output/'high-value-review.json',all_rows)
    public_write(output/'query-plan.json',query_plan())
    public_write(output/'source-assessments.json',assessments)
    fields=['url','role','status','checked_at','http_status','sha256','bytes','elapsed_seconds','error','error_type']
    public_write(output/'source-access.json',[{k:c[k] for k in fields if k in c} for c in reader.checks])
    public_write(output/'provider-probes.json',probes)
    public_write(output/'comparison.json',{'all_records':source_contributions(lanes),
        'open_decision_records':source_contributions({k:[r for r in v if r.get('evaluation_partition')=='open_discovery'] for k,v in lanes.items()}),
        'note':'Targeted regression and retained official records excluded from open decisions. Unlabelled traditional results require independent matching; no causal recall or uplift claim.'})
    old3=json.loads((ROOT/'docs/phase3-evidence-2026-11-26/discovered-events.json').read_text(encoding='utf8'))
    oldids={r['event_id'] for r in old3}
    lost=[r['event_id'] for r in previous if r['event_id'] not in oldids]
    public_write(output/'official-retention-audit.json',{'phase2_official':len(previous),'phase3_missing_record_ids':lost,
      'root_cause':'phase3_report builds all_rows from current discovery and public listings only; previous official rows were used solely to preserve matching IDs, never unioned into the calendar.',
      'additional_causes':['national source TLS/connection failures','dynamic calendar columns return no article links','calendar multi-window rows deliberately held by parser'],
      'fixed_in':'Phase4 fused review layer; still-valid records retained without changing IDs, review status or original evidence timestamps.',
      'retained_ids':[r['event_id'] for r in official]})
    collect.write_json(private/'run.json',{'checks':reader.checks})
    public_write(output/'cost-stability.json',{'as_of':today.isoformat(),'direct_request_checks':len(reader.checks),
      'replay_or_run_elapsed_seconds':round(time.monotonic()-started,3),'fresh_request_checks_this_invocation':len(reader.checks)-reader.initial_request_count,
      'recorded_request_elapsed_seconds':round(sum(c.get('elapsed_seconds',0) for c in reader.checks),3),'downloaded_bytes':sum(c.get('bytes',0) for c in reader.checks),
      'paid_services_enabled':False,'external_paid_model_calls':0,'total_currency_cost':None,
      'limitations':'Web-tool search and assistant-token cost not exposed. One bounded run is not a production reliability estimate.',
      'anonymous_provider_results':sum(len(p['results']) for p in probes)})
    print(json.dumps({'review_records':len(all_rows),'retained_official':len(official),'traditional_records':len(traditional),'source_checks':len(reader.checks)}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--private',type=Path,required=True);a=p.parse_args();run(a.output,a.private)
