import copy
import contextlib
import io
import json
import tempfile
from datetime import date
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import collect
from scripts.source_calendar import parse_listing, collect_source_calendar


class SourceCalendarTests(unittest.TestCase):
    city = {'city_name': '洛阳市', 'city_slug': 'luoyang', 'aliases': ['洛阳']}
    day = date(2026, 11, 4)
    stamp = '2026-11-04T06:00:00Z'
    url = 'https://www.showstart.com/event/list?cityCode=379&pageNo=1&pageSize=20'

    def card(self, city='洛阳', day='2026/11/07', title='经典话剧《样本》', key='123'):
        return f'<a class="show-item item" href="/event/{key}"><div class="title">{title}</div><div class="time">时间：{day} 19:30</div><div class="addr"><i></i>[{city}]新区剧院</div></a>'

    def parse(self, body):
        return parse_listing('<div class="show-list">' + body + '</div>', self.city, self.url, self.stamp, self.day)

    def test_date_and_city_come_from_the_same_card_not_navigation_or_other_cards(self):
        body = '<nav>洛阳 2026/11/07</nav>' + self.card(city='北京') + self.card(key='456')
        rows = self.parse(body)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['event_detail_url'], 'https://www.showstart.com/event/456')
        self.assertEqual(rows[0]['start_at'], '2026-11-07')
        self.assertEqual(rows[0]['review_status'], 'pending')
        self.assertEqual(rows[0]['sources'][0]['source_url'], self.url)
        self.assertEqual(rows[0]['sources'][0]['access_status'], 'official_listing_read')
        self.assertNotEqual(rows[0]['sources'][0]['source_url'], rows[0]['event_detail_url'])
        broken = self.card().replace('<div class="time">时间：2026/11/07 19:30</div>', '')
        with self.assertRaises(ValueError): self.parse(broken)
        with self.assertRaises(ValueError): self.parse(self.card(city='北京'))

    def test_scripts_invalid_dates_sales_missing_dates_and_unconfirmed_titles_are_not_events(self):
        script = '<script>' + self.card() + '</script>'
        self.assertEqual(self.parse(script), [])
        for day in ('2026/11/31', '2026/10/31', '2027/03/01', '开票2026/11/07'):
            self.assertEqual(self.parse(self.card(day=day)), [], day)
        for title in ('演出延期', '暂定巡演', '门票代拍', '待官宣活动'):
            self.assertEqual(self.parse(self.card(title=title)), [])
        with self.assertRaises(ValueError):
            parse_listing('<style>.show-list{}</style><p>login</p>', self.city, self.url, self.stamp, self.day)

    def test_duplicate_pages_do_not_inflate_records_and_failure_preserves_real_check_time(self):
        body = '<div class="show-list">' + self.card() * 20 + '</div>'
        rows, checks = collect_source_calendar(collect.ROOT, [self.city], self.stamp, self.day, transport=lambda url: body)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(checks[0]['pages']), 2)
        original = copy.deepcopy(rows[0])
        def offline(url): raise OSError('source down')
        retained, failed = collect_source_calendar(collect.ROOT, [self.city], '2026-11-05T06:00:00Z', self.day, {'source_candidates': rows}, transport=offline)
        self.assertEqual(failed[0]['status'], 'failed')
        self.assertEqual(retained[0]['last_evidence_check_at'], original['last_evidence_check_at'])
        self.assertEqual(retained[0]['source_presence'], 'retained_not_refreshed')

    def test_human_decision_and_first_seen_are_preserved_on_refresh(self):
        body = '<div class="show-list">' + self.card() + '</div>'
        rows, _ = collect_source_calendar(collect.ROOT, [self.city], self.stamp, self.day, transport=lambda url: body)
        rows[0].update(review_status='rejected', event_status='cancelled', scope_note='人工结论')
        refreshed, _ = collect_source_calendar(collect.ROOT, [self.city], '2026-11-05T06:00:00Z', self.day, {'source_candidates': rows}, transport=lambda url: body)
        self.assertEqual(refreshed, rows)
        self.assertFalse(collect.is_upcoming_event(refreshed[0], self.day))

    def test_upcoming_queries_do_not_require_a_year_and_follow_cross_year_months(self):
        from urllib.parse import urlparse, parse_qs
        query = parse_qs(urlparse(collect.build_feed_url(self.city, date(2026, 11, 4), collect.FEED_TOPICS[0], True)).query)['q'][0]
        self.assertIn('(1月 OR 2月 OR 11月 OR 12月)', query)
        self.assertNotIn('(2026 OR 2027)', query)
        self.assertIn('after:2026-10-05', query)

    def test_full_collection_writes_independent_sources_and_both_rss_routes(self):
        from datetime import datetime, timezone
        row = self.parse(self.card())[0]
        with tempfile.TemporaryDirectory() as tmp:
            api = Path(tmp)
            city_file = api/'catalogue.json'
            city_file.write_text(json.dumps([self.city]), encoding='utf8')
            with patch.object(collect, 'SITE_API', api), patch.object(collect, 'CITIES_FILE', city_file), \
                    patch.object(collect, 'configured_cities', return_value=[self.city]), \
                    patch.object(collect, 'now_utc', return_value=datetime(2026,11,4,6,tzinfo=timezone.utc)), \
                    patch.object(collect, 'fetch_feed', return_value=b'<rss><channel/></rss>') as rss, \
                    patch('scripts.source_calendar.collect_source_calendar', return_value=([row], [{'city_name':'洛阳市','status':'ok'}])) as source, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(collect.run_collection(include_sources=True), 0)
            source.assert_called_once()
            self.assertEqual(rss.call_count, 12)
            calendar = json.loads((api/'activities.json').read_text(encoding='utf8'))
            self.assertEqual(calendar['source_candidates'], [row])
            coverage = json.loads((api/'coverage.json').read_text(encoding='utf8'))
            self.assertEqual(next(c for c in coverage['data'] if c['topic']=='concert')['source_candidate_count'], 1)

