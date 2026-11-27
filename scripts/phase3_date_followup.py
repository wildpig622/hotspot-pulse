"""Separately rediscovered publisher bodies, not a bypass of Google robots.

These four articles were located by independent title searches. This is an
assistant annotation draft for human review, not 200 completed human labels.
"""
import argparse
from datetime import date
from pathlib import Path
from . import collect
from .event_observations import evidence_gate
from .phase3_discovery import Reader, safe_output, extract_article

CASES=[
 {'sample_id':'evt_533b76a8ac73','url':'https://epaper.tianjinwe.com/tjrb/html/2026-11/03/content_143098_3977805.htm',
  'label':'historical_or_undetermined','reason':'日前在我市召开，没有绝对活动日期；不能用报纸日期代替活动日。','draft':None,'match':'title_match'},
 {'sample_id':'evt_9a7d22816f9c','url':'https://jnxxq.jinan.gov.cn/col/col122860/art/2026/art_754579fba3924815a84452abce6a259a.html',
  'label':'rss_missing_body_has_date','reason':'正文有10月14日至16日；2026年历史活动，不能流入未来事件。','match':'title_match',
  'draft':{'start_at':'2026-10-14','end_at':'2026-10-16','quote':'10月14日至16日','start_at_token':'10月14日','end_at_token':'16日','year_quote':'2026人工智能产业大会','date_role':'event'}},
 {'sample_id':'evt_3a01f3a6a86f','url':'https://finance.sina.cn/2026-11-09/detail-iniycrzw6539502.d.html',
  'label':'rss_missing_body_has_date','reason':'正文11月7日至8日，实际举办地成都；既是过去事件也不是三城现场需求。','match':'official_media_reprint',
  'draft':{'start_at':'2026-11-07','end_at':'2026-11-08','quote':'11月7日至8日，2026年全国幼儿手球嘉年华','start_at_token':'11月7日','end_at_token':'8日','year_quote':'2026年全国幼儿手球嘉年华','date_role':'event'}},
 {'sample_id':'evt_4e4c7dec000e','url':'https://www.sdxc.gov.cn/waplm/wapxw/202608/t20260805_17994768.htm',
  'label':'rss_missing_body_has_date','reason':'同一活动的权威替代报道，开幕8月4日；不是已证实的RSS原始正文。','match':'related_event_not_exact_original',
  'draft':{'start_at':'2026-08-04','end_at':'2026-08-04','quote':'8月4日','start_at_token':'8月4日','end_at_token':'8月4日','year_quote':'2026中非友好走进山东','date_role':'event'}}]


def run(output):
    output=safe_output(output);reader=Reader(output);result=[]
    for case in CASES:
        body,check=reader.fetch(case['url'],'independently_rediscovered_article')
        row=extract_article(body,{'id':'date-followup','scope':'unknown'},case['url'],check['checked_at'],date(2026,11,26)) if body else None
        draft=case['draft'];gate=evidence_gate(draft,row['body_text']) if draft and row else (False,'no_structured_proposal')
        result.append({**case,'access':check,'body_text':row['body_text'] if row else None,'rule_extraction':row,
            'annotation_author':'assistant','human_label':None,'annotation_status':'draft_requires_human_review',
            'llm_method':'conversation_assistant_no_external_paid_model','evidence_gate':{'passed':gate[0],'reason':gate[1]}})
    collect.write_json(output/'annotations.json',{'not_a_200_row_accuracy_estimate':True,'human_completed':0,'data':result})
    collect.write_json(output/'run.json',{'checks':reader.checks})
    print({'bodies_read':sum(bool(r['body_text']) for r in result),'evidence_gated_proposals':sum(r['evidence_gate']['passed'] for r in result)})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args();run(args.output)
