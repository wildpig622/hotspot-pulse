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
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


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


def parse_listing(body: str, city: dict, url: str, checked_at: str, today: date) -> list[dict]:
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
        if day < today or (day - today).days > 90:
            continue
        title = re.sub(r'\s+', ' ', card['title']).strip()
        if re.search(r'取消|延期|待定|暂定|待官宣|拟定|代拍|代抢|转让', title) or CONDITIONAL_EVENT_PATTERN.search(title):
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
            'content_kind': 'event_announcement', 'review_status': 'pending', 'event_status': 'unknown',
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
    with urllib.request.urlopen(request, timeout=15) as response:
        body = response.read(3_000_001)
        if len(body) > 3_000_000:
            raise ValueError('listing_too_large')
        return body.decode(response.headers.get_content_charset() or 'utf-8')


def collect_source_calendar(root: Path, cities: list[dict], checked_at: str, today: date,
                            previous: dict | None = None, transport=None) -> tuple[list[dict], list[dict]]:
    config = json.loads((root / 'config/source-calendars.json').read_text(encoding='utf8'))
    transport = transport or fetch_listing
    by_name = {c['city_name']: c for c in cities}
    routes = [r for r in config['data'] if r['city_name'] in by_name]
    previous_rows = {r['event_id']: r for r in (previous or {}).get('source_candidates', [])}

    def read(route):
        city = by_name[route['city_name']]
        rows, pages, errors = [], [], []
        for page in (1, 2):
            url = 'https://www.showstart.com/event/list?cityCode=' + str(route['city_code']) + '&pageNo=' + str(page) + '&pageSize=20'
            try:
                body = transport(url)
                parsed = parse_listing(body, city, url, checked_at, today)
                rows.extend(parsed)
                pages.append({'url': url, 'status': 'ok', 'dated_records': len(parsed)})
            except Exception as exc:
                errors.append(type(exc).__name__)
                pages.append({'url': url, 'status': 'failed', 'error_type': type(exc).__name__})
        unique = {r['event_id']: r for r in rows}
        status = 'failed' if len(errors) == 2 else 'partial' if errors else 'ok'
        return sorted(unique.values(), key=lambda r: (r['start_at'], r['event_id']))[:config['max_records_per_city']], {
            'city_name': city['city_name'], 'topic': 'concert', 'source_type': 'authorized_ticketing',
            'status': status, 'checked_at': checked_at, 'pages': pages,
            'note': '仅覆盖本平台所列演出；零条不表示没有活动。'}

    rows, checks = {}, []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for found, check in pool.map(read, routes):
            checks.append(check)
            for row in found:
                prior = previous_rows.get(row['event_id'])
                if prior:
                    row['first_seen_at'] = prior.get('first_seen_at') or row['first_seen_at']
                    row['event_status'] = prior.get('event_status', 'unknown')
                    if prior.get('review_status') in {'verified', 'rejected'}:
                        row = copy.deepcopy(prior)
                rows[row['event_id']] = row
    for key, prior in previous_rows.items():
        if key not in rows:
            retained = copy.deepcopy(prior)
            retained['source_presence'] = 'retained_not_refreshed'
            rows[key] = retained
    return sorted(rows.values(), key=lambda r: (r['start_at'], r['city_name'], r['event_id'])), checks
