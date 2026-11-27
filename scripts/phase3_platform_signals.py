"""Keep public social search assertions as signals, not verified bookings."""
import hashlib
import re
from . import collect

SIGNAL=re.compile(r'待官宣|定档|开票|售罄|加场|应援|冬聚|快闪|想去|歌迷会|聚集|聚会|人挤人')


def extract_signals(payload,stamp):
    rows=[]
    # Bilibili returned concrete public BV links. Web fallback snippets and
    # anonymous reposts are not promoted to events by relevance scores.
    for item in payload.get('bilibili',[]):
        text=item.get('title','')+'\n'+item.get('description','')
        if not SIGNAL.search(text):continue
        url=item.get('url','')
        if not re.fullmatch(r'https://www\.bilibili\.com/video/BV[\w]+/?',url):continue
        cities=[c for c in collect.configured_cities() if any(a in text for a in c['aliases'])]
        city=cities[0] if len(cities)==1 and cities[0]['city_name'] in {'西安市','济南市','天津市'} else None
        status='extra_show' if re.search(r'(?:确认|宣布|官宣|确定).*加场|加场(?:确定|官宣)',text) else 'sold_out' if re.search(r'已售罄|全部售罄|售罄了',text) else 'ticket_on_sale' if '开票' in text else 'announced'
        digest=hashlib.sha256(url.encode()).hexdigest()[:12]
        rows.append({'event_id':'sig_'+digest,'source_record_id':url,'source_id':'bilibili-search','event_name':item['title'],
            'source_url':url,'source_text':text,'city_name':city['city_name'] if city else None,'city_slug':city['city_slug'] if city else None,
            'city_match':'post_text_only' if city else 'not_established','scope_level':'city_signal' if city else 'multi_city_or_unknown',
            'mentioned_cities':[c['city_name'] for c in cities],
            'local_demand_confirmed':False,'event_type':collect.classify_event(item['title']),
            'signal_kind':'market_signal' if re.search(r'应援|歌迷会|聚集|人挤人|想去',text) else 'unscheduled',
            'observation_type':status,'source_published_date':item.get('date'),'source_published_at':None,
            'first_seen_at':stamp,'last_seen_at':stamp,'start_at':None,'end_at':None,'sessions':[],
            'event_date_role':'unknown','date_evidence':[{'quote':text,'role':'unresolved_social_assertion'}],'review_status':'pending','event_status':'unknown',
            'evidence_level':'public_social_search_result','body_read':False,
            'persistence_status':'not_established',
            'signal_note':'公开视频标题/描述中的主张，发布日期不是活动日；未核实主办方、年份、活动状态和住宿影响。'})
    return rows
