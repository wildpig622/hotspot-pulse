"""Reproducible stratified missing-date sample; unavailable bodies stay unknown."""
import argparse
import collections
import concurrent.futures
import hashlib
import json
import random
import re
from datetime import date
from pathlib import Path
from . import collect
from .phase2_acceptance import git_bytes
from .phase3_discovery import Reader,ROOT,safe_output,document,extract_article

def sample_rows(rows,n=200,seed=20261126):
    groups=collections.defaultdict(list)
    for row in rows:
        if not row.get('start_at'):
            city=row['city_name'] if row['city_name'] in {'西安市','济南市','天津市'} else '其他城市'
            groups[(city,row.get('event_type','other'))].append(row)
    rng=random.Random(seed);result=[];keys=sorted(groups)
    for group in groups.values():rng.shuffle(group)
    # Round-robin stratification deliberately oversamples sparse topic/city
    # strata; report inclusion counts, do not estimate population rates.
    while len(result)<n and any(groups.values()):
        for key in keys:
            if groups[key] and len(result)<n:result.append(groups[key].pop())
    return result

def run(output):
    output=safe_output(output);raw=git_bytes('site/api/v1/hotspots.json',ref='c4c2c52')
    samples=sample_rows(json.loads(raw)['data']);reader=Reader(output,0.6)
    def read(row):
        source=next((s['source_url'] for s in row.get('sources',[]) if s.get('source_url','').startswith('https://')),None)
        body,check=reader.fetch(source,'sample_article') if source else ('',{'status':'unavailable','error':'no_source_url'})
        title,text,_=document(body) if body else ('','',[])
        original_read=bool(body) and 'news.google.com' not in check.get('final_url',source or '') and len(text)>100
        if original_read:
            parsed=extract_article(body,{'id':'date-sample','scope':'unknown'},source,check['checked_at'],date(2026,11,26),row['event_name'])
        else:parsed=None
        return {'sample_id':row['event_id'],'stratum':{'city':row['city_name'] if row['city_name'] in {'西安市','济南市','天津市'} else '其他城市','topic':row.get('event_type')},
                'event_name':row['event_name'],'rss_summary':row.get('discovery_summary',''),'source_url':source,
                'access':check,'original_body_read':original_read,'body_text':text if original_read else None,
                'rule_extraction':parsed,'human_label':None,'human_evidence':None,
                'annotation_status':'awaiting_body_review' if original_read else 'unresolved_body_unavailable'}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:result=list(pool.map(read,samples))
    collect.write_json(output/'sample-200.json',{'seed':20261126,'method':'round_robin_city_topic_strata_without_replacement','population_sha256':hashlib.sha256(raw).hexdigest(),
        'original_body_read_count':sum(r['original_body_read'] for r in result),'sample_size':len(result),'data':result})
    collect.write_json(output/'checks.json',reader.checks)
    print(json.dumps({'samples':len(result),'original_bodies':sum(r['original_body_read'] for r in result)}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args();run(args.output)
