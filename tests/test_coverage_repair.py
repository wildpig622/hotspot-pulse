import contextlib
import copy
import io
import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from scripts import collect
from scripts.activity_registry import build_activities, build_coverage, build_registry_payload
from scripts.rebuild_snapshot import rebuild


class CoverageRepairTests(unittest.TestCase):
    def setUp(self):
        self.city = {'city_name': '杭州市', 'city_slug': 'hangzhou', 'aliases': ['杭州']}
        self.now = datetime(2026, 11, 4, 1, tzinfo=timezone.utc)

    def entry(self, **extra):
        return dict({'registry_id': 'one_actual_activity', 'event_name': '杭州音乐会', 'event_type': 'concert',
                     'city_name': '杭州市', 'sessions': [{'start_at': '2026-11-06'}, {'start_at': '2026-11-08'}],
                     'source': {'url': 'https://venue.example/event', 'publisher': '场馆', 'source_type': 'official_venue',
                                'access_status': 'body_read', 'checked_at': '2026-11-03T08:00:00Z'}}, **extra)

    def test_holidays_and_major_conferences_are_admitted_without_confusing_a_tour_name(self):
        self.assertEqual(collect.classify_event('成都中小学秋假放假时间公布'), 'holiday')
        self.assertEqual(collect.classify_event('深圳APEC领导人会议'), 'conference')
        self.assertEqual(collect.classify_event('许佳琪续假期巡回演唱会成都站'), 'concert')
        self.assertEqual(collect.classify_event('杭州话剧'), 'concert')
        self.assertTrue(all(term in collect.KEYWORDS for topic in collect.FEED_TOPICS for term in topic['terms']))
        self.assertEqual(collect.classify_event('深圳高交会'), 'exhibition')
        disputed = collect.build_candidate(self.city, {'title': '杭州秋假时间11月11日—13日定了？相关部门回应', 'url': 'https://news.example/response'}, '2026-11-04T01:00:00Z', self.now.date())
        self.assertFalse(collect.is_upcoming_event(disputed, self.now.date()))
        cancelled = collect.build_candidate(self.city, {'title': '杭州音乐会将于2026年11月11日举行', 'url': 'https://venue.example/show'}, '2026-11-04T01:00:00Z', self.now.date())
        cancelled['event_status'] = 'cancelled'
        self.assertFalse(collect.is_upcoming_event(cancelled, self.now.date()))
        self.assertEqual(collect.classify_content('德阳秋假分批错峰时间公布'), 'schedule_roundup')
        row = collect.build_candidate(self.city, {'title': '杭州中小学秋假放假时间：2026年11月11日至13日',
                                                'url': 'https://education.example/calendar'}, '2026-11-04T01:00:00Z', self.now.date())
        self.assertEqual((row['event_type'], row['start_at'], row['end_at']), ('holiday', '2026-11-11', '2026-11-13'))
        self.assertEqual(row['review_status'], 'pending')

    def test_search_topics_have_separate_quotas_and_years_follow_the_actual_window(self):
        urls = {topic['key']: collect.build_feed_url(self.city, date(2028, 12, 15), topic) for topic in collect.FEED_TOPICS}
        self.assertEqual(set(urls), {'concert', 'exhibition', 'sports', 'festival', 'holiday', 'conference'})
        queries = {key: parse_qs(urlparse(url).query)['q'][0] for key, url in urls.items()}
        self.assertIn('秋假', queries['holiday'])
        self.assertNotIn('马拉松', queries['holiday'])
        self.assertIn('(2028 OR 2029)', queries['concert'])
        self.assertNotIn('2026 OR 2027', queries['concert'])

    def run_pipeline(self, transport):
        with tempfile.TemporaryDirectory() as temp:
            api = Path(temp)
            city_file = api / 'config.json'
            city_file.write_text(json.dumps([self.city]), encoding='utf-8')
            with patch.object(collect, 'SITE_API', api), patch.object(collect, 'CITIES_FILE', city_file), \
                    patch.object(collect, 'configured_cities', return_value=[self.city]), \
                    patch.object(collect, 'now_utc', return_value=self.now), \
                    patch.object(collect, 'fetch_feed', side_effect=transport), contextlib.redirect_stdout(io.StringIO()):
                result = collect.run_collection()
            return result, {p.name: json.loads(p.read_text(encoding='utf-8')) for p in api.glob('*.json') if p.name != 'config.json'}

    def test_many_race_reports_cannot_exhaust_the_concert_feed(self):
        def transport(url):
            query = parse_qs(urlparse(url).query)['q'][0]
            kind, count = ('演唱会', 31) if '演唱会' in query else ('马拉松', 20) if '马拉松' in query else ('', 0)
            items = ''.join(f'<item><title>杭州{kind}{i}将于2026年11月20日举行</title><link>https://example.com/{kind}/{i}</link></item>' for i in range(count))
            return ('<rss><channel>' + items + '</channel></rss>').encode('utf-8')
        result, files = self.run_pipeline(transport)
        self.assertEqual(result, 0)
        rows = files['hotspots.json']['data']
        self.assertEqual(sum(row['event_type'] == 'concert' for row in rows), 31)
        self.assertEqual(sum(row['event_type'] == 'sports' for row in rows), 20)
        self.assertEqual(files['health.json']['successful_feeds'], 6)
        self.assertTrue(all(row['review_status'] == 'pending' for row in rows))

    def test_a_holiday_source_failure_is_visible_even_if_other_topics_succeed(self):
        def transport(url):
            if '秋假' in parse_qs(urlparse(url).query)['q'][0]:
                raise OSError('holiday source unavailable')
            return b'<rss><channel /></rss>'
        result, files = self.run_pipeline(transport)
        self.assertEqual(result, 0)
        self.assertEqual(files['health.json']['status'], 'degraded')
        holiday = next(row for row in files['coverage.json']['data'] if row['topic'] == 'holiday')
        self.assertEqual(holiday['discovery_status'], 'failed')
        self.assertNotEqual(holiday['coverage_status'], 'complete')

    def test_activity_identity_is_not_a_continuous_date_range_and_review_is_preserved(self):
        rows = build_activities([self.entry()], [self.city], [])
        self.assertEqual(len(rows), 1)
        self.assertEqual([row['start_at'] for row in rows[0]['sessions']], ['2026-11-06', '2026-11-08'])
        reviewed = dict(rows[0], review_status='verified', event_status='cancelled', scope_note='人工结论')
        refreshed = build_activities([self.entry(sessions=[{'start_at': '2026-12-01'}])], [self.city], [], [reviewed])
        self.assertEqual(refreshed, [reviewed])
        self.assertEqual(build_activities([], [self.city], [], [reviewed]), [reviewed])
        cancelled = dict(rows[0], event_status='cancelled')
        self.assertEqual(build_activities([self.entry()], [self.city], [], [cancelled])[0]['event_status'], 'cancelled')
        retained = build_activities([], [self.city], [], [cancelled])[0]
        self.assertEqual(retained['event_id'], cancelled['event_id'])
        self.assertEqual(retained['last_evidence_check_at'], cancelled['last_evidence_check_at'])
        self.assertEqual(retained['registry_presence'], 'retained_not_refreshed')

    def test_unread_evidence_invalid_dates_and_conflicting_identities_cannot_supply_calendar_rows(self):
        entry = self.entry()
        entry['source']['access_status'] = 'open_failed'
        with self.assertRaises(ValueError):
            build_activities([entry], [self.city], [])
        with self.assertRaises(ValueError):
            build_activities([self.entry(sessions=[{'start_at': '2026-11-31'}])], [self.city], [])
        with self.assertRaises(ValueError):
            build_activities([self.entry(review_status='verified')], [self.city], [])
        lead = {'event_id': 'lead', 'city_name': '杭州市'}
        with self.assertRaises(ValueError):
            build_activities([self.entry(related_lead_ids=['lead']), self.entry(registry_id='other', related_lead_ids=['lead'])], [self.city], [lead])

    def test_offline_migration_clears_stored_errors_and_does_not_refresh_collection_or_source_times(self):
        snapshot = {'meta': {'generated_at': '2026-10-30T01:55:55Z'}, 'data': [
            {'event_id': 'quantity', 'event_name': '杭州马拉松3.5万人参赛', 'city_name': '杭州市', 'city_slug': 'hangzhou',
             'start_at': '2027-03-05', 'date_precision': 'day', 'review_status': 'pending', 'sources': [{'observed_at': '2026-10-30T01:55:55Z'}]},
        ]}
        before = copy.deepcopy(snapshot)
        outputs, report = rebuild(snapshot, [self.city], {'last_run_at': '2026-10-30T01:55:55Z'}, date(2026, 11, 4), '2026-11-04T01:00:00Z')
        migrated = outputs['hotspots.json']
        self.assertIsNone(migrated['data'][0]['start_at'])
        self.assertEqual(migrated['data'][0]['review_status'], 'pending')
        self.assertEqual(migrated['meta']['last_collection_at'], '2026-10-30T01:55:55Z')
        self.assertEqual(migrated['data'][0]['sources'], before['data'][0]['sources'])
        self.assertEqual(snapshot, before)
        self.assertEqual(report['automatic_verified_promotions'], 0)

    def test_recovered_scope_has_school_batches_concerts_and_conferences_with_honest_coverage(self):
        cities = json.loads(collect.CITIES_FILE.read_text(encoding='utf-8'))
        payload = build_registry_payload(collect.ROOT, [], cities, '2026-11-04T01:00:00Z', date(2026, 11, 4))
        activities = payload['data']
        holidays = [row for row in activities if row['event_type'] == 'holiday']
        self.assertEqual(len([row for row in holidays if row['city_name'] in {'成都市', '德阳市', '遂宁市'}]), 4)
        deyang = [row for row in holidays if row['city_name'] == '德阳市']
        self.assertEqual({row['start_at'] for row in deyang}, {'2026-11-18', '2026-11-25'})
        self.assertTrue(any('林忆莲' in row['event_name'] for row in activities))
        self.assertTrue(any('APEC' in row['event_name'] for row in activities))
        lixia = next(row for row in activities if row['registry_id'] == 'jinan_lixia_school_break_2026')
        self.assertEqual([row['start_at'] for row in lixia['sessions']], ['2026-11-06', '2026-11-09'])
        jackson = next(row for row in activities if row['registry_id'] == 'jackson_wang_nanjing_2026')
        self.assertEqual(len(jackson['sources']), 2)
        signal = payload['source_market_signals'][0]
        self.assertEqual(signal['city_name'], '汉中市')
        self.assertEqual(signal['impact_destination_cities'], ['西安市'])
        self.assertFalse(any(row['city_name'] == '汉中市' for row in activities))
        coverage = build_coverage(cities, list(collect.FEED_TOPICS), [], activities, [], '2026-11-04T01:00:00Z')
        self.assertEqual(len(coverage['data']), 168)
        self.assertTrue(all(row['coverage_status'] != 'complete' for row in coverage['data']))
        self.assertTrue(all(row['review_status'] == 'pending' for row in activities))
