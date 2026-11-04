import copy
import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts import collect
from scripts.activity_registry import build_discovery_candidates, build_registry_payload
from scripts.rebuild_snapshot import rebuild
from scripts.check_snapshot_quality import check_snapshot


class CityDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.city = next(c for c in collect.configured_cities() if c['city_name'] == '重庆市')
        self.day = date(2026, 11, 4)
        self.stamp = '2026-11-04T03:40:00Z'

    def lead(self, **extra):
        row = collect.build_candidate(self.city, {'title': '重庆音乐会将于2026年11月20日举行',
                                                'url': 'https://news.example/chongqing'}, self.stamp, self.day)
        row.update(extra)
        return row

    def test_unregistered_city_flows_to_calendar_without_altering_news_or_inventing_evidence(self):
        row = self.lead()
        original = copy.deepcopy(row)
        payload = build_registry_payload(collect.ROOT, [row], [self.city], self.stamp, self.day)
        candidates = payload['discovery_candidates']
        self.assertEqual([c['event_id'] for c in candidates], [row['event_id']])
        self.assertEqual(candidates[0]['review_status'], 'pending')
        self.assertEqual(candidates[0]['evidence_level'], 'title_or_rss_summary')
        self.assertNotIn('last_evidence_check_at', candidates[0])
        self.assertEqual(candidates[0]['sources'], row['sources'])
        self.assertEqual(row, original)

    def test_dates_roles_city_review_and_internal_meetings_are_not_promoted(self):
        bad = [dict(event_date_role='ambiguous'), dict(event_date_role='ticket_sale'),
               dict(event_date_role='registration'), dict(date_precision='month'),
               dict(city_match='query_only'), dict(city_match='event_city_conflict'),
               dict(review_status='rejected'), dict(review_status='verified'),
               dict(event_status='cancelled'), dict(event_status='postponed'),
               dict(event_name='重庆演唱会暂定2026年11月20日'),
               dict(event_name='重庆公司将于2026年11月20日举行股东大会'),
               dict(start_at='2026-11-31'), dict(end_at='2026-11-01'),
               dict(content_kind='schedule_roundup'), dict(content_kind='past_report')]
        for extra in bad:
            with self.subTest(extra=extra):
                self.assertEqual(build_discovery_candidates([self.lead(**extra)], []), [])
        # Date-window filtering is a display concern; retained dates can age.
        self.assertEqual(len(build_discovery_candidates([self.lead(start_at='2026-10-20')], [])), 1)

    def test_only_explicit_links_remove_duplicate_news_from_calendar_projection(self):
        first = self.lead(event_id='a')
        second = self.lead(event_id='b')
        activities = [{'event_id': 'act_one', 'related_lead_ids': ['a']}]
        self.assertEqual([r['event_id'] for r in build_discovery_candidates([first, second], activities)], ['b'])

    def test_release_gate_detects_a_dropped_city_even_when_all_168_requests_succeeded(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = Path(tmp)
            snapshot = json.loads((collect.SITE_API / 'hotspots.json').read_text(encoding='utf8'))
            snapshot['data'].append(self.lead(event_id='regression_chongqing'))
            health = json.loads((collect.SITE_API / 'health.json').read_text(encoding='utf8'))
            cities = collect.configured_cities()
            outputs, _ = rebuild(snapshot, cities, health, self.day, self.stamp)
            for name, payload in outputs.items():
                collect.write_json(api / name, payload)
            self.assertEqual(check_snapshot(api, require_discovery_calendar=True)['status'], 'PASS')
            path = api / 'activities.json'
            calendar = outputs['activities.json']
            calendar['discovery_candidates'] = [r for r in calendar['discovery_candidates'] if r['event_id'] != 'regression_chongqing']
            calendar['meta']['discovery_candidate_count'] -= 1
            collect.write_json(path, calendar)
            result = check_snapshot(api, require_discovery_calendar=True)
            self.assertEqual(result['status'], 'FAIL')
            self.assertTrue(any('handoff' in error for error in result['errors']))

