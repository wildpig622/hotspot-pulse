import copy
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.event_feed import build_feed
from scripts.validate_event_feed import validate
from scripts.check_service_execution import request_errors
from scripts.official_calendar import parse_events
from scripts.source_calendar import inspect_detail, collect_source_calendar
from scripts.refresh_service import run
from integrations.import_batch import build_import_batch

NOW = datetime(2026, 11, 4, 8, tzinfo=timezone.utc)
STAMP = '2026-11-04T08:00:00Z'


def row(key='a', **kwargs):
    result = dict(event_id=key, event_name='某某巡演', city_name='重庆市', event_type='concert',
                  venue_name='示例体育馆', start_at='2026-11-07', end_at='2026-11-07',
                  date_confidence='source_listing', review_status='pending', event_status='unknown',
                  first_seen_at=STAMP, last_seen_at=STAMP, sources=[{'source_url':'https://example.org/list', 'source_type':'authorized_ticketing'}])
    result.update(kwargs)
    return result


def feed(rows, prior=None, links=None, **kwargs):
    return build_feed({'source_candidates':rows}, {'last_collection_at':STAMP},
                      {'status':'ok','last_successful_collection_at':STAMP}, kwargs.get('now',NOW), prior, links)


class IdentityTests(unittest.TestCase):
    def test_exact_same_identity_merges_but_shared_url_and_similar_title_do_not(self):
        result=feed([row(), row('b'), row('c',event_name='另外巡演')])
        self.assertEqual(len(result['events']['data']),2)
        self.assertEqual(validate(result['events'],result['changes'])['status'],'PASS')

    def test_cross_city_and_type_links_rejected(self):
        for changed in ({'city_name':'成都市'},{'event_type':'sports'}):
            with self.assertRaises(ValueError):feed([row(),row('b',**changed)],links=[{'member_ids':['a','b']}])

    def test_explicit_link_preserves_original_identity_and_records_merge(self):
        rows=[row(),row('b',event_name='新闻中的巡演名称')]
        first=feed(rows)
        linked=feed(rows,first,[{'member_ids':['a','b']}])
        self.assertEqual(len(linked['events']['data']),1)
        canonical=linked['events']['data'][0]['event_id']
        self.assertIn(canonical,[r['event_id'] for r in first['events']['data']])
        self.assertEqual(linked['changes']['data'][-1]['change_type'],'merged')
        repeat=feed(rows,linked,[{'member_ids':['a','b']}])
        self.assertEqual(repeat['events']['meta']['cursor'],linked['events']['meta']['cursor'])

    def test_reschedule_has_same_event_and_occurrence_and_new_revision(self):
        first=feed([row()]);changed=feed([row(start_at='2026-11-09',end_at='2026-11-09')],first)
        a,b=first['events']['data'][0],changed['events']['data'][0]
        self.assertEqual(a['event_id'],b['event_id'])
        self.assertEqual(a['sessions'][0]['occurrence_id'],b['sessions'][0]['occurrence_id'])
        self.assertEqual(b['revision'],2)

    def test_added_earlier_session_does_not_renumber_existing_sessions(self):
        sessions=[{'start_at':'2026-11-07','end_at':'2026-11-07'},{'start_at':'2026-11-09','end_at':'2026-11-09'}]
        first=feed([row(sessions=sessions)])
        second=feed([row(sessions=[{'start_at':'2026-11-05','end_at':'2026-11-05'}]+sessions)],first)
        self.assertEqual(first['events']['data'][0]['sessions'],second['events']['data'][0]['sessions'][1:])
        self.assertEqual(len({s['occurrence_id'] for s in second['events']['data'][0]['sessions']}),3)

    def test_refresh_timestamps_do_not_create_semantic_changes(self):
        first=feed([row()]);again=feed([row(last_seen_at='2026-11-04T09:00:00Z')],first)
        self.assertEqual(first['events']['meta']['cursor'],again['events']['meta']['cursor'])

    def test_conflicting_dates_hold_and_never_auto_verify(self):
        result=feed([row(review_status='verified'),row('b',start_at='2026-11-09',end_at='2026-11-09')],links=[{'member_ids':['a','b']}])
        event=result['events']['data'][0]
        self.assertEqual(event['review_status'],'pending')
        self.assertEqual(event['availability'],'needs_date_review')

    def test_cancelled_postponed_and_missing_are_retained(self):
        first=feed([row()]);missing=feed([],first)
        self.assertEqual(missing['events']['data'][0]['availability'],'not_recently_observed')
        for status in ('cancelled','postponed'):
            self.assertEqual(feed([row(event_status=status)],first)['events']['data'][0]['availability'],status)

    def test_malformed_change_cursors_fail_cleanly(self):
        built=feed([row()]);built['changes']['data'].append({'cursor':None})
        self.assertIn('invalid_change_cursors',validate(built['events'],built['changes'])['errors'])

    def test_staleness_uses_actual_collection_not_rebuild(self):
        built=feed([row()],now=NOW+timedelta(hours=19))
        self.assertTrue(built['events']['meta']['is_stale'])
        self.assertEqual(built['events']['meta']['last_successful_collection_at'],STAMP)


