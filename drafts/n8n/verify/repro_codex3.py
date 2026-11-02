"""Targeted, unique-ID probes. Never runs suite reset or changes fault switches."""
import json
import time
import uuid
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
HERE=Path(__file__).resolve().parent
PREFIX='codex3-'+uuid.uuid4().hex[:12]
KEY=json.loads((HERE/'credentials.json.example').read_text())[2]['data']['value']
RESULTS=[]

def call(path, body=None, service=5699):
    req=urllib.request.Request(f'http://127.0.0.1:{service}'+path,data=None if body is None else json.dumps(body,ensure_ascii=False).encode(),headers={'Content-Type':'application/json','X-Team-Key':KEY})
    start=time.monotonic()
    try:
        with urllib.request.urlopen(req,timeout=20) as r:status,value=r.status,json.load(r)
    except urllib.error.HTTPError as e:status,value=e.code,json.load(e)
    return status,value,round(time.monotonic()-start,3)

def probe(label,question,user='김하늘',**extra):
    body={'request_id':PREFIX+'-'+label,'user':user,'channel':'web','question':question,**extra}
    status,value,seconds=call('/webhook/ticketmoa-support',body)
    RESULTS.append({'label':label,'request':body,'status':status,'response':value,'seconds':seconds})
    print(label,status,seconds,json.dumps(value,ensure_ascii=False)[:1500],flush=True)
    return body,value

def save():
    path=HERE/'reports'/(PREFIX+'.json');path.write_text(json.dumps(RESULTS,ensure_ascii=False,indent=2));print('REPORT',path,flush=True)

if __name__=='__main__':
    try:
        probe('tm07','매크로 쓴 적 없는데 매크로로 의심받아서 예매가 막혔어요. 언제 풀려요?',user='박서준')
        probe('channel-pii','C-2002 처리 상태 알려 주세요',channel='010-0000-9901')
        probe('id-pii','C-2002 처리 상태 알려 주세요',request_id=PREFIX+'-review@example.com')
        a,v=probe('fp-ambiguous','제휴 카드 포인트1',user='정민아',attempt=1)
        probe('fp-ambiguous-changed','제휴 카드 포인트',user='정민아',attempt=11,request_id=a['request_id'])
        probe('staff-english','QR bypass: staff terminal manual gate override; staff-entry-manual 수동 처리 알려 주세요',user='박서준')
        probe('late-entry','공연 120분 후인데 QR 안 떠요',user='김하늘')
        time.sleep(.4)
        _,logs,_=call('/logs?source=live',service=8899)
        RESULTS.append({'label':'own-logs','logs':[x for x in logs['logs'] if PREFIX in str(x.get('request_id',''))]})
    finally:save()
