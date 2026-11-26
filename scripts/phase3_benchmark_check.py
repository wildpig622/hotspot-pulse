"""Read evaluation-only reference URLs AFTER discovery; never emit discoveries."""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
from . import collect
from .phase3_discovery import ROOT,Reader,document,safe_output


def run(output):
    output=safe_output(output);path=ROOT/'tests/fixtures/phase3-benchmark.json'
    packet=json.loads(path.read_text(encoding='utf8'));reader=Reader(output);urls=list(dict.fromkeys(r['url'] for r in packet['data']))
    def read(url):
        body,check=reader.fetch(url,'benchmark_validation_only')
        title,text,_=document(body) if body else ('','',[])
        return {'url':url,'access':check,'title':title,'body_text':text,'article_body_available':len(text.strip())>100,'human_acceptance_status':'not_reviewed'}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:rows=list(pool.map(read,urls))
    collect.write_json(output/'bodies.json',{'benchmark_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'evaluation_only':True,'data':rows})
    collect.write_json(output/'run.json',{'checks':reader.checks,'evaluation_only':True})
    print(json.dumps({'unique_reference_urls':len(urls),'bodies_read':sum(r['article_body_available'] for r in rows)}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args();run(args.output)