class SourceTests(unittest.TestCase):
    def test_detail_ignores_refund_policy_outside_current_header(self):
        body='<div class="describe"><div class="title">某某巡演</div><p>演出时间：11月7日 场地：示例体育馆</p></div><p>如演出取消或延期可退款</p>'
        observation=inspect_detail(body,row())
        self.assertIsNone(observation['event_status'])
        self.assertFalse(observation['date_review_required'])
        self.assertEqual(inspect_detail(body.replace('11月7日','11月8日'),row())['date_review_required'],True)
        conditional='<div class="describe"><div class="title">某某巡演</div>如遇演出取消或延期可退款</div>'
        self.assertIsNone(inspect_detail(conditional,row())['event_status'])

    def test_detail_identity_and_explicit_status(self):
        with self.assertRaises(ValueError):inspect_detail('<div class="describe"><div class="title">其他活动</div></div>',row())
        for text,status in [('演出已取消','cancelled'),('演出延期','postponed')]:
            self.assertEqual(inspect_detail('<div class="describe"><div class="title">某某巡演</div>'+text+'</div>',row())['event_status'],status)

    def test_pagination_continues_beyond_two_pages(self):
        from scripts import collect
        city={'city_name':'重庆市','city_slug':'chongqing','aliases':['重庆']}
        def transport(url):
            from urllib.parse import urlparse,parse_qs
            page=int(parse_qs(urlparse(url).query)['pageNo'][0])
            cards=''.join(f'<a class="show-item item" href="/event/{page*100+i}"><div class="title">巡演{i}</div><div class="time">时间：2026/11/07 19:30</div><div class="addr">[重庆]剧院</div></a>' for i in range(20 if page<=3 else 1))
            return '<div class="show-list">'+cards+'</div>'
        rows,checks=collect_source_calendar(collect.ROOT,[city],STAMP,NOW.date(),transport=transport)
        self.assertEqual(len(rows),61)
        self.assertEqual(len(checks[0]['pages']),4)
        self.assertTrue(checks[0]['pagination']['complete'])

    def test_official_schema_requires_explicit_city_date_and_identity(self):
        source={'url':'https://example.org/official','publisher':'场馆','source_type':'official_venue'}
        cities=[{'city_name':'重庆市','city_slug':'chongqing','aliases':['重庆']}]
        obj={'@type':'BusinessEvent','name':'行业大会','startDate':'2026-11-09','endDate':'2026-11-10','eventStatus':'https://schema.org/EventCancelled','location':{'name':'国际会议中心','address':{'addressLocality':'重庆'}}}
        parse=lambda o:parse_events('<script type="application/ld+json">'+json.dumps(o)+'</script>',source,cities,STAMP,NOW.date())
        self.assertEqual(parse(obj)[0]['event_status'],'cancelled')
        self.assertEqual(parse(obj)[0]['review_status'],'pending')
        self.assertEqual(parse(dict(obj,startDate='11月9日')),[])
        self.assertEqual(parse(dict(obj,location={'name':'会议中心','address':{'addressLocality':'成都'}})),[])


