"""Bounded autonomous discovery; input is index roots, never benchmark names/URLs."""
from __future__ import annotations
import argparse
import concurrent.futures
import gzip
import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import zipfile
from datetime import date,timedelta
from pathlib import Path
from . import collect
from .phase2_acceptance import Page

ROOT=Path(__file__).resolve().parents[1]
RELEVANT=re.compile(r'考试|招录|招聘|招考|考研|考点|校历|寒假|暑假|春假|秋假|学术|会议|研讨会|大会|年会|论坛|演唱会|演出|音乐|漫展|动漫|家博会|博览会|会展|展览|展会|电竞|文旅|放假')
PAGE=re.compile(r'下一页|下页|尾页|^更多$|^更多[>》]+$|Next|^\d+$',re.I)
DATE=re.compile(r'(?:(?:20\d{2})年)?\d{1,2}月\d{1,2}日|20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}')

def safe_output(path):
    path=Path(path).resolve()
    if path==ROOT or path.is_relative_to(ROOT/'site') or any(p.lower()=='sources' for p in path.parts):
        raise ValueError('isolated_output_required')
    path.mkdir(parents=True,exist_ok=True);return path


def archive_bytes(output,check):
    """Read a loose response or the review bundle without extracting paths."""
    output=Path(output);relative=check.get('raw_file','missing').replace('\\','/')
    path=output/relative
    if path.is_file():return path.read_bytes()
    bundle=output.parent/'responses.zip'
    if bundle.is_file():
        member=output.name+'/'+relative
        with zipfile.ZipFile(bundle) as archive:
            try:return archive.read(member)
            except KeyError:return None
    return None

