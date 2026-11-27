import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from scripts.business_service import build, merge, validate
from scripts.build_release_candidate import assemble

NOW = datetime(2026, 11, 27, 3, tzinfo=timezone.utc)


def row(**kwargs):
    return dict(event_id='off_existing', event_name='三城会议测试', city_name='西安市', event_type='conference',
                start_at='2027-05-01', end_at='2027-05-02', source_url='https://example.org/notice/1',
                short_evidence=['2027年5月1日至2日'], observed_at='2026-11-27T02:00:00Z', **kwargs)


class PersistenceTests(unittest.TestCase):
    def test_absence_failure_and_duplicate_import_keep_last_good(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = Path(tmp) / 'api/v1'
            api.mkdir(parents=True)
            first = build(api, NOW, [row()])
            second = build(api, NOW + timedelta(hours=1), [row()])
            failed = build(api, NOW + timedelta(days=1), collection_ok=False)
            self.assertEqual(first['state'], second['state'])
            self.assertEqual(second['state'], failed['state'])
            self.assertFalse(failed['focus']['meta']['collection_ok'])
            self.assertEqual(len(failed['calendar']['data']), 1)  # beyond 90, inside 365

    def test_status_without_dates_retains_schedule_and_separate_observed_time(self):
        state = merge(None, [row()], NOW)
        for i, status in enumerate(('announced', 'ticket_on_sale', 'sold_out', 'extra_show', 'postponed', 'cancelled')):
            followup = row()
            followup.pop('start_at'); followup.pop('end_at')
            followup.update(observation_type=status, observed_at='2026-11-27T02:%02d:00Z' % (i+1))
            state = merge(state, [followup], NOW)
        self.assertEqual(state['events']['off_existing']['start_at'], '2027-05-01')
        self.assertEqual(state['events']['off_existing']['event_status'], 'cancelled')
        self.assertEqual(len(state['observations']), 7)
        self.assertEqual(len({o['observed_at'] for o in state['observations']}), 7)

    def test_canonical_identity_human_review_and_out_of_order(self):
        state = merge(None, [row()], NOW, {'membership': {'off_existing': 'hp_stable'}})
        state['events']['hp_stable']['review_status'] = 'verified'
        changed = row(); changed.update(start_at='2027-06-01', end_at='2027-06-02', observed_at='2026-11-27T02:01:00Z')
        result = merge(state, [changed], NOW, {'membership': {'off_existing': 'hp_stable'}})
        self.assertEqual(result['events']['hp_stable']['start_at'], '2027-05-01')
        self.assertEqual(result['events']['hp_stable']['review_status'], 'verified')
        result = merge(result, [row()], NOW, {'membership': {'off_existing': 'hp_stable'}})
        self.assertEqual(result['events']['hp_stable']['last_observed_at'], changed['observed_at'])
        changed['city_name'] = '天津市'
        with self.assertRaisesRegex(ValueError, 'city_conflict'):
            merge(result, [changed], NOW, {'membership': {'off_existing': 'hp_stable'}})

    def test_conflicting_dates_are_held_out_of_calendar(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = Path(tmp) / 'api/v1'; api.mkdir(parents=True)
            build(api, NOW, [row()])
            changed = row(); changed.update(start_at='2027-06-01', end_at='2027-06-02', observed_at='2026-11-27T02:01:00Z')
            result = build(api, NOW, [changed])
            self.assertEqual(result['calendar']['data'], [])
            self.assertTrue(result['intelligence']['data'][0]['date_review_required'])

    def test_import_cannot_upgrade_review_include_contacts_or_infer_local_scope(self):
        for patch in ({'review_status': 'verified'}, {'short_evidence': ['contact@example.org']},
                      {'short_evidence': ['<b>contact</b>&#64;<i>example.org</i>']},
                      {'scope_level': 'national'}, {'observed_at': '2026-11-27T02:00:00'},
                      {'source_url': 'http://example.org/notice'}, {'end_at': '2026-01-01'}):
            candidate = row(); candidate.update(patch)
            with self.assertRaises((ValueError, KeyError)):
                validate(candidate)

    def test_invalid_batch_is_atomic_and_v1_v2_bytes_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = Path(tmp) / 'api/v1'; api.mkdir(parents=True)
            (api / 'activities.json').write_text('{"official_candidates": []}')
            before = (api / 'activities.json').read_bytes()
            build(api, NOW, [row()])
            saved = (api.parent / 'business/state.json').read_bytes()
            bad = row(); bad['review_status'] = 'verified'
            with self.assertRaises(ValueError):
                build(api, NOW, [row(), bad])
            self.assertEqual(saved, (api.parent / 'business/state.json').read_bytes())
            self.assertEqual(before, (api / 'activities.json').read_bytes())

    def test_auto_official_adapter_and_human_v2_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = Path(tmp) / 'api/v1'; api.mkdir(parents=True)
            candidate = row(); candidate.pop('observed_at'); candidate['checked_at'] = '2026-11-27T02:00:00Z'
            (api / 'activities.json').write_text(json.dumps({'official_candidates': [candidate]}))
            result = build(api, NOW)
            self.assertEqual(result['status']['event_count'], 1)
            v2 = api.parent / 'v2'; v2.mkdir()
            (v2 / 'events.json').write_text(json.dumps({'data': [{'event_id': 'off_existing', 'review_status': 'rejected'}]}))
            result = build(api, NOW)
            self.assertEqual(result['focus']['data'], [])
            self.assertEqual(result['state']['events']['off_existing']['review_status'], 'rejected')

    def test_release_builder_refuses_production_or_non_review_output(self):
        with self.assertRaisesRegex(ValueError, 'review_subdirectory'):
            assemble(Path(__file__).resolve().parents[1] / 'site')

    def test_new_v2_human_decision_protects_venue_and_sessions_before_refresh(self):
        state = merge(None, [row()], NOW)
        approved = dict(event_id='off_existing', review_status='verified', venue_name='人工确认会场',
                        sessions=[{'start_at': '2027-05-01', 'end_at': '2027-05-01'}], event_type='conference')
        incoming = row(); incoming.update(venue_name='自动新地点', sessions=['2027-05-02'], observed_at='2026-11-27T02:02:00Z')
        result = merge(state, [incoming], NOW, v2_events={'data': [approved]})
        self.assertEqual(result['events']['off_existing']['venue_name'], approved['venue_name'])
        self.assertEqual(result['events']['off_existing']['sessions'], approved['sessions'])
