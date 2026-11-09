"""Collect dated, city-specific public ticketing listings independently of RSS.

Only rendered listing cards supply dates. Navigation cities, scripts, sales
times and neighbouring cards cannot supply an event's city/date. No JS runs.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import urllib.request
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
try:
    from .monitoring_window import window_end
except ImportError:
    from monitoring_window import window_end


class ListingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cards = []
        self.card = None
        self.field = None
        self.depth = 0
        self.suppressed = 0
        self.listing_seen = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {'script', 'style'}:
            self.suppressed += 1
        if self.suppressed:
            return
        if tag == 'div' and 'show-list' in attrs.get('class', '').split():
            self.listing_seen = True
        if tag == 'a' and 'show-item' in attrs.get('class', '').split():
            href = attrs.get('href', '')
            self.card = {'href': href, 'title': '', 'time': '', 'addr': ''} if re.fullmatch(r'/event/\d+', href) else None
            self.field = None
            self.depth = 0
        if self.card is not None and tag == 'div':
            if self.field:
                self.depth += 1
            else:
                field = next((f for f in ('title', 'time', 'addr') if f in attrs.get('class', '').split()), None)
                if field:
                    self.field, self.depth = field, 1

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.suppressed = max(0, self.suppressed - 1)
        if self.suppressed:
            return
        if tag == 'div' and self.field:
            self.depth -= 1
            if not self.depth:
                self.field = None
        if tag == 'a' and self.card is not None:
            self.cards.append(self.card)
            self.card, self.field = None, None

    def handle_data(self, value):
        if not self.suppressed and self.card is not None and self.field:
            self.card[self.field] += value


def parse_listing(body: str, city: dict, url: str, checked_at: str, today: date, include_status_changes=False) -> list[dict]:
    try:
        from .collect import classify_event, assess_event_city, CONDITIONAL_EVENT_PATTERN
    except ImportError:
        from collect import classify_event, assess_event_city, CONDITIONAL_EVENT_PATTERN
    parser = ListingParser()
    parser.feed(body)
    # A successful HTTP response can be a login page, bot check or changed layout.
    if not parser.listing_seen:
        raise ValueError('listing_layout_unrecognized')
    result = []
    aliases = set(city.get('aliases', [])) | {city['city_name'], city['city_name'].removesuffix('市')}
    if parser.cards and not any(card['title'].strip() and card['time'].strip() and card['addr'].strip() for card in parser.cards):
        raise ValueError('listing_fields_missing')
    if parser.cards and not any(re.search(r'\[([^\]]+)\]', card['addr']) and re.search(r'\[([^\]]+)\]', card['addr'])[1] in aliases for card in parser.cards):
        raise ValueError('listing_city_route_mismatch')
    for card in parser.cards:
        location = re.fullmatch(r'\s*\[([^\]]+)\]\s*(.+)', card['addr'])
        stamp = re.fullmatch(r'\s*时间[：:]\s*(20\d{2})/(\d{2})/(\d{2})\s+\d{2}:\d{2}\s*', card['time'])
        if not location or location[1] not in aliases or not stamp or not card['title'].strip():
            continue
        try:
            day = date(int(stamp[1]), int(stamp[2]), int(stamp[3]))
        except ValueError:
            continue
        if (day < today and not include_status_changes) or day > window_end(today):
            continue
        title = re.sub(r'\s+', ' ', card['title']).strip()
        status = 'cancelled' if re.search(r'活动(?:已)?取消|演出(?:已)?取消|取消演出',title) else 'postponed' if re.search(r'延期|推迟',title) else 'unknown'
        if re.search(r'待定|暂定|待官宣|拟定|代拍|代抢|转让', title) or CONDITIONAL_EVENT_PATTERN.search(title) or (not include_status_changes and re.search(r'取消|延期',title)):
            continue
        if assess_event_city(city, title, city['city_name'] + ' ' + location[2]) == 'event_city_conflict':
            continue
        kind = classify_event(title)
        kind = kind if kind in {'sports', 'exhibition', 'festival', 'concert'} else 'concert'
        key = 'showstart_' + card['href'].rsplit('/', 1)[1]
        result.append({
            'event_id': 'src_' + hashlib.sha256(key.encode()).hexdigest()[:12], 'source_record_id': key,
            'record_kind': 'source_candidate', 'evidence_level': 'ticketing_listing',
            'event_name': title, 'event_type': kind,
            'city_name': city['city_name'], 'city_slug': city['city_slug'], 'city_match': 'text_confirmed',
            'venue_name': location[2].strip(), 'start_at': day.isoformat(), 'end_at': day.isoformat(),
            'discovery_summary': city['city_name'] + ' ' + location[2].strip(),
            'source_context': {'city_label': location[1], 'title': title, 'start_at': day.isoformat(), 'venue_name': location[2].strip()},
            'date_precision': 'day', 'date_confidence': 'source_listing', 'event_date_role': 'event',
            'sessions': [{'start_at': day.isoformat(), 'end_at': day.isoformat()}],
            'content_kind': 'event_announcement', 'review_status': 'pending', 'event_status': status,
            'event_confirmation': 'unknown', 'first_seen_at': checked_at, 'last_seen_at': checked_at,
            'knowable_at': checked_at, 'last_evidence_check_at': checked_at,
            'scope_note': '票务列表明确列出的场次开始日；尚未读取详情或主办方公告，可能与其他来源重复；规模及住宿影响未知。',
            'source_count': 1, 'event_detail_url': 'https://www.showstart.com' + card['href'],
            'sources': [{'source_url': url, 'publisher': '秀动公开演出列表', 'source_type': 'authorized_ticketing',
                         'checked_at': checked_at, 'observed_at': checked_at, 'last_observed_at': checked_at,
                         'access_status': 'official_listing_read', 'verification_status': 'unverified',
                         'authority_note': '城市、名称、日期从同一活动卡片读取；详情链接仅供补查，未声称读取详情。'}],
        })
    return result


def fetch_listing(url: str) -> str:
    request = urllib.request.Request(url, headers={'User-Agent': 'HotspotPulse/0.1 public calendar discovery', 'Accept-Encoding': 'identity'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                body = response.read(3_000_001)
                if len(body) > 3_000_000: raise ValueError('listing_too_large')
                return body.decode(response.headers.get_content_charset() or 'utf-8')
        except (OSError, TimeoutError):
            if attempt == 2: raise
            time.sleep(0.3 * (attempt+1))


def collect_source_calendar(root: Path, cities: list[dict], checked_at: str, today: date,
                            previous: dict | None = None, transport=None) -> tuple[list[dict], list[dict]]:
    config = json.loads((root / 'config/source-calendars.json').read_text(encoding='utf8'))
    transport = transport or fetch_listing
    by_name = {c['city_name']: c for c in cities}
    routes = [r for r in config['data'] if r['city_name'] in by_name]
    previous_rows = {r['event_id']: r for r in (previous or {}).get('source_candidates', [])}

    def read(route):
        city = by_name[route['city_name']]
        rows, pages, errors, seen_pages = [], [], [], set()
        stop = 'page_limit'
        for page in range(1, config.get('max_pages', 2)+1):
            url = 'https://www.showstart.com/event/list?cityCode=' + str(route['city_code']) + '&pageNo=' + str(page) + '&pageSize=' + str(config.get('page_size',20))
            try:
                body = transport(url)
                parsed = parse_listing(body, city, url, checked_at, today, include_status_changes=True)
                parsed = [r for r in parsed if r['start_at'] >= today.isoformat() or r['event_id'] in previous_rows]
                rows.extend(parsed)
                pages.append({'url': url, 'status': 'ok', 'dated_records': len(parsed)})
                parser=ListingParser();parser.feed(body)
                fingerprint=tuple(c['href'] for c in parser.cards)
                if not fingerprint: stop='exhausted';break
                if fingerprint in seen_pages: stop='repeated_page';break
                seen_pages.add(fingerprint)
                if len(parser.cards) < config.get('page_size',20): stop='exhausted';break
                if len({r['event_id'] for r in rows}) >= config['max_records_per_city']: stop='record_limit';break
            except Exception as exc:
                errors.append(type(exc).__name__)
                pages.append({'url': url, 'status': 'failed', 'error_type': type(exc).__name__})
                stop='read_failed';break
        unique = {r['event_id']: r for r in rows}
        status = 'failed' if errors and not rows else 'partial' if errors else 'ok'
        return sorted(unique.values(), key=lambda r: (r['start_at'], r['event_id']))[:config['max_records_per_city']], {
            'city_name': city['city_name'], 'topic': 'concert', 'source_type': 'authorized_ticketing',
            'status': status, 'checked_at': checked_at, 'pages': pages,
            'pagination': {'stop_reason':stop,'complete':stop=='exhausted','page_limit':config.get('max_pages',2),'record_limit':config['max_records_per_city']},
            'note': '仅覆盖本平台所列演出；零条不表示没有活动。'}

    rows, checks = {}, []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for found, check in pool.map(read, routes):
            checks.append(check)
            for row in found:
                prior = previous_rows.get(row['event_id'])
                if prior:
                    observed_status = row.get('event_status','unknown')
                    row['first_seen_at'] = prior.get('first_seen_at') or row['first_seen_at']
                    row['event_status'] = prior.get('event_status', 'unknown')
                    if observed_status in {'cancelled','postponed'}: row['event_status']=observed_status
                    if row.get('start_at') != prior.get('start_at') or row.get('end_at') != prior.get('end_at'):
                        row['date_changes'] = prior.get('date_changes',[])+[{'checked_at':checked_at,'before':{'start_at':prior.get('start_at'),'end_at':prior.get('end_at')},'after':{'start_at':row.get('start_at'),'end_at':row.get('end_at')}}]
                    else: row['date_changes']=prior.get('date_changes',[])
                    if prior.get('last_detail_check_at'):row['last_detail_check_at']=prior['last_detail_check_at']
                    for field in ('detail_observation','date_review_required'):
                        if field in prior:row[field]=copy.deepcopy(prior[field])
                    current_urls={s['source_url'] for s in row['sources']}
                    row['sources'] += [copy.deepcopy(s) for s in prior.get('sources',[]) if s.get('source_url') not in current_urls]
                    row['source_count']=len(row['sources'])
                    if prior.get('review_status') in {'verified', 'rejected'}:
                        row = copy.deepcopy(prior)
                rows[row['event_id']] = row
    for key, prior in previous_rows.items():
        if key not in rows:
            retained = copy.deepcopy(prior)
            retained['source_presence'] = 'retained_not_refreshed'
            rows[key] = retained
    return sorted(rows.values(), key=lambda r: (r['start_at'], r['city_name'], r['event_id'])), checks


class DetailParser(HTMLParser):
    def __init__(self):
        super().__init__();self.depth=0;self.title_depth=0;self.parts=[];self.title=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='div':
            if self.depth:self.depth+=1
            elif 'describe' in attrs.get('class','').split():self.depth=1
            if self.depth and 'title' in attrs.get('class','').split():self.title_depth=self.depth
    def handle_endtag(self,tag):
        if tag=='div' and self.depth:
            if self.title_depth==self.depth:self.title_depth=0
            self.depth-=1
    def handle_data(self,value):
        if self.depth:
            self.parts.append(value)
            if self.title_depth:self.title.append(value)


def inspect_detail(body, row):
    parser=DetailParser();parser.feed(body)
    title=''.join(parser.title).strip();text=' '.join(parser.parts)
    if not title or not parser.parts:raise ValueError('detail_header_unrecognized')
    norm=lambda s:re.sub(r'[\W_]+','',s).lower()
    if norm(title)!=norm(row['event_name']):raise ValueError('detail_identity_changed')
    # Conditional refund language is not an observed cancellation/postponement.
    clauses=[s for s in re.split(r'[。！？；\n]',text) if not re.search(r'如果|如遇|若|可能|一旦|如因|如演出|如活动|未取消|不取消|未延期|不延期',s)]
    status_text='。'.join(clauses)
    status='cancelled' if re.search(r'活动(?:已)?取消|演出(?:已)?取消|取消演出',status_text) else 'postponed' if re.search(r'演出(?:已)?延期|活动(?:已)?延期|演出(?:已)?推迟',status_text) else None
    match=re.search(r'演出时间[：:]\s*([^\n]{1,100}?)(?=场地[：:]|地址[：:]|$)',text)
    date_text=match[1].strip() if match else None
    # Missing year in the detail cannot silently overwrite the list's explicit year.
    first=re.search(r'(\d{1,2})月(\d{1,2})日',date_text or '')
    conflict=bool(first and f'{int(first[1]):02d}-{int(first[2]):02d}'!=row['start_at'][5:])
    return {'event_status':status,'date_text':date_text,'date_review_required':conflict}


def refresh_details(rows, checked_at, today, limit=40, transport=None):
    transport=transport or fetch_listing
    eligible=[r for r in rows if r.get('review_status')=='pending' and r['start_at']>=today.isoformat()
              and (date.fromisoformat(r['start_at'])-today).days<=14]
    eligible.sort(key=lambda r:(r.get('last_detail_check_at') or '',r['start_at'],r['event_id']))
    def read(row):
        url=row.get('event_detail_url')
        try:return row,inspect_detail(transport(url),row),None
        except Exception as exc:return row,None,type(exc).__name__
    checks=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for row,observation,error in pool.map(read,eligible[:limit]):
            check={'event_id':row['event_id'],'url':row['event_detail_url'],'checked_at':checked_at,'status':'failed' if error else 'ok'}
            if error:check['error_type']=error
            else:
                row['last_detail_check_at']=checked_at
                row['detail_observation']=observation
                if observation['event_status']:row['event_status']=observation['event_status']
                row['date_review_required']=observation['date_review_required']
                row['sources']=[s for s in row['sources'] if s.get('source_url')!=row['event_detail_url']]+[{
                    'source_url':row['event_detail_url'],'publisher':'秀动演出详情','source_type':'authorized_ticketing',
                    'checked_at':checked_at,'observed_at':checked_at,'access_status':'body_read','verification_status':'unverified',
                    'authority_note':'只从当前活动页头读取状态和月日；缺少年份的详情日期不覆盖列表年份。'}]
                row['source_count']=len(row['sources'])
            checks.append(check)
    return checks
