"""Run the pinned third-party tool without private cookies/config/browser state."""
import argparse
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from .phase3_discovery import ROOT,safe_output
from . import collect

def child(args):
    skill=ROOT/'review/last30days-skill-cn';sys.path.insert(0,str(skill/'scripts'))
    from lib import env
    # The tool is tested as installed, but no account configuration, private
    # credentials or existing browser session is consumed in this experiment.
    env.get_config=lambda:{key:None for key in env.CONFIG_KEYS}
    env.discover_xiaohongshu_mcp=lambda *a,**k:None
    os.environ['LAST30DAYS_DISABLE_BROWSER']='1'
    spec=importlib.util.spec_from_file_location('last30days_isolated',skill/'scripts/last30days.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    sys.argv=['last30days']+args;module.main()

def run(output,focused=False):
    output=safe_output(output);skill=ROOT/'review/last30days-skill-cn'
    sha=subprocess.check_output(['git','-c','safe.directory='+skill.as_posix(),'rev-parse','HEAD'],cwd=skill).decode().strip()
    tasks=[['--diagnose','--emit','json','--no-browser'],['--hot','--emit','json','--no-browser','--timeout','60']]
    config=json.loads((ROOT/'config/phase3-discovery.json').read_text(encoding='utf8'))
    topics=config['public_search_tasks'] if not focused else [city+' '+task for city in ['西安','济南','天津'] for task in ['演唱会 加场','漫展 应援']]
    if focused:tasks=[]
    for topic in topics:
        tasks.append([topic,'--search','weibo,bilibili,xiaohongshu,douyin,baidu,toutiao','--days','30','--as-of','2026-11-26','--no-cache','--no-browser','--timeout','70','--emit','json'])
    runs=[]
    for i,args in enumerate(tasks):
        started=time.monotonic();stamp=collect.iso_utc(collect.now_utc())
        command=[sys.executable,'-c',"import sys;sys.path.insert(0,'.');from scripts.phase3_platforms import child;child(sys.argv[1:])"]+args
        try:
            result=subprocess.run(command,cwd=ROOT,capture_output=True,timeout=90)
            stdout=result.stdout.decode('utf8',errors='replace');stderr=result.stderr.decode('utf8',errors='replace')
            code=result.returncode
        except subprocess.TimeoutExpired as exc:
            stdout=(exc.stdout or b'').decode('utf8',errors='replace');stderr='experiment_wall_timeout';code=124
        # Avoid Windows text translation turning captured CRLF into CRCRLF.
        (output/f'run-{i}.stdout.txt').write_text(stdout.replace('\r\n','\n').rstrip()+'\n',encoding='utf8',newline='\n')
        (output/f'run-{i}.stderr.txt').write_text(stderr.replace('\r\n','\n').rstrip()+'\n',encoding='utf8',newline='\n')
        runs.append({'args':args,'checked_at':stamp,'exit_code':code,'elapsed_seconds':round(time.monotonic()-started,3),
                     'stdout_file':f'run-{i}.stdout.txt','stderr_file':f'run-{i}.stderr.txt'})
        collect.write_json(output/'runs.json',{'tool_repo':'https://github.com/Jesseovo/last30days-skill-cn','commit':sha,'credentials_used':False,'browser_used':False,'captured_text_newlines':'LF normalized','runs':runs})
    print(json.dumps(runs,ensure_ascii=True))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--focused',action='store_true');args=parser.parse_args();run(args.output,args.focused)
