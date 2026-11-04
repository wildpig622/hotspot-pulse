"""Gate the explicitly authorized service schedule and manual full-pipeline runs."""
import json
import os
import re
from pathlib import Path

def request_errors(environ, config, event=None):
    errors=[]
    if not config.get('enabled'):errors.append('service_disabled')
    if environ.get('GITHUB_REF')!='refs/heads/main':errors.append('main_branch_required')
    actual=environ.get('GITHUB_SHA','')
    if not re.fullmatch('[0-9a-f]{40}',actual):errors.append('full_workflow_sha_required')
    kind=environ.get('GITHUB_EVENT_NAME')
    if kind=='schedule':
        if (event or {}).get('schedule')!=config['cron_utc']:errors.append('schedule_not_authorized')
    elif kind=='workflow_dispatch':
        if environ.get('REQUESTED_SHA')!=actual:errors.append('commit_mismatch')
        if environ.get('REQUEST_CONFIRMATION')!='REFRESH_AND_PUBLISH_PENDING':errors.append('explicit_confirmation_required')
    else:errors.append('event_not_authorized')
    return errors

if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    config=json.loads((root/'config/service.json').read_text(encoding='utf8'))
    event=json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text(encoding='utf8')) if os.environ.get('GITHUB_EVENT_PATH') else {}
    errors=request_errors(os.environ,config,event)
    print(json.dumps({'status':'DENIED' if errors else 'AUTHORIZED','errors':errors}))
    raise SystemExit(bool(errors))
