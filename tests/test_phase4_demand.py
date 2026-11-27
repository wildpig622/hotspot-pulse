import unittest
from datetime import date
from scripts.demand_candidates import retain_official,operating_relevance,compact_event,recent_announcement
from scripts.phase4_experiment import query_plan,SearchAgent


class DemandTests(unittest.TestCase):
    def test_missing_official_record_retains_identity_and_actual_check_time(self):
        old={'event_id':'off_1','start_at':'2026-12-06','review_status':'pending','last_evidence_check_at':'2026-11-26T07:00:00Z'}
        row=retain_official([], [old],date(2026,11,27))[0]
        self.assertEqual(row['event_id'],'off_1');self.assertEqual(row['last_evidence_check_at'],old['last_evidence_check_at'])
        self.assertEqual(row['source_presence'],'retained_not_rediscovered')
        self.assertEqual(retain_official([], [old],date(2026,12,7)),[])

    def test_refresh_cannot_replace_human_decision_or_refresh_unread_date(self):
        old={'event_id':'a','start_at':'2026-12-06','review_status':'rejected','last_evidence_check_at':'2026-11-26T07:00:00Z'}
        new={**old,'start_at':'2026-12-07','review_status':'verified','last_evidence_check_at':'2026-11-27T07:00:00Z'}
        row=retain_official([new],[old],date(2026,11,27))[0]
        self.assertEqual(row['review_status'],'rejected');self.assertEqual(row['start_at'],'2026-12-06')

    def test_business_priority_does_not_invent_scale_or_hotel_revenue(self):
        row={'event_name':'巡回演唱会','venue_name':'奥体体育馆','city_name':'西安市','review_status':'pending'}
        value=operating_relevance(row)
        self.assertEqual(value['review_priority'],'priority_review');self.assertIsNone(value['audience_scale'])
        self.assertEqual(value['lodging_increment_grade'],'unknown');self.assertIsNone(value['revenue_impact'])
        self.assertEqual(row['review_status'],'pending')
        self.assertEqual(operating_relevance({'event_name':'每周脱口秀'})['review_priority'],'routine_local')
        self.assertEqual(operating_relevance({'event_type':'holiday'})['review_priority'],'origin_market_review')

    def test_export_is_allowlisted_and_contact_redacted(self):
        r=compact_event({'event_id':'a','body_text':'unnecessary body','short_evidence':['contact@example.org'],'review_status':'pending'})
        self.assertNotIn('body_text',r);self.assertNotIn('contact@example.org',r['short_evidence'][0])

    def test_search_inputs_have_no_regression_names_and_old_announcements_are_not_recent(self):
        plan=query_plan();self.assertEqual(len(plan),18)
        for row in plan:
            for name in ['那英','徐良','老狼','FICMSS','ICCLL']:self.assertNotIn(name,row['query'])
        self.assertFalse(recent_announcement('2026-11-10',date(2026,11,27)))
        self.assertTrue(recent_announcement('2026-11-22',date(2026,11,27)))
        self.assertFalse(recent_announcement(None,date(2026,11,27)))

    def test_agent_searches_then_reads_provider_results_without_url_seed(self):
        class Provider:
            def search(self,q):return [{'url':'https://example.org/notice','title':'公告'}],{'status':'ok'}
        class Reader:
            def fetch(self,url,role):return '<p>正文</p>',{'status':'ok'}
        r=SearchAgent(Provider(),Reader()).discover('西安未来活动')
        self.assertTrue(r['results'][0]['body_read']);self.assertFalse(r['benchmark_used'])
