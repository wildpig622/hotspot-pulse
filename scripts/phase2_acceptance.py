"""Isolated, bounded public-source experiment. Never invokes production collection."""
from __future__ import annotations
import argparse
import collections
import concurrent.futures
import copy
import gzip
import hashlib
import json
import re
import subprocess
import types
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path
from . import collect

ROOT = Path(__file__).resolve().parents[1]
BASE = 'ca514b513b3f95de36a4655c7938afeb00e91c34'
TARGETS = {'西安市', '济南市', '天津市'}
CACHE = {}
TERMS = ['考研 研究生招生考试', '国考 国家公务员', '省考 公务员录用', '事业单位考试 事业编', '高考 普通高校招生', '中考 初中学业水平考试', '教资 教师资格考试', '职业资格考试 专业技术资格', '春假 秋假', '寒假 暑假 校历', '学术会议 学术年会 研讨会', '行业会议 峰会 论坛']

def git_bytes(path, ref=BASE):
    return subprocess.check_output(['git', '-c', 'safe.directory=' + ROOT.as_posix(), 'show', ref + ':' + path], cwd=ROOT)

def legacy_module():
    module = types.ModuleType('phase2_baseline')
    module.__file__ = str(ROOT / 'scripts/collect.py')
    exec(compile(git_bytes('scripts/collect.py'), module.__file__, 'exec'), module.__dict__)
    return module

class Page(HTMLParser):
    def __init__(self):
        super().__init__(); self.skip = 0; self.text = []; self.links = []; self.link = None
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style'): self.skip += 1
        if tag == 'a': self.link = [attrs.get('href', ''), '']
        if tag in ('p', 'div', 'br', 'li', 'tr', 'h1', 'h2'): self.text.append('\n')
    def handle_endtag(self, tag):
        if tag in ('script', 'style'): self.skip = max(0, self.skip - 1)
        if tag == 'a' and self.link: self.links.append(self.link); self.link = None
    def handle_data(self, text):
        if not self.skip:
            self.text.append(text)
            if self.link: self.link[1] += text

def read_public(url, output):
    prior = CACHE.get(url)
    if prior:
        if prior.get('status') != 'ok': return '', dict(prior, replayed=True)
        return gzip.decompress((output / prior['raw_file']).read_bytes()).decode(prior['encoding'], errors='replace'), dict(prior, replayed=True)
    stamp = collect.iso_utc(collect.now_utc())
    check = {'url': url, 'checked_at': stamp}
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username: raise ValueError('unsafe_source_url')
        request = urllib.request.Request(url, headers={'User-Agent': collect.USER_AGENT})
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read(2_000_001)
            check.update(http_status=response.status, final_url=response.url)
            if len(raw) > 2_000_000: raise ValueError('body_size_limit')
            encoding = response.headers.get_content_charset()
        if not encoding:
            match = re.search(br'charset=["\s]*([\w-]+)', raw[:4096], re.I)
            encoding = match[1].decode() if match else 'utf-8'
        body = raw.decode(encoding, errors='replace')
        if any(term in body[:20000] for term in ('访问验证', '验证码验证', 'Access Denied', 'Just a moment...', '安全验证')):
            raise ValueError('access_challenge')
        digest = hashlib.sha256(raw).hexdigest()
        relative = 'raw/' + digest + '.gz'
        (output / 'raw').mkdir(exist_ok=True)
        (output / relative).write_bytes(gzip.compress(raw, mtime=0))
        check.update(status='ok', sha256=digest, raw_file=relative, encoding=encoding, bytes=len(raw))
        return body, check
    except Exception as exc:
        check.update(status='failed', error_type=type(exc).__name__, error=str(exc), http_status=getattr(exc, 'code', check.get('http_status')))
        return '', check

