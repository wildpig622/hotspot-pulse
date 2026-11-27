"""Anonymous, bounded public ticket-list discovery; no benchmark detail input."""
import argparse
import json
import hashlib
import re
from html.parser import HTMLParser
import time
from datetime import date
from pathlib import Path
from . import collect
from .phase3_discovery import Reader, safe_output
from .source_calendar import parse_listing


class CosgoParser(HTMLParser):
    def __init__(self):
        super().__init__();self.cards=[];self.card=None;self.depth=0;self.field=None
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='div' and 'ev' in (a.get('class') or '').split():
            self.card={'name':'','meta':'','ticket_url':''};self.depth=1
        elif self.card is not None:
            if tag=='div':self.depth+=1
            if tag=='h4':self.field='name'
            elif tag=='div' and a.get('class')=='meta':self.field='meta'
            elif tag=='a':self.card['ticket_url']=a.get('href','')
    def handle_endtag(self,tag):
        if self.card is None:return
        if tag=='h4':self.field=None
        if tag=='div':
            self.depth-=1
            if self.field=='meta':self.field=None
            if self.depth==0:self.cards.append(self.card);self.card=None
    def handle_data(self,data):
        if self.card is not None and self.field:self.card[self.field]+=data


def parse_cosgo(body,url,stamp,today):
    parser=CosgoParser();parser.feed(body);rows=[]
    for card in parser.cards:
        stamp_match=re.match(r'(20\d{2})\.(\d{2})\.(\d{2})\s+\d{2}:\d{2}',card['meta'])
        if not stamp_match:continue
        day=date(*(int(v) for v in stamp_match.groups()))
        if not 0<=(day-today).days<=365:continue
        city=next((c for c in collect.configured_cities() if c['city_name'] in {'西安市','济南市','天津市'}
                   and card['name'].startswith(c['city_name'].removesuffix('市')+'·')
                   and re.search(c['city_name'].removesuffix('市')+r'\s*·',card['meta'])),None)
        if not city:continue
        # Stable source listing ID; we have not read the primary ticket body.
        match=re.search(r'[?&]id=(\d+)',card['ticket_url'])
        if not match:continue
        source_id='cosgo_bili_'+match[1]
        rows.append({'event_id':'src_'+hashlib.sha256(source_id.encode()).hexdigest()[:12],'source_record_id':source_id,
            'event_name':card['name'],'city_name':city['city_name'],'city_slug':city['city_slug'],'city_match':'text_confirmed',
            'start_at':day.isoformat(),'end_at':day.isoformat(),'sessions':[{'start_at':day.isoformat(),'end_at':day.isoformat()}],
            'event_type':collect.classify_event(card['name']),'event_date_role':'event','date_precision':'day','date_confidence':'secondary_listing',
            'review_status':'pending','event_status':'unknown','first_seen_at':stamp,'last_seen_at':stamp,'source_id':'cosgo-public-calendar',
            'evidence_level':'secondary_listing','primary_body_read':False,'event_detail_url':card['ticket_url'].split('&')[0],
            'source_url':url,'date_evidence':[{'quote':card['meta'],'date_text':stamp_match[0]}],
            'sources':[{'source_url':url,'observed_at':stamp,'checked_at':stamp,'access_status':'secondary_listing_read','verification_status':'unverified'}]})
    return rows


def run(output,today):
    output=safe_output(output);reader=Reader(output);rows=[];routes=[];started=time.monotonic()
    codes={'西安市':29,'济南市':531,'天津市':22}
    for city in collect.configured_cities():
        if city['city_name'] not in codes:continue
        seen=set()
        for page in range(1,7):
            url=f"https://www.showstart.com/event/list?cityCode={codes[city['city_name']]}&pageNo={page}"
            body,check=reader.fetch(url,'public_ticket_index');route={'city':city['city_name'],'page':page,'url':url,'status':check['status']}
            if body:
                try:
                    found=parse_listing(body,city,url,check['checked_at'],today,horizon_days=365)
                    keys={r['event_id'] for r in found};route.update(records=len(found),new_records=len(keys-seen))
                    rows.extend(r for r in found if r['event_id'] not in seen)
                    repeated=bool(keys) and not(keys-seen);seen.update(keys)
                    if repeated:route['stop_reason']='repeated_page'
                except ValueError as exc:route.update(error=str(exc),stop_reason='layout_or_city_mismatch')
            else:route['stop_reason']='access_failed'
            routes.append(route)
            if route.get('stop_reason'):break
    # Independent lawful alternatives. HTML-only/JS shells are reported as
    # such; HTTP 200 does not establish platform search coverage.
    alternatives=[]
    for source,url in [('bilibili-ticket-index','https://show.bilibili.com/platform/home.html'),
                       ('damai-index','https://search.damai.cn/search.htm'),
                       ('cosgo-public-calendar','https://cosgo.cn/conventions/'),
                       ('tianjin-local-acg','https://022acg.com/moe/')]:
        body,check=reader.fetch(url,'alternative_index')
        found=parse_cosgo(body,url,check['checked_at'],today) if body and source=='cosgo-public-calendar' else []
        rows.extend(found)
        alternatives.append({'source_id':source,**check,'body_length':len(body),'records':len(found),
                             'extraction_status':'secondary_listing_read' if found else 'not_adapted' if body else 'unavailable'})
    collect.write_json(output/'events.json',rows)
    collect.write_json(output/'run.json',{'as_of':today.isoformat(),'input_kind':'city_category_indexes_only','benchmark_loaded_by_collector':False,
        'routes':routes,'alternatives':alternatives,'checks':reader.checks,'elapsed_seconds':round(time.monotonic()-started,3),
        'request_count':len(reader.checks),'downloaded_bytes':sum(c.get('bytes',0) for c in reader.checks)})
    print(json.dumps({'events':len(rows),'routes':routes},ensure_ascii=True))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--as-of',type=date.fromisoformat,required=True)
    args=p.parse_args();run(args.output,args.as_of)
