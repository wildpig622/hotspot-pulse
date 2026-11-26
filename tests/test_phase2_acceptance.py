import unittest
from datetime import date
from pathlib import Path
from scripts import collect
from scripts.phase2_acceptance import parse_official, disposition, run

class Phase2Tests(unittest.TestCase):
    def test_national_exam_stays_national_and_keeps_date_role(self):
        source={'id':'test','publisher':'考试机关','url':'https://example.gov.cn/a','topic':'exam','level':'national',
                'rules':[{'name':'2027考研','pattern':'初试时间为(2026年12月19日至20日)','date_text_group':1}]}
        rows,diag,_,_=parse_official('<p>报名时间为2026年10月15日。初试时间为2026年12月19日至20日。</p>',source,date(2026,11,26),'2026-11-26T00:00:00Z')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['start_at'],'2026-12-19')
        self.assertIsNone(rows[0]['city_name'])
        self.assertFalse(rows[0]['local_demand_confirmed'])
        self.assertEqual(rows[0]['review_status'],'pending')
        missing=parse_official('<p>报名2026年10月15日</p>',source,date(2026,11,26),'2026-11-26T00:00:00Z')
        self.assertEqual(missing[0],[])
        self.assertEqual(missing[1][0]['status'],'selector_not_matched')

    def test_score_release_date_is_not_exam_date(self):
        row=collect.build_candidate({'city_name':'天津市','city_slug':'tianjin','aliases':['天津']},
            {'title':'天津公务员考试成绩查询时间：2027年1月29日','url':'https://example.gov.cn/score'},
            '2026-11-26T00:00:00Z',date(2026,11,26))
        self.assertIsNone(row['start_at'])
        self.assertTrue(disposition(row,date(2026,11,26)))

    def test_specific_conference_beats_incidental_school_term(self):
        self.assertEqual(collect.classify_event('中小学教育学术研讨会'),'conference')

    def test_production_output_is_rejected_before_writes_or_network(self):
        from scripts.phase2_acceptance import ROOT
        with self.assertRaisesRegex(ValueError,'isolated_output_required'):
            run(ROOT/'site/api/v1',date(2026,11,26))

    def test_unknown_city_and_undated_events_stay_excluded(self):
        reasons=disposition({'event_id':'a','event_name':'考试公告','city_name':'西安市','city_slug':'xian',
                            'city_match':'query_only','content_kind':'uncertain','event_date_role':'unknown'},date(2026,11,26))
        self.assertIn('city_not_confirmed',reasons)
        self.assertIn('missing_event_date',reasons)
