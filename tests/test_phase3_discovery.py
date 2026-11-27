import copy
import json
import gzip
import zipfile
from scripts.phase3_bundle import pack
import tempfile
import unittest
from datetime import date
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from scripts.phase3_discovery import Reader,ROOT,archive_bytes,candidate_links,crawl_source,extract_article,safe_output
from scripts.phase3_date_sample import sample_rows
from scripts.phase3_public import parse_cosgo
from scripts.source_calendar import parse_listing

TODAY=date(2026,11,26)
STAMP='2026-11-26T07:00:00Z'
SOURCE={'id':'test','scope':'organizer','topic':'conference'}


class DiscoveryTests(unittest.TestCase):
    def test_discovery_config_does_not_contain_benchmark_names_or_detail_urls(self):
        config=(ROOT/'config/phase3-discovery.json').read_text(encoding='utf8')
        gold=json.loads((ROOT/'tests/fixtures/phase3-benchmark.json').read_text(encoding='utf8'))
        roots={s['url'] for s in json.loads(config)['sources']}
        for row in gold['data']:
            self.assertNotIn(row['url'],roots)
            self.assertNotIn(row['name'],config)

    def test_bfs_follows_next_page_then_reads_article_without_detail_seed(self):
        index='<a href="/page2.htm">下一页</a><a href="https://outside.cn/a">全国考试通知</a>'
        second='<a href="/2026/notice.htm">2026学术研讨会通知</a>'
        class FakeReader:
            def fetch(self,url,role):
                bodies={'https://test.cn/':index,'https://test.cn/page2.htm':second,'https://test.cn/2026/notice.htm':'<h1>学术研讨会</h1><p>将于2026年12月19日举行。</p>'}
                return bodies[url],{'checked_at':STAMP,'url':url,'status':'ok'}
        rows,route=crawl_source(FakeReader(),{**SOURCE,'url':'https://test.cn/'},TODAY,{'max_index_pages':3,'max_articles_per_source':5})
        self.assertEqual(route['index_pages_attempted'],2)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['start_at'],'2026-12-19')

    def test_calendar_is_not_merged_into_one_manufactured_interval(self):
        r=extract_article('<h1>2027学校校历</h1><p>寒假2027年1月23日至2月21日。</p><p>暑假2027年7月7日至8月31日。</p>',SOURCE,'https://a.cn/a',STAMP,TODAY)
        self.assertIsNone(r['start_at']);self.assertTrue(r['date_evidence'])

    def test_footer_city_and_date_do_not_contaminate_main_article(self):
        body='<h1>全国研究生考试通知</h1><div hidden class="v_news_content"><p>初试将于2026年12月19日至20日举行。</p></div><footer>地址：天津 2027年1月1日</footer>'
        r=extract_article(body,{**SOURCE,'scope':'national'},'https://a.cn/a',STAMP,TODAY)
        self.assertIsNone(r['city_name']);self.assertEqual(r['end_at'],'2026-12-20')
        self.assertNotIn('2027年1月1日',r['body_text'])

    def test_results_publication_is_not_exam_day(self):
        r=extract_article('<h1>艺术类考试通知</h1><p>成绩将于2027年1月12日公布。</p>',SOURCE,'https://a.cn/a',STAMP,TODAY)
        self.assertIsNone(r['start_at'])
        self.assertEqual(r['date_evidence'][0]['parsed']['event_date_role'],'non_event')

    def test_online_course_and_navigation_title_are_held_or_corrected(self):
        r=extract_article('<h1>管理服务</h1><p>会议将于2026年12月19日举行。</p>',SOURCE,'https://a.cn/a',STAMP,TODAY,'数字赋能研讨会')
        self.assertEqual(r['event_name'],'数字赋能研讨会')
        r=extract_article('<h1>网上在线课程开课通知</h1><p>考试将于2026年12月29日举行。</p>',SOURCE,'https://a.cn/b',STAMP,TODAY)
        self.assertIsNone(r['start_at'])

    def test_output_cannot_target_production_or_synced_sources(self):
        for p in [ROOT,ROOT/'site/api',ROOT.parent/'sources/test']:
            with self.assertRaises(ValueError):safe_output(p)

    def test_stratified_sample_is_reproducible_unique_and_non_mutating(self):
        rows=[{'event_id':str(i),'city_name':['西安市','济南市','天津市','厦门市'][i%4],'event_type':['concert','exam'][i%2],'start_at':None} for i in range(240)]
        before=copy.deepcopy(rows);a=sample_rows(rows);b=sample_rows(rows)
        self.assertEqual(a,b);self.assertEqual(len(a),200);self.assertEqual(len({r['event_id'] for r in a}),200);self.assertEqual(rows,before)

    def test_ticket_horizon_is_opt_in_and_does_not_change_existing_default(self):
        city={'city_name':'西安市','city_slug':'xian','aliases':['西安']}
        body='<div class="show-list"><a class="show-item" href="/event/123"><div class="title">西安音乐会</div><div class="time">时间：2027/05/21 19:30</div><div class="addr">[西安]剧场</div></a></div>'
        self.assertEqual(parse_listing(body,city,'https://a.cn',STAMP,TODAY),[])
        self.assertEqual(len(parse_listing(body,city,'https://a.cn',STAMP,TODAY,horizon_days=365)),1)

    def test_secondary_card_never_inherits_neighbor_city_or_primary_verification(self):
        body='<div class="ev"><h4>天津·角色生日会</h4><div class="meta"><b>2026.11.28 10:00</b>天津 · 悦动广场 · ¥58</div><a href="https://mall.bilibili.com/detail?id=123">购票</a></div>'
        row=parse_cosgo(body,'https://a.cn',STAMP,TODAY)[0]
        self.assertFalse(row['primary_body_read']);self.assertEqual(row['review_status'],'pending')
        self.assertEqual(parse_cosgo(body.replace('天津 ·','北京 ·'),'https://a.cn',STAMP,TODAY),[])