def parse_official(body, source, today, checked_at):
    parser = Page(); parser.feed(body)
    text = re.sub(r'\s+', ' ', ''.join(parser.text))
    rows = []; diagnostics = []
    for rule in source.get('rules', []):
        match = re.search(rule['pattern'], text)
        if not match:
            diagnostics.append({'name': rule['name'], 'status': 'selector_not_matched'}); continue
        if rule.get('range_groups'):
            parts = [re.sub(r'\s+', '', match[i]) for i in rule['range_groups']]
            year = rule['year']; dates = []
            for part in parts:
                m = re.search(r'(?:(20\d{2})年)?(\d+)月(\d+)日', part)
                dates.append(date(int(m[1] or year), int(m[2]), int(m[3])).isoformat())
            start, end = dates
        else:
            value = match[rule.get('date_text_group', 1)]
            if rule.get('year') and not re.search(r'20\d{2}年', value): value = str(rule['year']) + '年' + value
            parsed = collect.extract_event_date('活动时间：' + value, today=today)
            start, end = parsed['start_at'], parsed['end_at'] or parsed['start_at']
        if not start or end < today.isoformat() or start > (today + timedelta(days=365)).isoformat():
            diagnostics.append({'name': rule['name'], 'status': 'outside_window'}); continue
        city = source.get('city')
        row = {'event_id': 'off_' + hashlib.sha256((source['id'] + '|' + rule['name']).encode()).hexdigest()[:12],
               'event_name': rule['name'], 'event_type': source['topic'], 'city_name': city,
               'scope_level': source['level'], 'local_demand_confirmed': False,
               'start_at': start, 'end_at': end, 'sessions': [{'start_at': start, 'end_at': end}],
               'event_date_role': 'event', 'date_precision': 'day', 'date_confidence': 'source_body',
               'content_kind': 'event_announcement', 'review_status': 'pending', 'event_status': 'unknown',
               'record_kind': 'official_candidate', 'source_url': source['url'],
               'source_id': source['id'], 'checked_at': checked_at, 'evidence_excerpt': match[0],
               'source_authority': source['publisher'], 'venue_name': None,
               'sources': [{'source_url': source['url'], 'publisher': source['publisher'], 'checked_at': checked_at,
                            'access_status': 'body_read', 'verification_status': 'unverified'}]}
        rows.append(row)
    return rows, diagnostics, parser.links, text

def disposition(row, today):
    reasons = collect.future_exclusion_reasons(row)
    if row.get('content_kind') not in ('event_announcement', 'uncertain'): reasons.append('non_event_content:' + str(row.get('content_kind')))
    if row.get('event_date_role') != 'event': reasons.append('not_explicit_event_date:' + str(row.get('event_date_role')))
    if not row.get('start_at'): reasons.append('missing_event_date')
    elif row.get('end_at', None) and row['end_at'] < row['start_at']: reasons.append('reversed_date')
    elif (row.get('end_at') or row['start_at']) < today.isoformat(): reasons.append('past_event')
    elif row['start_at'] > (today + timedelta(days=365)).isoformat(): reasons.append('beyond_365_days')
    if row.get('review_status') == 'rejected' or row.get('event_status') in ('cancelled', 'postponed'): reasons.append('inactive')
    return sorted(set(reasons))

def funnel(rows, today):
    counts = collections.Counter(); details = []
    for row in rows:
        reasons = disposition(row, today)
        counts.update(reasons)
        details.append({'event_id': row['event_id'], 'event_name': row['event_name'], 'city_name': row.get('city_name'),
                        'event_type': row.get('event_type'), 'start_at': row.get('start_at'),
                        'accepted': not reasons, 'reasons': reasons})
    stages = [('event_content', lambda r:r.get('content_kind') in ('event_announcement','uncertain')),
              ('explicit_event_date', lambda r:bool(r.get('start_at')) and r.get('event_date_role') == 'event'),
              ('confirmed_city', lambda r:r.get('city_match') == 'text_confirmed'),
              ('future_365', lambda r:bool(r.get('start_at')) and (r.get('end_at') or r['start_at']) >= today.isoformat() and r['start_at'] <= (today+timedelta(days=365)).isoformat()),
              ('safe_candidate', lambda r:not disposition(r,today))]
    remaining = rows; waterfall = []
    for label, predicate in stages:
        kept = [r for r in remaining if predicate(r)]
        waterfall.append({'stage':label,'input':len(remaining),'retained':len(kept),'lost':len(remaining)-len(kept)})
        remaining = kept
    return {'waterfall':waterfall,'raw_records': len(rows), 'explicit_event_dates': sum(bool(r.get('start_at')) and r.get('event_date_role') == 'event' for r in rows),
            'valid_future_candidates': sum(r['accepted'] for r in details), 'excluded_records': sum(not r['accepted'] for r in details),
            'reason_counts_nonexclusive': dict(counts), 'records': details}

