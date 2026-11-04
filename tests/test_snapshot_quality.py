import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts import collect
from scripts.check_snapshot_quality import check_snapshot


class SnapshotQualityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.api = Path(temp.name)
        for name in ('hotspots', 'activities', 'coverage', 'cities', 'health'):
            shutil.copy2(collect.SITE_API / (name + '.json'), self.api / (name + '.json'))

    def test_complete_scan_checks_the_last_activity_and_its_sources(self):
        self.assertEqual(check_snapshot(self.api)['status'], 'PASS')
        path = self.api / 'activities.json'
        payload = json.loads(path.read_text(encoding='utf-8'))
        payload['data'][-1]['sources'] = []
        path.write_text(json.dumps(payload), encoding='utf-8')
        result = check_snapshot(self.api)
        self.assertEqual(result['status'], 'FAIL')
        self.assertTrue(any('no readable source evidence' in error for error in result['errors']))

    def test_duplicate_query_route_cannot_pass_with_an_inflated_success_count(self):
        path = self.api / 'health.json'
        health = json.loads(path.read_text(encoding='utf-8'))
        feeds = [{'city_name': city['city_name'], 'topic': topic['key'], 'status': 'ok'}
                 for city in collect.configured_cities() for topic in collect.FEED_TOPICS]
        feeds[-1] = feeds[0].copy()
        health.update(feed_results=feeds, successful_feeds=168, failed_feeds=0)
        path.write_text(json.dumps(health), encoding='utf-8')
        self.assertEqual(check_snapshot(self.api, require_full_scope=True)['status'], 'FAIL')

    def test_fresh_file_generation_cannot_make_old_collection_deployable(self):
        path = self.api / 'hotspots.json'
        payload = json.loads(path.read_text(encoding='utf-8'))
        payload['meta'].update(generated_at=collect.iso_utc(collect.now_utc()), last_collection_at='2020-01-01T00:00:00Z')
        path.write_text(json.dumps(payload), encoding='utf-8')
        result = check_snapshot(self.api, max_age_hours=24)
        self.assertEqual(result['status'], 'FAIL')
        self.assertTrue(any('stale' in error for error in result['errors']))
