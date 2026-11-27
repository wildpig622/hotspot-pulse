"""Package original successful response bytes for reliable review transport."""
import argparse
import gzip
import hashlib
import json
import zipfile
from pathlib import Path
from . import collect
from .phase3_discovery import archive_bytes,safe_output


def pack(output):
    output=safe_output(output);objects={};kinds={};checks=0
    for path in sorted(output.glob('*/run.json')):
        for check in json.loads(path.read_text(encoding='utf8')).get('checks',[]):
            if check['status']!='ok' or not check.get('raw_file'):continue
            raw=archive_bytes(path.parent,check)
            if raw is None or hashlib.sha256(gzip.decompress(raw)).hexdigest()!=check['sha256']:raise ValueError('response_hash_mismatch: '+check['url'])
            key=path.parent.name+'/'+check['raw_file'].replace('\\','/')
            if '..' in Path(key).parts:raise ValueError('unsafe_archive_path')
            objects[key]=raw;kinds[key]={'archive_kind':check.get('archive_kind','original_response'),'original_response_sha256':check.get('original_response_sha256',check['sha256'])};checks+=1
    # Verify all source bytes before replacing a prior transport bundle.
    manifest=[]
    with zipfile.ZipFile(output/'responses.zip','w',compression=zipfile.ZIP_STORED) as archive:
        for key,raw in sorted(objects.items()):
            info=zipfile.ZipInfo(key,date_time=(1980,1,1,0,0,0));info.external_attr=0o100644<<16
            archive.writestr(info,raw)
            manifest.append({'path':key,'bytes':len(raw),'gzip_sha256':hashlib.sha256(raw).hexdigest(),'body_sha256':hashlib.sha256(gzip.decompress(raw)).hexdigest(),**kinds[key]})
    collect.write_json(output/'response-manifest.json',{'format':'ZIP_STORED_archived_gzip_bytes','successful_request_checks':checks,
        'unique_response_objects':len(objects),'archive_sha256':hashlib.sha256((output/'responses.zip').read_bytes()).hexdigest(),'entries':manifest})
    return {'successful_request_checks':checks,'unique_response_objects':len(objects),'bundle_bytes':(output/'responses.zip').stat().st_size}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args();print(json.dumps(pack(args.output)))