class Reader:
    def __init__(self,output,interval=1.0):
        self.output=safe_output(output); self.checks=[];self.interval=interval;self.locks={};self.guard=threading.Lock();self.last={};self.robots={};self.cache={}
        self.initial_request_count=0
        previous=self.output/'run.json'
        if previous.exists():
            self.checks=json.loads(previous.read_text(encoding='utf8'))['checks']
            self.initial_request_count=len(self.checks)
            for c in self.checks:
                archived=archive_bytes(self.output,c) if c['status']=='ok' else None
                if c['status']=='ok' and archived is None:raise ValueError('archived_response_missing: '+c['url'])
                body=gzip.decompress(archived).decode(c.get('encoding','utf8'),errors='replace') if archived is not None else ''
                self.cache[c['url']]=(body,c)
    def fetch(self,url,role='article',respect_robots=True):
        parsed=urllib.parse.urlsplit(url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
            return '',{'url':url,'status':'rejected','error':'https_only'}
        if url in self.cache:return self.cache[url]
        with self.guard: lock=self.locks.setdefault(parsed.netloc,threading.RLock())
        with lock:
            if url in self.cache:return self.cache[url]
            if respect_robots:
                host=parsed.scheme+'://'+parsed.netloc
                if host not in self.robots:
                    robot_body,robot_check=self.fetch(host+'/robots.txt','robots',False)
                    parser=urllib.robotparser.RobotFileParser();parser.parse(robot_body.splitlines())
                    # 404 means no published rules; other failures remain explicit.
                    self.robots[host]=(parser,robot_check)
                parser,robot_check=self.robots[host]
                if (robot_check['status']!='ok' and robot_check.get('http_status')!=404) or (robot_check['status']=='ok' and not parser.can_fetch(collect.USER_AGENT,url)):
                    check={'url':url,'role':role,'status':'blocked','error':'robots_or_host_denial','checked_at':collect.iso_utc(collect.now_utc())}
                    self.checks.append(check);self.cache[url]=('',check);return '',check
            time.sleep(max(0,self.interval-(time.monotonic()-self.last.get(parsed.netloc,0))))
            self.last[parsed.netloc]=time.monotonic(); started=time.monotonic()
            check={'url':url,'role':role,'checked_at':collect.iso_utc(collect.now_utc())}
            try:
                req=urllib.request.Request(url,headers={'User-Agent':collect.USER_AGENT,'Accept':'text/html,application/json,application/xml;q=0.8'})
                with urllib.request.urlopen(req,timeout=10) as resp:
                    raw=resp.read(1_500_001);check.update(http_status=resp.status,final_url=resp.url)
                    encoding=resp.headers.get_content_charset()
                if len(raw)>1_500_000:raise ValueError('body_size_limit')
                if not encoding:
                    match=re.search(br'charset=["\s]*([\w-]+)',raw[:4096],re.I)
                    encoding=match[1].decode() if match else 'utf-8'
                body=raw.decode(encoding,errors='replace')
                if re.search(r'访问验证|安全验证|请输入验证码|Access Denied|Just a moment|异常访问',body[:10000],re.I):raise ValueError('access_challenge')
                digest=hashlib.sha256(raw).hexdigest();target=self.output/'raw'/(digest+'.gz');target.parent.mkdir(exist_ok=True)
                target.write_bytes(gzip.compress(raw,mtime=0))
                check.update(status='ok',sha256=digest,raw_file=target.relative_to(self.output).as_posix(),encoding=encoding,bytes=len(raw))
            except Exception as exc:
                body='';check.update(status='failed',error_type=type(exc).__name__,error=str(exc),http_status=getattr(exc,'code',check.get('http_status')))
            check['elapsed_seconds']=round(time.monotonic()-started,3);self.checks.append(check);self.cache[url]=(body,check)
            return body,check

def document(body):
    parser=Page();parser.feed(body)
    text=re.sub(r'[ \t\r\f]+',' ',''.join(parser.text));text=re.sub(r'\n\s*\n+','\n',text)
    title=re.search(r'<h1[^>]*>(.*?)</h1>',body,re.S|re.I) or re.search(r'<title[^>]*>(.*?)</title>',body,re.S|re.I)
    return (collect.clean_html(title[1]) if title else ''),text,parser.links

class ArticleText(Page):
    def __init__(self):
        super().__init__();self.content_depth=0;self.content=[];self.content_found=False
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='div':
            if self.content_depth:self.content_depth+=1
            elif re.search(r'v_news_content|TRS_Editor|article[-_]content|vsb_content|ArticleContent|TRS_UEDITOR',' '.join(str(v or '') for v in attrs.values())):
                self.content_depth=1;self.content_found=True
        super().handle_starttag(tag,list(attrs.items()))
        if self.content_depth and tag in ('p','div','br','li','tr'):self.content.append('\n')
    def handle_endtag(self,tag):
        if tag=='div' and self.content_depth:self.content_depth-=1
        super().handle_endtag(tag)
    def handle_data(self,data):
        if self.content_depth and not self.skip:self.content.append(data)
        super().handle_data(data)

def candidate_links(body,url):
    _,_,links=document(body);host=urllib.parse.urlsplit(url).hostname;articles=[];pages=[]
    for href,label in links:
        full=urllib.parse.urljoin(url,href).split('#')[0]
        p=urllib.parse.urlsplit(full);label=collect.clean_html(label)
        if p.scheme!='https' or p.hostname!=host or re.search(r'\.(?:pdf|docx?|xlsx?|jpe?g|png|zip)(?:\?|$)',full,re.I):continue
        if full==url:continue
        if PAGE.search(label):pages.append(full)
        elif RELEVANT.search(label):
            if re.search(r'NewsList|/zc/|/col/[^/]+/index|/tzgg[^/]*\.htm$',full,re.I) and not re.search(r'20\d{2}',label):pages.append(full)
            elif len(label)>=7:articles.append((full,label))
    return list(dict.fromkeys(articles)),list(dict.fromkeys(pages))

def extract_article(body,source,url,stamp,today,title_hint=''):
    title,text,_=document(body);title=title or title_hint
    if title_hint and RELEVANT.search(title_hint) and not RELEVANT.search(title):title=title_hint
    main=ArticleText();main.feed(body)
    if main.content_found:text=''.join(main.content)
    else:text=re.split(r'版权所有|Copyright|联系我们|友情链接',text,flags=re.I)[0]
    observed=[];topic=collect.classify_event(title)
    if topic=='other':topic=source.get('topic','other')
    # Preserve all date mentions and their exact windows; only event-labelled
    # dates become scheduled records. Publication/birth/registration stay out.
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    date_evidence=[]
    for index,line in enumerate(lines):
        for match in DATE.finditer(line):
            snippet=line[max(0,match.start()-55):min(len(line),match.end()+100)]
            parsed=collect.extract_event_date(snippet,today=today)
            date_evidence.append({'quote':snippet,'date_text':match[0],'parsed':parsed,'line_index':index})
    alias_cities=[]
    for city in collect.configured_cities():
        aliases='|'.join(re.escape(a) for a in city['aliases'])
        if re.search(r'(?:地点|考点|考场|会场|举办地|地址)[：:\s][^。\n]{0,45}(?:'+aliases+r')|在(?:'+aliases+r')[^。\n]{0,35}(?:举行|举办|召开)',text):alias_cities.append(city)
    if not alias_cities:
        alias_cities=[c for c in collect.configured_cities() if any(a in title for a in c['aliases'])]
    city=alias_cities[0] if len(alias_cities)==1 else None
    # A school name or query city alone is not a local venue assertion.
    scope=source.get('scope','unknown')
    if scope=='national': city=None
    for evidence in date_evidence:
        if re.search(r'成绩.*公布|成绩查询|录取结果|公示时间|报名截止|缴费截止|发布时间|发布日期',evidence['quote']):
            evidence['parsed']['event_date_role']='non_event'
    explicit=[e for e in date_evidence if e['parsed'].get('event_date_role')=='event' and e['parsed'].get('start_at') and e['parsed'].get('date_confidence')=='explicit_year']
    sessions=[]
    for e in explicit:
        start=e['parsed']['start_at'];end=e['parsed'].get('end_at') or start
        if end>=today.isoformat() and start<=(today+timedelta(days=365)).isoformat():
            session={'start_at':start,'end_at':end}
            if session not in sessions:sessions.append(session)
    # More than one distinct date window in prose may describe unrelated
    # events. Keep in review rather than manufacturing a continuous event.
    scheduled=len(sessions)==1 and bool(title) and not re.search(r'汇总|一览|年度.*计划|日历|周历|校历|网上在线课程|开课通知|新闻通气会',title)
    identity='off_'+hashlib.sha256(url.encode()).hexdigest()[:12]
    row={'event_id':identity,'source_record_id':url,'event_name':title,'event_type':topic,
         'city_name':city['city_name'] if city else None,'city_slug':city['city_slug'] if city else None,
         'city_match':'text_confirmed' if city else 'not_established','scope_level':scope,
         'source_scope_city':source.get('city'),'impact_destination_cities':source.get('impact_cities',[]),
         'local_demand_confirmed':False,'event_date_role':'event' if scheduled else 'unknown',
         'content_kind':collect.classify_content(title,text[:800]),'date_precision':'day' if scheduled else 'tbd',
         'date_confidence':'source_body' if scheduled else 'unknown','sessions':sessions if scheduled else [],
         'start_at':sessions[0]['start_at'] if scheduled else None,'end_at':sessions[0]['end_at'] if scheduled else None,
         'review_status':'pending','event_status':'unknown','record_kind':'official_candidate',
         'event_phase':'scheduled' if scheduled else 'unscheduled','date_evidence':date_evidence,
         'body_text':text,'content_extraction':'article_container' if main.content_found else 'page_without_footer',
         'evidence_level':'source_body','source_url':url,'first_seen_at':stamp,'last_seen_at':stamp,
         'last_evidence_check_at':stamp,'source_id':source['id'],'source_count':1,
         'sources':[{'source_url':url,'publisher':source['id'],'checked_at':stamp,'observed_at':stamp,'access_status':'body_read','verification_status':'unverified'}]}
    return row

def crawl_source(reader,source,today,config):
    queue=[source['url']];seen=set();articles={};traversal=[]
    while queue and len(seen)<config['max_index_pages']:
        url=queue.pop(0)
        if url in seen:continue
        seen.add(url);body,check=reader.fetch(url,'index');traversal.append(check)
        if not body:continue
        found,pages=candidate_links(body,url)
        for full,title in found:
            articles.setdefault(full,title)
        queue.extend(p for p in pages if p not in seen)
    records=[]
    # Stable article order from entry pages: benchmark data is never loaded.
    def rank(item):
        url,title=item
        year=re.search(r'20\d{2}',title)
        score=(int(year[0]) if year else 0)+10*bool(re.search(r'考试|报名|校历|放假|会议|研讨会|年会',title))
        score-=30*bool(re.search(r'科研规划|课题|项目申报|实验室.*招聘|党委|政治局|成功举办|顺利举行',title))
        return score
    for url,title in sorted(articles.items(),key=rank,reverse=True)[:config['max_articles_per_source']]:
        body,check=reader.fetch(url,'article')
        if body:
            records.append(extract_article(body,source,url,check['checked_at'],today,title))
    return records,{'source_id':source['id'],'entry_url':source['url'],'index_pages_attempted':len(seen),
                    'article_links_found':len(articles),'articles_attempted':min(len(articles),config['max_articles_per_source']),
                    'records':len(records),'pagination_stop':'page_budget' if queue else 'no_next_link',
                    'article_stop':'article_budget' if len(articles)>config['max_articles_per_source'] else 'exhausted',
                    'unvisited_pages':queue,'unread_article_count':max(0,len(articles)-config['max_articles_per_source']),
                    'index_checks':traversal}

def run(output,today):
    output=safe_output(output);config=json.loads((ROOT/'config/phase3-discovery.json').read_text(encoding='utf8'))
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'site/api').rglob('*.json')}
    reader=Reader(output,config['min_host_interval_seconds']);started=time.monotonic();rows=[];routes=[]
    def guarded(source):
        try:return crawl_source(reader,source,today,config)
        except Exception as exc:return [],{'source_id':source['id'],'entry_url':source['url'],'status':'parser_failed','error_type':type(exc).__name__,'error':str(exc)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=config['workers']) as pool:
        for records,route in pool.map(guarded,config['sources']):rows.extend(records);routes.append(route)
    from .event_observations import preserve_record_ids
    prior=ROOT/'docs/phase2-evidence-2026-11-26/official-events.json'
    rows,identity_links=preserve_record_ids(rows,json.loads(prior.read_text(encoding='utf8')) if prior.exists() else [])
    report={'as_of':today.isoformat(),'horizon_days':365,'input_kind':'index_roots_only','identity_links':identity_links,'config_sha256':hashlib.sha256((ROOT/'config/phase3-discovery.json').read_bytes()).hexdigest(),
            'benchmark_loaded_by_collector':False,'routes':routes,'checks':reader.checks,'elapsed_seconds':round(time.monotonic()-started,3),
            'request_count':len(reader.checks),'fresh_request_count':len(reader.checks)-reader.initial_request_count,'reused_archived_requests':reader.initial_request_count,'downloaded_bytes':sum(c.get('bytes',0) for c in reader.checks),
            'production_unchanged':hashes=={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'site/api').rglob('*.json')}}
    collect.write_json(output/'events.json',rows);collect.write_json(output/'run.json',report)
    print(json.dumps({'records':len(rows),'requests':len(reader.checks),'elapsed_seconds':report['elapsed_seconds'],'production_unchanged':report['production_unchanged']}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--as-of',type=date.fromisoformat,required=True)
    args=parser.parse_args();run(args.output,args.as_of)
