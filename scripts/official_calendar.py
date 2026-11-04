"""Poll existing primary source URLs and consume only explicit Event JSON-LD dates."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from html.parser import HTMLParser
try:
    from .source_calendar import fetch_listing
except ImportError:
    from source_calendar import fetch_listing


class StructuredParser(HTMLParser):
    def __init__(self):super().__init__();self.active=False;self.parts=[];self.blocks=[]
    def handle_starttag(self,tag,attrs):
        if tag=='script' and dict(attrs).get('type')=='application/ld+json':self.active=True;self.parts=[]
    def handle_data(self,data):
        if self.active:self.parts.append(data)
    def handle_endtag(self,tag):
        if tag=='script' and self.active:
            try:self.blocks.append(json.loads(''.join(self.parts)))
            except ValueError:pass
            self.active=False


def parse_events(body, source, cities, checked_at, today):
    parser=StructuredParser();parser.feed(body)
    stack=list(parser.blocks);found=[]
    while stack:
        obj=stack.pop()
        if isinstance(obj,list):stack.extend(obj);continue
        if not isinstance(obj,dict):continue
        stack.extend(obj.get('@graph',[]))
        typ=obj.get('@type',[]);typ=[typ] if isinstance(typ,str) else typ
        if not any(t in {'Event','MusicEvent','BusinessEvent','SportsEvent','ExhibitionEvent','Festival','TheaterEvent'} for t in typ):continue
        location=obj.get('location',{})
        if not isinstance(location,dict):continue
        address=location.get('address',{})
        locality=address.get('addressLocality','') if isinstance(address,dict) else str(address)
        city=next((c for c in cities if any(a and a in locality for a in c.get('aliases',[]))),None)
        if not city:continue
        try:
            start=date.fromisoformat(str(obj.get('startDate',''))[:10]);end=date.fromisoformat(str(obj.get('endDate') or obj.get('startDate'))[:10])
            if end<start or end<today or (start-today).days>90:continue
        except ValueError:continue
        name=obj.get('name');venue=location.get('name')
        if not isinstance(name,str) or not name or not isinstance(venue,str) or not venue:continue
        identity=str(obj.get('@id') or obj.get('url') or source['url']+'#'+name+'|'+city['city_name'])
        status=str(obj.get('eventStatus',''))
        event_status='cancelled' if status.endswith('EventCancelled') else 'postponed' if status.endswith('EventPostponed') else 'unknown'
        found.append({'event_id':'off_'+hashlib.sha256(identity.encode()).hexdigest()[:12],
                      'record_kind':'official_candidate','evidence_level':'structured_official','date_confidence':'structured_official',
                      'event_name':name,'city_name':city['city_name'],'city_slug':city['city_slug'],'city_match':'text_confirmed',
                      'event_type':'sports' if 'SportsEvent' in typ else 'exhibition' if 'ExhibitionEvent' in typ else 'festival' if 'Festival' in typ else 'conference' if 'BusinessEvent' in typ else 'concert',
                      'venue_name':venue,'start_at':start.isoformat(),'end_at':end.isoformat(),'sessions':[{'start_at':start.isoformat(),'end_at':end.isoformat()}],
                      'date_precision':'day','event_date_role':'event','content_kind':'event_announcement','review_status':'pending','event_status':event_status,
                      'first_seen_at':checked_at,'last_seen_at':checked_at,'last_evidence_check_at':checked_at,
                      'scope_note':'来源页面结构化Event数据，仍待核验；不由文章发布日期或全文任意日期推断活动日期。',
                      'sources':[{'source_url':source['url'],'publisher':source['publisher'],'source_type':source['source_type'],
                                  'checked_at':checked_at,'observed_at':checked_at,'access_status':'body_read','verification_status':'unverified'}], 'source_count':1})
    return found


def collect_official_calendar(root,cities,checked_at,today,previous=None,transport=None):
    transport=transport or fetch_listing
    registry=json.loads((root/'config/activity-registry.json').read_text(encoding='utf8'))
    accepted={'government_portal','government_department','official_event_organizer','official_venue','official_association','official_event_sponsor','government_official_account'}
    sources={s['url']:s for s in registry['sources'].values() if s['source_type'] in accepted}
    def read(source):
        try:
            rows=parse_events(transport(source['url']),source,cities,checked_at,today)
            return rows,{'url':source['url'],'source_type':source['source_type'],'checked_at':checked_at,'status':'ok','structured_events':len(rows),
                         'note':'读取页面不等于重新核验历史登记日期；无Event结构时不自动从全文猜日期。'}
        except Exception as exc:return [],{'url':source['url'],'source_type':source['source_type'],'checked_at':checked_at,'status':'failed','error_type':type(exc).__name__}
    rows={};checks=[];old={r['event_id']:r for r in (previous or {}).get('official_candidates',[])}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for found,check in pool.map(read,sources.values()):
            checks.append(check)
            for row in found:
                prior=old.get(row['event_id'])
                if prior:
                    row['first_seen_at']=prior['first_seen_at']
                    if prior.get('review_status') in {'verified','rejected'}:row=prior
                rows[row['event_id']]=row
    for key,row in old.items():
        if key not in rows:rows[key]=dict(row,source_presence='retained_not_refreshed')
    return sorted(rows.values(),key=lambda r:r['event_id']),checks
