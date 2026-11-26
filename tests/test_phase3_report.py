import unittest
from scripts.phase3_report import reference_metrics


class ReferenceMetricTests(unittest.TestCase):
    def test_unmatched_output_is_not_false_positive_and_failed_sources_have_zero_recall(self):
        rows=[{'event_id':'a','event_name':'未知活动','city_name':'西安市','start_at':'2026-12-01','source_id':'s'}]
        gold=[{'id':'b','name':'人工样本','city':'西安市','start':'2026-12-19','end':'2026-12-19','url':'https://a.cn/1','terms':['人工样本'],'category':'conference','basis':'independent'}]
        result=reference_metrics(rows,gold,['failed-source'])
        self.assertIsNone(result['false_positive_rate']);self.assertEqual(result['union_recall'],0)
        self.assertEqual(next(s for s in result['sources'] if s['source_id']=='failed-source')['independent_discoveries'],0)

    def test_same_tour_name_in_another_city_is_not_automatically_wrong_city(self):
        rows=[{'event_id':'a','event_name':'巡演样本','city_name':'天津市','start_at':'2026-12-19','end_at':'2026-12-19','event_detail_url':'https://a.cn/2','source_id':'s'}]
        gold=[{'id':'b','name':'巡演样本','city':'西安市','start':'2026-12-19','end':'2026-12-19','url':'https://a.cn/1','terms':['巡演样本'],'category':'performance','basis':'independent'}]
        result=reference_metrics(rows,gold)
        self.assertEqual(result['wrong_city_records'],0);self.assertFalse(result['data'][0]['valid_discovery'])
        rows[0]['event_detail_url']='https://a.cn/1'
        self.assertEqual(reference_metrics(rows,gold)['wrong_city_records'],1)

    def test_wrong_date_is_not_counted_as_successful_discovery(self):
        rows=[{'event_id':'a','event_name':'样本','city_name':'西安市','start_at':'2026-12-20','end_at':'2026-12-20','source_id':'s'}]
        gold=[{'id':'b','name':'样本','city':'西安市','start':'2026-12-19','end':'2026-12-19','url':'https://a.cn/1','terms':['样本'],'category':'conference','basis':'independent'}]
        result=reference_metrics(rows,gold)
        self.assertEqual(result['wrong_date_records'],1);self.assertEqual(result['union_recall'],0)
