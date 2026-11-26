import copy
import unittest
from scripts.event_observations import build_ledger,evidence_gate,preserve_record_ids,v2_candidates


class ObservationTests(unittest.TestCase):
    def row(self,**kwargs):
        return dict(event_id='src_123',source_record_id='showstart_123',event_name='样本',last_seen_at='2026-11-26T07:00:00Z',**kwargs)

    def test_status_history_is_append_only_and_retains_existing_identity_and_human_decision(self):
        v2={'state':{'membership':{'src_123':'hp_abc'}},'events':{'data':[{'event_id':'hp_abc','review_status':'verified'}]}}
        rows=[self.row(observation_type='announced'),self.row(observation_type='ticket_on_sale'),self.row(observation_type='sold_out'),self.row(observation_type='extra_show'),self.row(observation_type='cancelled')]
        ledger=build_ledger(rows,v2=v2)
        self.assertEqual(len(ledger['observations']),5)
        self.assertEqual(ledger['events']['hp_abc']['review_status'],'verified')
        self.assertEqual(ledger['events']['hp_abc']['observation_type'],'cancelled')
        self.assertTrue(all(r['review_status']=='pending' for r in ledger['observations']))

    def test_replay_does_not_inflate_history_but_independent_observation_times_are_retained(self):
        r=self.row();first=build_ledger([r]);before=copy.deepcopy(first)
        second=build_ledger([r],first)
        self.assertEqual(first,before);self.assertEqual(len(second['observations']),1)
        r['last_seen_at']='2026-11-27T07:00:00Z'
        self.assertEqual(len(build_ledger([r],second)['observations']),2)

    def test_out_of_order_status_does_not_replace_latest_state(self):
        later=self.row(observation_type='cancelled');earlier=self.row(observation_type='announced');earlier['last_seen_at']='2026-11-25T07:00:00Z'
        ledger=build_ledger([later,earlier]);self.assertEqual(ledger['events']['src_123']['observation_type'],'cancelled')

    def test_unscheduled_and_market_signal_do_not_enter_v2(self):
        for kind in ['unscheduled','market_signal']:
            r=self.row(signal_kind=kind);ledger=build_ledger([r]);self.assertEqual(ledger['observations'][0]['kind'],kind);self.assertEqual(v2_candidates([r]),[])
        r=self.row(start_at='2026-12-19',end_at='2026-12-19',city_name='西安市',city_match='text_confirmed',event_date_role='event',review_status='pending')
        self.assertEqual(v2_candidates([r])[0],r)

    def test_dated_national_announcement_is_not_local_v2_event(self):
        self.assertEqual(v2_candidates([self.row(start_at='2026-12-19',event_date_role='event',city_name=None)]),[])

    def test_aliases_resolve_without_new_canonical_id(self):
        ledger=build_ledger([self.row()],v2={'state':{'membership':{'src_123':'hp_old'},'aliases':{'hp_old':'hp_new'}}})
        self.assertIn('hp_new',ledger['events'])

    def test_missing_timestamp_or_invalid_kind_is_rejected(self):
        for r in [{'event_id':'a'},self.row(signal_kind='invented'),self.row(signal_kind='scheduled')]:
            with self.assertRaises(ValueError):build_ledger([r])

    def test_legacy_article_identity_requires_exact_city_session_and_unique_match(self):
        old={'event_id':'off_old','source_url':'https://a.cn/notice','city_name':'西安市','start_at':'2026-12-19','end_at':'2026-12-19'}
        new={**old,'event_id':'off_discovered'}
        bound,links=preserve_record_ids([new],[old]);self.assertEqual(bound[0]['event_id'],'off_old');self.assertEqual(len(links),1)
        self.assertEqual(preserve_record_ids([new],[old,old])[0][0]['event_id'],'off_discovered')
        self.assertEqual(preserve_record_ids([{**new,'city_name':'天津市'}],[old])[1],[])
        self.assertEqual(preserve_record_ids([{**new,'start_at':'2026-12-20'}],[old])[1],[])

    def test_llm_missing_quote_or_invented_date_is_rejected(self):
        body='会议将于2026年12月19日举行。'
        draft={'quote':body,'date_role':'event','start_at':'2026-12-19','end_at':'2026-12-19','start_at_token':'2026年12月19日','end_at_token':'2026年12月19日'}
        self.assertTrue(evidence_gate(draft,body)[0])
        self.assertFalse(evidence_gate({**draft,'start_at':'2026-12-20'},body)[0])
        self.assertFalse(evidence_gate({**draft,'quote':'不存在'},body)[0])
        self.assertFalse(evidence_gate({**draft,'date_role':'publication'},body)[0])

    def test_abbreviated_range_requires_month_and_year_evidence(self):
        body='2026大会将于10月14日至16日举行。'
        draft={'quote':'10月14日至16日','date_role':'event','start_at':'2026-10-14','end_at':'2026-10-16','start_at_token':'10月14日','end_at_token':'16日','year_quote':'2026大会'}
        self.assertTrue(evidence_gate(draft,body)[0])
        self.assertFalse(evidence_gate({**draft,'year_quote':''},body)[0])
        self.assertFalse(evidence_gate({**draft,'end_at':'2026-11-16'},body)[0])

if __name__=='__main__':unittest.main()