def run(output, today, online=True, reuse=False):
    output = output.resolve()
    if output == ROOT or output.is_relative_to(ROOT / 'site') or output.is_relative_to(ROOT / 'sources'):
        raise ValueError('isolated_output_required')
    output.mkdir(parents=True, exist_ok=True)
    CACHE.clear()
    if reuse and (output/'report.json').exists():
        CACHE.update({r['url']:r for r in json.loads((output/'report.json').read_text(encoding='utf8'))['sources']})
    before = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / 'site/api').rglob('*.json')}
    baseline = legacy_module(); stamp = collect.iso_utc(collect.now_utc())
    original = json.loads(git_bytes('site/api/v1/hotspots.json'))
    old_rows = [baseline.enrich_existing_event(copy.deepcopy(row), today) for row in original['data']]
    new_rows = [collect.enrich_existing_event(copy.deepcopy(row), today) for row in original['data']]
    # Reclassify in audit only; production retention and human decisions stay intact.
    for row in new_rows:
        if row.get('review_status') != 'verified': row['event_type'] = collect.classify_event(row['event_name'] + ' ' + row.get('discovery_summary', ''))
    old_audit, new_audit = funnel(old_rows, today), funnel(new_rows, today)
    changes = [{'event_id': a['event_id'], 'before': a, 'after': b} for a, b in zip(old_audit['records'], new_audit['records']) if a != b]
    checks = []; observations = []; official = []; selectors = []; location_evidence = []
    cities = [c for c in collect.configured_cities() if c['city_name'] in TARGETS]
    jobs = []
    for city in cities:
        for terms in TERMS:
            topic = {'terms': terms.split()}
            for mode in ('years', 'months'):
                scope = dict(collect.SCOPE, monitoring_horizon_days=365)
                old_scope = collect.SCOPE; collect.SCOPE = scope
                try: url = collect.build_feed_url(city, today, topic, route={'mode': mode, 'lookback_days': 365})
                finally: collect.SCOPE = old_scope
                jobs.append((city, terms, mode, url))
    def rss(job):
        city, terms, mode, url = job; body, check = read_public(url, output)
        check.update(city=city['city_name'], terms=terms, route=mode, kind='rss')
        found = []
        if body:
            try: found = collect.parse_feed(body.encode('utf8'))
            except Exception as exc: check.update(status='failed', error_type=type(exc).__name__, error=str(exc))
        return city, found, check
    if online:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            for city, items, check in pool.map(rss, jobs):
                checks.append(check)
                for item in items:
                    row = collect.build_candidate(city, item, stamp, today)
                    row.update(discovery_query=check['url'], experiment_terms=check['terms'])
                    observations.append(row)
        sources = json.loads((ROOT / 'config/phase2-sources.json').read_text(encoding='utf8'))['sources']
        def official_read(source): return source, read_public(source['url'], output)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            for source, (body, check) in pool.map(official_read, sources):
                check.update(kind='official', source_id=source['id'], city=source.get('city'), scope_level=source['level'])
                checks.append(check)
                if not body: continue
                rows, diagnostic, links, text = parse_official(body, source, today, check['checked_at'])
                official.extend(rows); selectors.extend(dict(r, source_id=source['id']) for r in diagnostic)
                if source.get('location_pattern') and re.search(source['location_pattern'], text):
                    location_evidence.append({'source_id': source['id'], 'city_name': source['city'], 'national_event': source.get('national_event'),
                                              'source_url': source['url'], 'checked_at': check['checked_at'], 'evidence_excerpt': source['location_pattern']})
                # Independent index adapters expose relevant article links; dates require article bodies.
                check['relevant_links'] = [{'url': urllib.parse.urljoin(source['url'], href), 'title': title.strip()} for href, title in links
                                           if re.search(r'考试|考研|招录|招聘|校历|寒假|暑假|会议|年会|论坛', title)][:20]
    unique = {}; duplicates = []
    for row in observations:
        key = (row['city_name'], row['event_id'])
        if key in unique: duplicates.append({'event_id': row['event_id'], 'query': row['discovery_query']})
        else: unique[key] = row
    collected = list(unique.values()); live_funnel = funnel(collected, today)
    accepted = [r for r in collected if not disposition(r, today)]
    comparisons = {}
    baseline_v2 = json.loads(git_bytes('site/api/v2/events.json'))['data']
    for city in sorted(TARGETS):
        old = [r for r in old_rows if r['city_name'] == city and not disposition(r, today)]
        old_ids = {r['event_id'] for r in old}
        new = [r for r in new_rows + accepted if r['city_name'] == city and not disposition(r, today)]
        dedup = {r['event_id']: r for r in new}
        canonical = [r for r in baseline_v2 if r['city_name']==city and r.get('availability')=='candidate' and any(
            s['end_at'] >= today.isoformat() and s['start_at'] <= (today+timedelta(days=365)).isoformat() for s in r.get('sessions',[]))]
        comparisons[city] = {'old_event_ids': sorted(r['event_id'] for r in canonical), 'old_news_event_ids':sorted(old_ids), 'new_valid_event_ids': sorted(set(dedup) - old_ids),
                             'official_only_event_ids': [r['event_id'] for r in official if r['city_name'] == city and not any(
                                 r['event_name'] == n['event_name'] and r['start_at'] == n.get('start_at') for n in dedup.values())],
                             'note': 'Official-only uses explicit name/date identity; unresolved near duplicates require review.'}
    benchmark = json.loads((ROOT / 'tests/fixtures/phase2-benchmark.json').read_text(encoding='utf8'))
    benchmark_results = []
    for sample in benchmark['data']:
        hits = [r for r in accepted if r.get('city_name') == sample.get('city_name') and r.get('start_at') == sample['start_at'] and all(t in r['event_name'] for t in sample['terms'])]
        primary = [r for r in official if r.get('source_id') == sample['source_id'] and r['start_at'] == sample['start_at'] and r['end_at'] == sample['end_at']]
        benchmark_results.append(dict(sample, rss_found=bool(hits), official_found=bool(primary), discovered=bool(hits or primary)))
    after = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / 'site/api').rglob('*.json')}
    if before != after: raise RuntimeError('production_snapshot_modified')
    calendar = json.loads(git_bytes('site/api/v1/activities.json'))
    linked = {lead for row in calendar['data'] for lead in row.get('related_lead_ids',[])}
    registration_audit = {'registered_activities':len(calendar['data']), 'explicitly_linked_news':len(linked),
                          'safe_future_unregistered_lead_ids':[r['event_id'] for r in new_rows if not disposition(r,today) and r['event_id'] not in linked],
                          'note':'Lack of registration is not rejection: eligible pending leads flow through discovery_candidates; titles alone cannot establish canonical activity identity.'}
    unresolved_duplicates = []
    groups = collections.defaultdict(list)
    for row in collected:
        if row.get('start_at'): groups[(row['city_name'],row['event_type'],row['start_at'])].append(row['event_id'])
    unresolved_duplicates = [ids for ids in groups.values() if len(ids)>1]
    city_counts = {}
    for city in sorted(TARGETS):
        rows = [r for r in collected if r['city_name']==city]
        city_counts[city] = {'raw_observations':sum(r['city_name']==city for r in observations),'unique_news':len(rows),
                             'funnel':{k:v for k,v in funnel(rows,today).items() if k!='records'},
                             'official_events':sum(r['city_name']==city for r in official)}
    report = {'observed_at': stamp, 'as_of': today.isoformat(), 'horizon_days':365, 'baseline_commit':BASE,
              'original_snapshot_count':len(original['data']), 'original_snapshot_sha256': hashlib.sha256(git_bytes('site/api/v1/hotspots.json')).hexdigest(),
              'production_unchanged':before == after, 'production_hashes':before,
              'sources':checks, 'selector_diagnostics':selectors, 'local_test_center_evidence':location_evidence,
              'historical_before':old_audit, 'historical_after':new_audit, 'recognition_changes':changes,
              'registration_audit':registration_audit, 'unresolved_same_city_type_date_groups':unresolved_duplicates,
              'rss_raw_observations':len(observations), 'duplicate_query_observations':len(duplicates), 'duplicates':duplicates,
              'per_city':city_counts,
              'live_funnel':live_funnel, 'comparisons':comparisons, 'benchmark':benchmark_results,
              'benchmark_recall':sum(r['discovered'] for r in benchmark_results)/len(benchmark_results),
              'benchmark_rss_recall':sum(r['rss_found'] for r in benchmark_results)/len(benchmark_results),
              'benchmark_limit':'Purposive sample. Most official URLs are explicitly seeded from manual research: official result measures extraction success, not autonomous discovery recall. Holdout is unseeded. National dates do not imply city demand.',
              'manual_review_queue':[r for r in new_audit['records'] if r['accepted'] and (r['start_at'] or '')[:4] > str(today.year)]}
    for name, data in [('report',report),('rss-candidates',collected),('official-events',official),('raw-observations',observations)]:
        collect.write_json(output/(name+'.json'),data)
    lines = ['# Phase 2 三城真实采集与验收', '',
             '观察日：'+today.isoformat()+'；窗口首尾包含，截止 '+(today+timedelta(days=365)).isoformat()+'。',
             '固定基线 ca514b5；所有新闻重放使用同一观察日。原始页面的 checked_at 是实际获取时间，replayed 不刷新证据时间。', '',
             '## 真实采集', '', '| 城市 | RSS命中 | 去重新闻 | 明确举办日期 | 有效未来候选 | 官方日期记录 |', '|---|---:|---:|---:|---:|---:|']
    for city, stats in city_counts.items():
        lines.append(f"| {city} | {stats['raw_observations']} | {stats['unique_news']} | {stats['funnel']['explicit_event_dates']} | {stats['funnel']['valid_future_candidates']} | {stats['official_events']} |")
    lines += ['',f'跨查询重复命中 {len(duplicates)} 条；此数是重复观察次数，不是独立重复活动数。同城同类同日只能进入疑似重复队列，不能据此合并。',
              '全国统一日程 '+str(sum(r['city_name'] is None for r in official))+' 项单独列出；不复制到三城，不估计规模/住宿增量。', '',
              '## 官方事件清单', '', '| 城市/范围 | 名称 | 开始 | 结束 | 来源 |', '|---|---|---|---|---|']
    for r in official:
        lines.append(f"| {r['city_name'] or '全国'} | {r['event_name']} | {r['start_at']} | {r['end_at']} | [{r['source_authority']}]({r['source_url']}) |")
    lines += ['', '## 17079条候选转化漏斗', '', '| 阶段 | 输入 | 留存 | 损失 |', '|---|---:|---:|---:|']
    for stage in new_audit['waterfall']:
        lines.append(f"| {stage['stage']} | {stage['input']} | {stage['retained']} | {stage['lost']} |")
    lines += ['',f"重放前后有效未来新闻候选 {old_audit['valid_future_candidates']} → {new_audit['valid_future_candidates']}。分类/过滤结果变化 {len(changes)} 条，全部逐条见 report.json。",
              '默认未来API和本验收口径不同：本验收要求明确 event 日期角色；ambiguous 留待复核，不能视为已确认错误。',
              f"原活动登记 {registration_audit['registered_activities']} 项；严格有效且未显式登记关联的新闻 {len(registration_audit['safe_future_unregistered_lead_ids'])} 条，仍可经 discovery_candidates 进入日历，不能把未登记等同于丢弃。", '',
              '合理过滤：无明确日期、历史事件、报名/缴费/成绩节点、城市未证实、条件安排、取消/延期。',
              '确认并修复：成绩查询/证书日期不得充当考试日；宽泛学校词不得覆盖具体会议主题；网页 topic_catalog 的 key 应被消费，不能只识别 topic。',
              '未逐条核实全部新闻真实性；跨城冲突、日期歧义和相似活动保留为复核队列，不把所有过滤记录宣称为合理或错误。', '',
              '## 同点对照与独立基准', '', '| 城市 | 原v2候选身份 | 原严格新闻 | 新增严格新闻 | 官方补充记录 |', '|---|---:|---:|---:|---:|']
    for city,c in comparisons.items():
        lines.append(f"| {city} | {len(c['old_event_ids'])} | {len(c['old_news_event_ids'])} | {len(c['new_valid_event_ids'])} | {len(c['official_only_event_ids'])} |")
    lines += ['', '原v2是全部主题的候选身份；新检索重点为考试、假期和会议，两列不构成完整版本召回率。官方与新闻未完全绑定身份，官方补充仍可能与旧记录重复。',
              f"人工基准 {len(benchmark_results)} 项：RSS自主命中 {sum(r['rss_found'] for r in benchmark_results)}；官方定向提取命中 {sum(r['official_found'] for r in benchmark_results)}。",
              '基准在提取前从独立官方检索人工抄录。大部分网址随后作为显式种子传给适配器，因此官方命中是定向提取成功率，不是无偏自主发现率。ICCLL保留为未接入holdout；小样本不推断全网召回率。', '',
              '未覆盖的已知事件：']
    for r in benchmark_results:
        if not r['discovered']: lines.append('- '+r['source_id']+'：'+r['start_at']+' 至 '+r['end_at']+'；'+str(r.get('city_name')))
    lines += ['', '## 来源失败与限制', '']
    for c in checks:
        if c['status']!='ok': lines.append('- '+str(c.get('source_id',c.get('city')))+'：'+c['url']+'；'+str(c.get('error')))
    lines += ['', '失败未关闭TLS验证、未绕过验证码或访问限制。天津考试另读市政府公开公告、国考另读政府转载，明确保留来源层级。HTTP读取成功只证明响应可读，不保证官网内容已遍历或全部规则适配。',
              '三城各考试子类均已检索；没有当前正文与明确举办日期的高考/中考、事业单位、教资、职业资格、省考等仍列来源覆盖缺口，不按年度规律生成日期。校历按学段区分；春秋假未外推统一日期。会议索引相关链接仅列后续检查队列。', '',
              '## 交付与复现', '',
              '原始响应：raw/*.gz（解压后的SHA-256与 report.json 对应）；raw-observations.json 是每次RSS命中；rss-candidates.json 是新闻身份去重；official-events.json 是正文规则命中；report.json 包含全部逐条损失、日期/城市原因、对照身份、基准漏项和生产哈希。',
              '生产快照哈希检查：'+str(before==after)+'。PR合并最新main时直接保留main快照，Phase 2没有改写 site/api。事件全部 pending，无经营数据库调用。',
              '命令：python -m scripts.phase2_acceptance --output docs/phase2-evidence-2026-11-26 --as-of 2026-11-26 --reuse-evidence',
              '下一步：补全会议/考试索引翻页与正文下钻；补充独立随机holdout、地方考点、逐事件跨源身份关联和取消/延期复查。当前自主发现指标不足，尚未通过业务完整覆盖验收。']
    (output/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k in ('observed_at','production_unchanged','original_snapshot_count','rss_raw_observations','duplicate_query_observations','benchmark_recall')},ensure_ascii=False))

if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('--output',type=Path,required=True); p.add_argument('--as-of',type=date.fromisoformat,required=True); p.add_argument('--reuse-evidence',action='store_true')
    args=p.parse_args(); run(args.output,args.as_of,reuse=args.reuse_evidence)
