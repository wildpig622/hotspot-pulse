import json
import unittest
from datetime import date,datetime,timezone
from urllib.parse import parse_qs,urlparse

from scripts.monitoring_window import window_end,window_metadata,future_months
from scripts import collect
from scripts.activity_registry import activity_is_future
from scripts.source_calendar import parse_listing
from scripts.official_calendar import parse_events
from scripts.event_feed import build_feed


class PlanningWindowTests(unittest.TestCase):
    def test_complete_third_month_instead_of_ninety_days(self):
        self.assertEqual(window_end(date(2026,11,9)),date(2027,2,28))
        self.assertEqual(window_metadata(date(2026,11,9))['monitoring_horizon_days'],111)
        self.assertEqual(window_end(date(2026,11,30)),date(2027,2,28))

    def test_year_leap_and_short_month_boundaries(self):
        for today,expected in [('2027-11-09','2028-02-29'),('2026-12-31','2027-03-31'),('2027-01-31','2027-04-30'),('2027-04-30','2027-07-31')]:
            self.assertEqual(window_end(date.fromisoformat(today)).isoformat(),expected)
        self.assertEqual([d.strftime('%Y-%m') for d in future_months(date(2026,11,9))],['2026-12','2027-01','2027-02'])

    def test_legacy_day_configuration_is_supported_and_invalid_months_rejected(self):
        self.assertEqual(window_end(date(2026,11,9),{'monitoring_horizon_days':90}),date(2027,2,7))
        for bad in (0,13,True,'3'):
            with self.assertRaises(ValueError):window_end(date(2026,11,9),{'monitoring_complete_months':bad})

    def test_ticketing_and_calendar_both_include_february_28(self):
        city={'city_name':'成都市','city_slug':'chengdu','aliases':['成都']}
        template='<div class="show-list"><a class="show-item item" href="/event/123"><div class="title">成都春季演出</div><div class="time">时间：{day} 19:30</div><div class="addr">[成都]体育馆</div></a></div>'
        rows=parse_listing(template.format(day='2027/02/28'),city,'https://www.showstart.com/event/list','2026-11-09T04:00:00Z',date(2026,11,9))
        self.assertEqual(len(rows),1)
        self.assertTrue(activity_is_future(rows[0],date(2026,11,9)))
        self.assertEqual(parse_listing(template.format(day='2027/03/01'),city,'https://www.showstart.com/event/list','2026-11-09T04:00:00Z',date(2026,11,9)),[])

    def test_primary_structured_events_have_the_same_end_boundary(self):
        source={'url':'https://example.org/calendar','publisher':'场馆','source_type':'official_venue'}
        city={'city_name':'成都市','city_slug':'chengdu','aliases':['成都']}
        event={'@type':'BusinessEvent','name':'成都行业大会','startDate':'2027-02-28','location':{'name':'会议中心','address':{'addressLocality':'成都'}}}
        parse=lambda e:parse_events('<script type="application/ld+json">'+json.dumps(e)+'</script>',source,[city],'2026-11-09T04:00:00Z',date(2026,11,9))
        self.assertEqual(len(parse(event)),1)
        self.assertEqual(parse(dict(event,startDate='2027-03-01')),[])

    def test_each_month_query_and_fair_names_are_discoverable(self):
        city={'aliases':['成都']};topic=next(t for t in collect.FEED_TOPICS if t['key']=='exhibition')
        url=collect.build_feed_url(city,date(2026,11,9),topic,target_month=date(2027,2,1))
        query=parse_qs(urlparse(url).query)['q'][0]
        self.assertIn('2月',query);self.assertNotIn('1月 OR',query)
        for term in ('糖酒会','春糖','秋糖','广交会'):
            self.assertIn(term,query);self.assertEqual(collect.classify_event('2027成都'+term),'exhibition')

    def test_empty_future_months_are_explicit_gaps_not_zero_events_claims(self):
        built=build_feed({}, {'last_collection_at':'2026-11-09T04:00:00Z'}, {'status':'healthy'}, datetime(2026,11,9,4,tzinfo=timezone.utc))
        meta=built['events']['meta']
        self.assertEqual(meta['monitoring_window']['end_at'],'2027-02-28')
        self.assertEqual([r['month'] for r in meta['monthly_coverage']],['2026-12','2027-01','2027-02'])
        self.assertTrue(all(r['coverage_status']=='no_dated_candidates' for r in meta['monthly_coverage']))