class ReaderTests(unittest.TestCase):
    def test_review_bundle_replays_original_body_without_extracting_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent=Path(tmp);output=parent/'discovery';output.mkdir();raw=gzip.compress('原始正文'.encode(),mtime=0)
            check={'url':'https://a.cn/a','status':'ok','raw_file':'raw/example.gz','encoding':'utf8','checked_at':STAMP}
            with zipfile.ZipFile(parent/'responses.zip','w') as archive:archive.writestr('discovery/raw/example.gz',raw)
            (output/'run.json').write_text(json.dumps({'checks':[check]}),encoding='utf8')
            self.assertEqual(archive_bytes(output,check),raw)
            with patch('urllib.request.urlopen',side_effect=AssertionError('network_on_replay')):
                body,record=Reader(output).fetch('https://a.cn/a')
            self.assertEqual(body,'原始正文');self.assertEqual(record['checked_at'],STAMP)
            self.assertFalse((output/'raw').exists())

    def test_missing_bundle_member_does_not_create_a_successful_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent=Path(tmp);output=parent/'discovery';output.mkdir()
            with zipfile.ZipFile(parent/'responses.zip','w') as archive:archive.writestr('other/file',b'')
            self.assertIsNone(archive_bytes(output,{'raw_file':'raw/missing.gz'}))

    def test_bundle_builder_rejects_corrupt_source_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);output=root/'discovery';(output/'raw').mkdir(parents=True)
            (output/'raw/a.gz').write_bytes(gzip.compress(b'wrong body'))
            (output/'run.json').write_text(json.dumps({'checks':[{'status':'ok','url':'https://a.cn/a','raw_file':'raw/a.gz','sha256':'0'*64}]}),encoding='utf8')
            with self.assertRaisesRegex(ValueError,'response_hash_mismatch'):pack(root)
            self.assertFalse((root/'responses.zip').exists())

    class Response:
        def __init__(self,body,url):
            self.body=body.encode();self.url=url;self.status=200;self.headers=Message();self.headers['Content-Type']='text/plain; charset=utf-8'
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,n):return self.body[:n]

    def test_robots_denial_never_fetches_article(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader=Reader(tmp,0)
            with patch('urllib.request.urlopen',return_value=self.Response('User-agent: *\nDisallow: /private','https://a.cn/robots.txt')) as fetch:
                body,check=reader.fetch('https://a.cn/private/article')
            self.assertEqual(fetch.call_count,1);self.assertFalse(body);self.assertEqual(check['status'],'blocked')

    def test_challenge_is_not_success_and_bad_scheme_is_not_fetched(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader=Reader(tmp,0)
            self.assertEqual(reader.fetch('http://a.cn/a')[1]['status'],'rejected')
            with patch('urllib.request.urlopen',return_value=self.Response('请输入验证码','https://a.cn/a')):
                body,check=reader.fetch('https://a.cn/a',respect_robots=False)
            self.assertFalse(body);self.assertEqual(check['error'],'access_challenge')

    def test_robots_transport_failure_is_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('urllib.request.urlopen',side_effect=OSError('TLS failed')) as fetch:
                body,check=Reader(tmp,0).fetch('https://a.cn/a')
            self.assertEqual(fetch.call_count,1);self.assertEqual(check['status'],'blocked')

if __name__=='__main__':unittest.main()