class ServiceTests(unittest.TestCase):
    def test_only_authorized_schedule_and_exact_manual_commit(self):
        config={'enabled':True,'cron_utc':'0 0,8 * * *'}
        env={'GITHUB_SHA':'a'*40,'GITHUB_REF':'refs/heads/main','GITHUB_EVENT_NAME':'schedule'}
        self.assertEqual(request_errors(env,config,{'schedule':config['cron_utc']}),[])
        self.assertTrue(request_errors(env,config,{'schedule':'* * * * *'}))
        for kind in ('push','pull_request'):
            self.assertTrue(request_errors(dict(env,GITHUB_EVENT_NAME=kind),config))
        manual=dict(env,GITHUB_EVENT_NAME='workflow_dispatch',REQUESTED_SHA='a'*40,REQUEST_CONFIRMATION='REFRESH_AND_PUBLISH_PENDING')
        self.assertEqual(request_errors(manual,config),[])
        self.assertTrue(request_errors(dict(manual,REQUESTED_SHA='b'*40),config))

    def test_failed_candidate_does_not_replace_last_good_data(self):
        from scripts import collect
        with tempfile.TemporaryDirectory() as tmp:
            api=Path(tmp)/'api/v1';api.mkdir(parents=True)
            for name,value in {'hotspots':{'meta':{'last_collection_at':STAMP},'data':[]},'activities':{'source_candidates':[row()]},'health':{'status':'ok'}}.items():collect.write_json(api/(name+'.json'),value)
            original=(api/'activities.json').read_bytes()
            def bad_collector(**kwargs):
                collect.write_json(collect.SITE_API/'activities.json',{'data':[]})
                return 0
            result=run(api,bad_collector,lambda *a,**k:{'errors':['broken_city']},NOW)
            self.assertFalse(result['collection_ok'])
            self.assertEqual((api/'activities.json').read_bytes(),original)
            health=json.loads((api/'health.json').read_text(encoding='utf8'))
            self.assertFalse(health['data_updated'])
            self.assertEqual(health['last_successful_collection_at'],STAMP)
            self.assertTrue(json.loads((api.parent/'v2/events.json').read_text(encoding='utf8'))['meta']['using_cached_data'])


class ImportAdapterTests(unittest.TestCase):
    def test_similar_existing_identity_is_held_without_automatic_merge(self):
        snapshot=feed([row(event_name='2026某某巡演重庆站')])['events']
        existing=row('consumer-id',event_name='某某巡演重庆站')
        result=build_import_batch(snapshot,existing_events=[existing],now=NOW)
        self.assertEqual(result['report']['events'],0)
        self.assertEqual(result['report']['held'][0]['existing_event_ids'],['consumer-id'])

    def test_pending_unique_identity_for_all_sources_and_sessions(self):
        snapshot=feed([row(),row('b',event_name='另外活动')])['events']
        batch=build_import_batch(snapshot,now=NOW)['p_batch']['events']
        urls=[s['source_url'] for ev in batch for s in ev['sources']]
        self.assertEqual(len(urls),len(set(urls)))
        self.assertEqual({r['review_status'] for r in batch},{'pending'})
        self.assertEqual({r['session_hint'] for r in batch},{'new_session'})
        self.assertTrue(all('https://example.org/list' in r['sources'][1]['evidence_summary'] for r in batch))

    def test_existing_verified_and_unbound_reschedule_are_held(self):
        snapshot=feed([row(),row('b',event_name='其他活动',date_changes=[{'before':'old'}])])['events']
        result=build_import_batch(snapshot,existing_events=[row(review_status='verified')],now=NOW)
        self.assertEqual(result['report']['events'],0)
        self.assertEqual(len(result['report']['held']),2)

    def test_stale_and_failed_snapshots_rejected(self):
        snapshot=feed([row()])['events']
        with self.assertRaises(ValueError):build_import_batch(snapshot,now=NOW+timedelta(hours=19))
        snapshot['meta']['using_cached_data']=True
        with self.assertRaises(ValueError):build_import_batch(snapshot,now=NOW)

    def test_bound_reschedule_uses_same_identity(self):
        first=feed([row()]);second=feed([row(start_at='2026-11-09',end_at='2026-11-09',date_changes=[{}])],first)
        occurrence=first['events']['data'][0]['sessions'][0]['occurrence_id']
        a=build_import_batch(first['events'],now=NOW)['p_batch']['events'][0]
        b=build_import_batch(second['events'],bound_occurrences=[occurrence],now=NOW)['p_batch']['events'][0]
        self.assertEqual(a['sources'][0]['source_url'],b['sources'][0]['source_url'])
        self.assertIsNone(b['session_hint'])
