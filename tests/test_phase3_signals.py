import unittest
from scripts.phase3_platform_signals import extract_signals


class PlatformSignalTests(unittest.TestCase):
    def test_post_date_and_almost_sold_out_do_not_become_event_facts(self):
        p={'bilibili':[{'title':'早鸟票即将售罄！1.23-1.25 西安漫展今日开票','description':'','date':'2026-11-14','url':'https://www.bilibili.com/video/BV123'}]}
        row=extract_signals(p,'2026-11-26T07:00:00Z')[0]
        self.assertEqual(row['observation_type'],'ticket_on_sale');self.assertIsNone(row['start_at']);self.assertEqual(row['source_published_date'],'2026-11-14')

    def test_query_city_and_multi_city_posts_are_not_local_venue_evidence(self):
        p={'bilibili':[{'title':'西安天津待官宣场次','url':'https://www.bilibili.com/video/BV123'}]}
        self.assertIsNone(extract_signals(p,'2026-11-26T07:00:00Z')[0]['city_name'])

    def test_search_noise_is_not_automatically_registered(self):
        p={'bilibili':[{'title':'其他日常视频','url':'https://www.bilibili.com/video/BV123'}], 'baidu':[{'title':'西安漫展开票','url':'https://untrusted.test'}]}
        self.assertEqual(extract_signals(p,'2026-11-26T07:00:00Z'),[])

    def test_cities_outside_pilot_also_make_a_post_multi_city(self):
        p={'bilibili':[{'title':'西安杭州重庆三馆同时开票','url':'https://www.bilibili.com/video/BV123'}]}
        row=extract_signals(p,'2026-11-26T07:00:00Z')[0]
        self.assertIsNone(row['city_name']);self.assertIn('杭州市',row['mentioned_cities'])
