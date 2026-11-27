import hashlib
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from scripts.business_service import ROOT, build, stamp
from scripts.refresh_service import run
from scripts.prepare_rollback import prepare, api_hashes


class RC1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT/'review').mkdir(exist_ok=True)
        cls.batch = json.loads((ROOT/'config/business-seed.json').read_text(encoding='utf8'))
        cls.now = max(stamp(r['observed_at']) for r in cls.batch['data']) + timedelta(minutes=1)
        cls.identities = {r['event_id'] for r in cls.batch['data']}

    def test_bootstrap_once_and_hold_records_without_removing_any_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = Path(tmp)/'api/v1'; api.mkdir(parents=True)
            first = build(api, self.now, bootstrap=True)
            self.assertEqual(set(first['state']['events']), self.identities)
            self.assertTrue(first['focus']['data'])
            held = {'p4_nj_tianjin','p4_industry_jinan','p4_xidian_exam'}
            self.assertTrue(held <= {r['event_id'] for r in first['intelligence']['data']})
            self.assertFalse(held & {r['event_id'] for r in first['calendar']['data']})
            state_path=api.parent/'business/state.json'
            saved=json.loads(state_path.read_text(encoding='utf8'))
            saved['events']['p4_naying_xian'].update(review_status='verified',venue_name='人工确认会场')
            state_path.write_text(json.dumps(saved),encoding='utf8')
            second=build(api,self.now+timedelta(hours=1),collection_ok=False,bootstrap=True)
            self.assertFalse(second['status']['meta']['bootstrap_applied_this_build'])
            self.assertEqual(len(second['state']['observations']),len(first['state']['observations']))
            self.assertEqual(second['state']['events']['p4_naying_xian']['venue_name'],'人工确认会场')
            self.assertEqual(second['state']['events']['p4_naying_xian']['review_status'],'verified')

    def test_first_refresh_failure_still_bootstraps_without_replacing_last_good_v1(self):
        from scripts.collect import write_json
        with tempfile.TemporaryDirectory() as tmp:
            api=Path(tmp)/'api/v1';api.mkdir(parents=True)
            stamp_text=(self.now-timedelta(hours=1)).isoformat()
            write_json(api/'hotspots.json',{'meta':{'last_collection_at':stamp_text},'data':[]})
            write_json(api/'activities.json',{'data':[],'meta':{'last_good_marker':True}})
            write_json(api/'health.json',{'status':'healthy','last_successful_collection_at':stamp_text})
            before=(api/'activities.json').read_bytes()
            result=run(api,collector=lambda **kwargs:1,now=self.now)
            self.assertFalse(result['collection_ok'])
            self.assertEqual(before,(api/'activities.json').read_bytes())
            state=json.loads((api.parent/'business/state.json').read_text(encoding='utf8'))
            self.assertEqual(set(state['events']),self.identities)
            focus=json.loads((api.parent/'business/focus.json').read_text(encoding='utf8'))
            self.assertFalse(focus['meta']['collection_ok'])
            self.assertTrue(focus['data'])

    def test_corrupt_present_state_is_not_replaced_by_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            api=Path(tmp)/'api/v1';api.mkdir(parents=True)
            state=api.parent/'business/state.json';state.parent.mkdir();state.write_text('{}')
            with self.assertRaisesRegex(ValueError,'invalid_existing_business_state'):
                build(api,self.now,bootstrap=True)
            self.assertEqual(state.read_text(),'{}')

    def test_rollback_preserves_current_human_decisions_and_observation_bytes(self):
        # Tool output remains inside review even when backup inputs are temporary.
        with tempfile.TemporaryDirectory(dir=ROOT/'review') as tmp:
            root=Path(tmp);backup=root/'old';current=root/'current';backup.mkdir();current.mkdir()
            (backup/'index.html').write_text('old UI')
            (backup/'api').mkdir();(backup/'api/decisions.json').write_text('{"review_status":"pending"}')
            (current/'api/business').mkdir(parents=True)
            (current/'api/business/state.json').write_text('{"review_status":"verified","observations":["new"]}')
            expected={p.relative_to(backup).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in backup.rglob('*') if p.is_file()}
            result=prepare(backup,current,root/'restored',expected)
            self.assertFalse(result['deployed'])
            self.assertEqual((root/'restored/index.html').read_text(),'old UI')
            self.assertEqual(api_hashes(root/'restored'),api_hashes(current))
            with self.assertRaisesRegex(ValueError,'backup_manifest_mismatch'):
                prepare(backup,current,root/'bad',{})
