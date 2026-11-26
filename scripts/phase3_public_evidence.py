"""Remove contact details before exporting public-source evidence for review.

Keep original response bytes in the ignored local review directory. The public
copies retain original hashes, observation dates and event facts; they are
explicitly labelled derivatives, not original response bytes.
"""
import argparse
import gzip
import hashlib
import html
import json
import re
import unicodedata
from pathlib import Path
from . import collect
from .phase3_bundle import pack
from .phase3_discovery import ROOT,archive_bytes,safe_output

EMAIL=re.compile(r'(?<![\w.+-])[A-Z0-9._%+-]+\s*[@＠]\s*[A-Z0-9.-]+\.[A-Z]{2,}',re.I)
PHONE=re.compile(r'(?<![A-Za-z0-9])(?:\+?86[ -]?)?1[3-9](?:[ -]?\d){9}(?![A-Za-z0-9])|(?<![A-Za-z0-9])(?:\+?86[ -]?)?0\d{2,3}[-－— ]?\d{7,8}(?![A-Za-z0-9])')
PROTECTED={'event_id','source_record_id','event_name','city_name','city_slug','start_at','end_at','source_url','event_detail_url','url','final_url','entry_url','identity_url','sha256','original_response_sha256','path'}


def redact(text):
    counts={'email':0,'phone':0}
    def direct(value):
        for label,pattern in [('email',EMAIL),('phone',PHONE)]:
            value,n=pattern.subn('[CONTACT_'+label.upper()+'_REMOVED]',value);counts[label]+=n
        return value
    text=direct(text)
    # Map visible text back to original offsets. This catches contacts split
    # across inline tags or represented by character entities without turning
    # markup into text or exposing an encoded version of the contact.
    visible=[];positions=[]
    for token in re.finditer(r'<[^>]*>|&(?:#\d+|#x[0-9a-fA-F]+|\w+);|[\s\S]',text):
        value=token[0]
        if value.startswith('<'):
            if re.match(r'</?(?:p|div|br|tr|li|h[1-6])\b',value,re.I):visible.append('\n');positions.append(None)
            continue
        for char in unicodedata.normalize('NFKC',html.unescape(value)):visible.append(char);positions.append((token.start(),token.end()))
    joined=''.join(visible);changes=[]
    for label,pattern in [('email',EMAIL),('phone',PHONE)]:
        for match in pattern.finditer(joined):
            spans=sorted(set(p for p in positions[match.start():match.end()] if p is not None))
            if not spans:continue
            counts[label]+=1
            for i,(a,b) in enumerate(spans):changes.append((a,b,'[CONTACT_'+label.upper()+'_REMOVED]' if i==0 else ''))
    for a,b,replacement in sorted(set(changes),reverse=True):text=text[:a]+replacement+text[b:]
    return text,counts


def sanitize(original,output):
    original=Path(original).resolve();output=safe_output(output)
    if not original.is_relative_to(ROOT/'review') or original==output:raise ValueError('local_original_backup_required')
    checks_by_key={};counts={'email':0,'phone':0};changed_responses=0
    for file in sorted(original.glob('*/run.json')):
        for check in json.loads(file.read_text(encoding='utf8')).get('checks',[]):
            if check['status']!='ok' or not check.get('raw_file'):continue
            raw=archive_bytes(file.parent,check);source=gzip.decompress(raw)
            if hashlib.sha256(source).hexdigest()!=check['sha256']:raise ValueError('original_hash_mismatch')
            text=source.decode(check.get('encoding','utf8'),errors='replace');clean,n=redact(text)
            changed=any(n.values());updated=dict(check)
            if changed:
                public=clean.encode('utf8');digest=hashlib.sha256(public).hexdigest()
                relative='raw/'+digest+'.gz';target=output/file.parent.name/relative;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(gzip.compress(public,mtime=0))
                updated.update(raw_file=relative,sha256=digest,encoding='utf8',original_response_sha256=check['sha256'],
                    original_response_encoding=check.get('encoding','utf8'),archive_kind='contact_redacted_derivative')
                changed_responses+=1
            else:updated['archive_kind']='original_response_no_contact_match'
            checks_by_key[(check['url'],check['checked_at'])]=updated
            for k,v in n.items():counts[k]+=v
    def walk(value,key=None):
        if isinstance(value,dict):
            if value.get('raw_file') and (value.get('url'),value.get('checked_at')) in checks_by_key:
                value={**value,**checks_by_key[(value['url'],value['checked_at'])]}
            return {k:walk(v,k) for k,v in value.items()}
        if isinstance(value,list):return [walk(v,key) for v in value]
        if isinstance(value,str) and key not in PROTECTED:
            clean,n=redact(value)
            for k,v in n.items():counts[k]+=v
            return clean
        return value
    for file in sorted(original.rglob('*')):
        if not file.is_file() or 'raw' in file.relative_to(original).parts or file.suffix not in {'.json','.txt'}:continue
        if file.name=='response-manifest.json':continue
        target=output/file.relative_to(original);target.parent.mkdir(parents=True,exist_ok=True)
        if file.suffix=='.json':collect.write_json(target,walk(json.loads(file.read_text(encoding='utf8'))))
        else:
            source=file.read_text(encoding='utf8')
            try:clean=json.dumps(walk(json.loads(source)),ensure_ascii=False,indent=2)+'\n'
            except json.JSONDecodeError:clean,n=redact(source)
            target.write_text(clean,encoding='utf8',newline='\n')
    result=pack(output)
    collect.write_json(output/'privacy-review.json',{'policy':'no_personal_contact_export','original_backup':'ignored local review/phase3-original-evidence',
        'contact_redacted_response_checks':changed_responses,'contact_replacements':counts,
        'original_response_hashes_retained':True,'public_archive_contains_derivatives':True,
        'event_identity_dates_cities_and_names_preserved':True,'bundle':result,
        'review_note':'Public review copies only; original source bytes were retained locally and are not added to this PR change.'})
    return {'response_checks_redacted':changed_responses,'replacements':counts,**result}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--original',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    print(json.dumps(sanitize(args.original,args.output)))
