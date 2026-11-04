"""Stage collection, validate, then publish data or a truthful cached-data health state."""
import argparse
import json
import shutil
import tempfile
from pathlib import Path
from . import collect
from .check_snapshot_quality import check_snapshot
from .event_feed import build_files
from .validate_event_feed import validate


def run(api, collector=None, checker=None, now=None):
    collector=collector or collect.run_collection
    checker=checker or check_snapshot
    now=now or collect.now_utc()
    old_meta=collect.load_json(api/'hotspots.json',{}).get('meta',{})
    last_success=collect.load_json(api/'health.json',{}).get('last_successful_collection_at') or old_meta.get('last_collection_at')
    errors=[];attempt_health={};success=False
    with tempfile.TemporaryDirectory() as temp:
        staged=Path(temp)/'api';shutil.copytree(api.parent,staged)
        target=staged/'v1';original=collect.SITE_API
        try:
            collect.SITE_API=target
            outcome=collector(include_sources=True,include_details=True,include_official=True)
            attempt_health=collect.load_json(target/'health.json',{})
            if outcome:errors.append('collection_failed')
            else:
                result=checker(target,require_full_scope=True,require_discovery_calendar=True,require_source_calendars=True,require_expanded_queries=True,max_age_hours=24)
                errors.extend(result['errors'])
                # Existing human decisions and first-observation times cannot be
                # silently replaced by a collector refresh.
                before=collect.load_json(api/'activities.json',{})
                after=collect.load_json(target/'activities.json',{})
                new_rows={r['event_id']:r for layer in ('data','source_candidates','official_candidates') for r in after.get(layer,[])}
                for layer in ('data','source_candidates','official_candidates'):
                    for row in before.get(layer,[]):
                        incoming=new_rows.get(row['event_id'])
                        protected=('event_name','city_name','event_type','venue_name','start_at','end_at','sessions','review_status','event_status','first_seen_at')
                        if row.get('review_status') in {'verified','rejected'} and (incoming is None or any(incoming.get(k)!=row.get(k) for k in protected)):
                            errors.append('human_review_overwrite:'+row['event_id'])
                if not errors:
                    stamp=collect.load_json(target/'hotspots.json',{})['meta']['last_collection_at']
                    attempt_health.update(data_updated=True,last_successful_collection_at=stamp)
                    collect.write_json(target/'health.json',attempt_health)
                    built=build_files(target,now)
                    errors.extend(validate(built['events'],built['changes'])['errors'])
                success=not errors
        except Exception as exc:errors.append(type(exc).__name__)
        finally:collect.SITE_API=original
        if success:
            health=attempt_health
            stamp=collect.load_json(target/'hotspots.json',{})['meta']['last_collection_at']
            health.update(data_updated=True,last_successful_collection_at=stamp)
            calendar=collect.load_json(target/'activities.json',{})
            health['source_warning_count']=sum(r.get('status')!='ok' for field in ('official_source_checks','detail_checks') for r in calendar.get(field,[]))
            collect.write_json(target/'health.json',health)
            build_files(target,now)
            for source in staged.rglob('*.json'):
                destination=api.parent/source.relative_to(staged);destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination)
        else:
            # The unvalidated candidate files remain in the temporary directory.
            # Only health and metadata about the unchanged last-good data publish.
            health=collect.load_json(api/'health.json',{})
            health.update(status='failed',data_updated=False,last_run_at=collect.iso_utc(now),
                          last_successful_collection_at=last_success,collection_errors=errors,
                          note='本轮采集或质量检查未通过，保留上次可用数据；请按真实采集时间判断是否过期。',
                          attempted_feed_results=attempt_health.get('feed_results',[]))
            collect.write_json(api/'health.json',health)
            build_files(api,now)
    return {'collection_ok':success,'data_updated':success,'errors':errors,'last_successful_collection_at':stamp if success else last_success}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--snapshot-dir',type=Path,default=collect.SITE_API);parser.add_argument('--result',type=Path,required=True)
    args=parser.parse_args();result=run(args.snapshot_dir);collect.write_json(args.result,result);print(json.dumps(result,ensure_ascii=False))
