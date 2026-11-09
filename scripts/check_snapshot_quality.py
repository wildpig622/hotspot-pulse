"""Check the complete public snapshot before committing or publishing it."""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.parse import parse_qs

try:
    from . import collect
except ImportError:
    import collect


def check_snapshot(api: Path, require_full_scope: bool = False, max_age_hours: float | None = None,
                   require_discovery_calendar: bool = False, require_source_calendars: bool = False,
                   require_city_calendar: bool = False, require_expanded_queries: bool = False) -> dict:
    payloads = {name: json.loads((api / (name + '.json')).read_text(encoding='utf-8'))
                for name in ('hotspots', 'activities', 'coverage', 'cities', 'health')}
    leads = payloads['hotspots']['data']
    calendar = payloads['activities']
    activities = calendar['data']
    signals = calendar.get('source_market_signals', [])
    source_candidates = calendar.get('source_candidates', [])
    official_candidates = calendar.get('official_candidates', [])
    cities = collect.configured_cities()
    city_names = {city['city_name'] for city in cities}
    topic_names = {topic['key'] for topic in collect.FEED_TOPICS}
    expected = {(city, topic) for city in city_names for topic in topic_names}
    errors = []

    def require(condition, message):
        if not condition:
            errors.append(message)

    candidates = calendar.get('discovery_candidates', [])
    if require_discovery_calendar or 'discovery_candidates' in calendar:
        try:
            from .activity_registry import build_discovery_candidates
        except ImportError:
            from activity_registry import build_discovery_candidates
        expected_candidates = build_discovery_candidates(leads, activities)
        # Compare every projected field as well as identity: discovery must not
        # invent body checks, change review status, or drop a whole city's leads.
        require('discovery_candidates' in calendar, 'dated news handoff has not been built')
        require(candidates == expected_candidates, 'dated news handoff is missing, duplicated, or modified')
        require(calendar['meta'].get('discovery_candidate_count') == len(candidates), 'dated news total mismatch')

    for kind, rows in (('news', leads), ('activity', activities), ('source_market', signals), ('source_candidate', source_candidates), ('official_candidate',official_candidates)):
        ids = [row.get('event_id') for row in rows]
        require(all(ids) and len(ids) == len(set(ids)), kind + ': missing or duplicate IDs')
        for row in rows:
            key = str(row.get('event_id'))
            require(row.get('review_status') in {'pending', 'verified', 'rejected'}, key + ': invalid review status')
            if kind != 'source_market':
                require(row.get('city_name') in city_names, key + ': city outside catalogue')
            else:
                require(row.get('record_kind') == 'source_market_signal', key + ': origin signal mislabeled')
                require(row.get('city_name') not in city_names, key + ': origin signal duplicates an operating city')
                require(bool(set(row.get('impact_destination_cities', [])) & city_names), key + ': no known observation destination')
            if kind == 'source_candidate':
                require(row.get('record_kind') == 'source_candidate' and row.get('evidence_level') == 'ticketing_listing', key + ': listing evidence mislabeled')
                require(row.get('date_confidence') == 'source_listing' and row.get('event_date_role') == 'event', key + ': invalid listing date role')
                context = row.get('source_context', {})
                require(context.get('title') == row.get('event_name') and context.get('start_at') == row.get('start_at') and context.get('venue_name') == row.get('venue_name'), key + ': listing context mismatch')
                require(context.get('city_label') in {row.get('city_name'), str(row.get('city_name')).removesuffix('市')}, key + ': listing city context mismatch')
            start = row.get('start_at')
            end = row.get('end_at') or start
            if start:
                try:
                    require(date.fromisoformat(end) >= date.fromisoformat(start), key + ': reversed dates')
                except (ValueError, TypeError):
                    errors.append(key + ': invalid calendar dates')
            if kind == 'news':
                require(bool(row.get('content_kind')) and bool(row.get('event_date_role')), key + ': missing date/content semantics')
                # Parser exclusions must also protect the serialized snapshot.
                if collect.CONDITIONAL_EVENT_PATTERN.search(row.get('event_name', '')):
                    require(not collect.is_upcoming_event(row, collect.now_utc().astimezone(collect.BEIJING).date()), key + ': unconfirmed item in future view')
                continue
            require(bool(row.get('sessions')), key + ': no sessions')
            for session in row.get('sessions', []):
                try:
                    require(date.fromisoformat(session.get('end_at') or session['start_at']) >= date.fromisoformat(session['start_at']), key + ': reversed session')
                except (ValueError, TypeError, KeyError):
                    errors.append(key + ': invalid session date')
            require(bool(row.get('sources')), key + ': missing evidence')
            readable = [source for source in row.get('sources', []) if source.get('access_status') in {'body_read', 'historical_body_read', 'official_listing_read'}]
            require(bool(readable), key + ': no readable source evidence')
            for source in readable:
                parsed = urlparse(source.get('source_url', ''))
                require(parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.username and not parsed.password, key + ': unsafe evidence URL')
                try:
                    stamp = datetime.fromisoformat(source['checked_at'].replace('Z', '+00:00'))
                    require(stamp.tzinfo is not None, key + ': evidence timestamp lacks timezone')
                except (ValueError, KeyError):
                    errors.append(key + ': invalid evidence timestamp')

    require(payloads['hotspots']['meta']['candidate_count'] == len(leads), 'news total mismatch')
    require(calendar['meta']['activity_count'] == len(activities), 'activity total mismatch')
    require(calendar['meta']['verified_count'] == sum(row.get('review_status') == 'verified' for row in activities), 'verified total mismatch')
    require({row['city_name'] for row in payloads['cities']['data']} == city_names, 'city catalogue mismatch')
    cells = payloads['coverage']['data']
    require(len(cells) == len(expected) and {(row['city_name'], row['topic']) for row in cells} == expected, 'coverage matrix is incomplete or duplicated')
    if 'discovery_candidates' in calendar:
        for cell in cells:
            count = sum(row['city_name'] == cell['city_name'] and row['event_type'] == cell['topic'] for row in candidates)
            require(cell.get('dated_news_candidate_count') == count, 'city/topic dated-news coverage mismatch: ' + cell['city_name'] + '/' + cell['topic'])
            if 'source_candidates' in calendar:
                count = sum(row['city_name'] == cell['city_name'] and row['event_type'] == cell['topic'] for row in source_candidates)
                require(cell.get('source_candidate_count') == count, 'city/topic listing coverage mismatch: ' + cell['city_name'] + '/' + cell['topic'])
    source_checks = calendar.get('source_checks', [])
    if 'source_candidates' in calendar or require_source_calendars:
        require(calendar['meta'].get('source_candidate_count') == len(source_candidates), 'source listing total mismatch')
    if require_source_calendars:
        routes = json.loads((collect.ROOT / 'config/source-calendars.json').read_text(encoding='utf8'))['data']
        codes = {row['city_name']: str(row['city_code']) for row in routes}
        require(set(codes) == city_names and len(routes) == len(city_names), 'source calendar route catalogue mismatch')
        require(len(source_checks) == len(city_names) and {r['city_name'] for r in source_checks} == city_names, 'source calendar cities missing or duplicated')
        for check in source_checks:
            pages = check.get('pages', [])
            require(check.get('status') == 'ok' and bool(pages) and all(p.get('status') == 'ok' for p in pages), 'source calendar read failed: ' + check['city_name'])
            urls = [urlparse(p.get('url', '')) for p in pages]
            require(all(p.scheme == 'https' and p.hostname == 'www.showstart.com' and p.path == '/event/list' and parse_qs(p.query).get('cityCode') == [codes.get(check['city_name'])] for p in urls), 'source calendar route mismatch')
            numbers=[int(parse_qs(p.query).get('pageNo',['0'])[0]) for p in urls]
            require(numbers == list(range(1,len(numbers)+1)), 'source calendar page duplicated or missing')
            if check.get('pagination'):
                require(check['pagination'].get('stop_reason') in {'exhausted','repeated_page','record_limit','page_limit'}, 'invalid pagination completion state')
    if require_city_calendar:
        try:
            from .activity_registry import activity_is_future
        except ImportError:
            from activity_registry import activity_is_future
        today = collect.now_utc().astimezone(collect.BEIJING).date()
        for name in city_names:
            require(any(row.get('city_name') == name and row.get('review_status') != 'rejected' and activity_is_future(row, today) for row in activities + candidates + source_candidates), 'no dated future calendar record: ' + name)
    feeds = payloads['health'].get('feed_results', [])
    if require_full_scope:
        require(len(feeds) == len(expected) and {(row['city_name'], row.get('topic')) for row in feeds} == expected, 'full city/topic collection was not executed')
        require(all(row.get('status') == 'ok' for row in feeds), 'some city/topic collection requests failed')
        require(payloads['health'].get('successful_feeds') == len(expected), 'full-scope success count mismatch')
    if require_expanded_queries:
        for feed in feeds:
            queries = feed.get('query_results', [])
            ordinary=[q for q in queries if q.get('route')!='planning_month']
            require(len(ordinary) == 2 and {q.get('route') for q in ordinary} == {'year_lookback', 'upcoming_months'}, 'expanded query routes missing or duplicated')
            months=payloads['hotspots']['meta'].get('monitoring_complete_months')
            if months:
                start=date.fromisoformat(payloads['hotspots']['meta']['monitoring_window']['start_at'])
                expected_months={d.strftime('%Y-%m') for d in collect.future_months(start,{'monitoring_complete_months':months})}
                monthly=[q for q in queries if q.get('route')=='planning_month']
                require(len(monthly)==months and {q.get('month') for q in monthly}==expected_months,'planning month queries missing or duplicated')
            require(all(q.get('status') == 'ok' for q in queries), 'expanded query route failed')
        require(len(feeds) == len(expected), 'expanded query city/topic cells missing')
    if max_age_hours is not None:
        try:
            collected = datetime.fromisoformat(payloads['hotspots']['meta']['last_collection_at'].replace('Z', '+00:00'))
            age = (collect.now_utc() - collected).total_seconds() / 3600
            require(-0.1 <= age <= max_age_hours, 'collection snapshot is stale or has a future timestamp')
        except (KeyError, ValueError, TypeError):
            errors.append('collection time is missing or invalid')
    require(payloads['coverage']['meta'].get('coverage_status') == 'partial', 'must not claim exhaustive web coverage')
    return {'status': 'FAIL' if errors else 'PASS', 'errors': errors, 'news_count': len(leads),
            'activity_count': len(activities), 'source_market_signal_count': len(signals),
            'discovery_candidate_count': len(candidates),
            'source_candidate_count': len(source_candidates), 'source_calendar_city_count': len(source_checks),
            'coverage_cells': len(cells), 'full_scope_required': require_full_scope,
            'collection_at': payloads['hotspots']['meta'].get('last_collection_at'),
            'verified_news': sum(row.get('review_status') == 'verified' for row in leads),
            'verified_activities': sum(row.get('review_status') == 'verified' for row in activities),
            'fact_completeness': 'NOT_CLAIMED', 'automatic_verified_promotions': 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot-dir', type=Path, default=collect.SITE_API)
    parser.add_argument('--require-full-scope', action='store_true')
    parser.add_argument('--max-age-hours', type=float)
    parser.add_argument('--require-discovery-calendar', action='store_true')
    parser.add_argument('--require-source-calendars', action='store_true')
    parser.add_argument('--require-city-calendar', action='store_true')
    parser.add_argument('--require-expanded-queries', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = check_snapshot(args.snapshot_dir, args.require_full_scope, args.max_age_hours, args.require_discovery_calendar,
                            args.require_source_calendars, args.require_city_calendar, args.require_expanded_queries)
    if args.report:
        collect.write_json(args.report, result)
    print(json.dumps(result, ensure_ascii=False))
    return int(result['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
