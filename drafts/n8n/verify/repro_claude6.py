"""Claude 6차: codex-5 결함 3건 재현 확인. 격리 하네스(5699·8899·8898)와 가짜 데이터만 쓴다."""
import json,time,uuid
from pathlib import Path
import runner
R=runner.Runner();P='claude6-'+uuid.uuid4().hex[:8];rows=[]

def post(label,hook,body):
    status,value,sec=runner.http('POST','http://127.0.0.1:5699/webhook/'+hook,body,timeout=15)
    rows.append({'case':label,'request':body,'status':status,'response':value,'seconds':round(sec,3)})
    v=value if isinstance(value,dict) else {}
    print(label,status,'route=',v.get('route'),'ticket=',v.get('ticket'),'reason=',v.get('reason'),'codes=',v.get('codes'),'period=',v.get('period'),flush=True)
    return status,v

def sup(label,rid,user,q,channel='web'):
    return post(label,'ticketmoa-support',{'request_id':rid,'user':user,'channel':channel,'question':q})

Q='C-2002 처리 상태 알려 주세요. 상담원 연결'
try:
    # 1a. codex-5 원 시나리오: 타인 요청이 티켓까지 가서 거절된 경우
    R.reset();rid=P+'-1a'
    sup('1a-owner',rid,'김하늘',Q)
    R.api('/cache-clear',{})
    sup('1a-foreign',rid,'박서준','상담원 연결 문의합니다')
    print(' cache=',runner.http('GET','http://127.0.0.1:8899/cache/req:'+rid)[:2])
    sup('1a-owner-again',rid,'김하늘',Q)
    # 1b. 타인 요청이 티켓 없이 끝나 handoff 복구를 지나지 않는 경우
    R.reset();rid=P+'-1b'
    sup('1b-owner',rid,'김하늘',Q)
    R.api('/cache-clear',{})
    sup('1b-foreign-faq',rid,'박서준','QR 모바일티켓이 안 열려요')
    print(' cache=',runner.http('GET','http://127.0.0.1:8899/cache/req:'+rid)[:2])
    sup('1b-owner-again',rid,'김하늘',Q)
    # 2. channel
    R.reset()
    for i,ch in enumerate(['web-010-0000-9901','010-0000-9901','web@example.com',['web'],'mobile']):
        sup('2-'+str(i),P+'-2-'+str(i),'김하늘','C-2002 처리 상태 알려 주세요',channel=ch)
    post('2-400','ticketmoa-support',{'request_id':P+'-2-400','user':'김하늘','channel':'web-010-0000-9901','question':''})
    time.sleep(.5)
    print(' log channels=',[(l.get('request_id')[-5:],l.get('channel'),l.get('masked')) for l in R.api('/logs?source=live')['logs']])
    # 3. ops
    for i,b in enumerate([{'from':'2026-99-99','to':'2026-99-99'},{'from':'2026-99-99'},{'from':'2026-02-30','to':'2026-02-31'},{'from':'2026-11-02','to':'2026-99-99'},{'from':'0000-01-01'},{'from':['2026-11-01']},{'from':20261101}]):
        post('3-'+str(i),'ticketmoa-ops',b)
finally:
    path=Path(__file__).parent/'reports'/(P+'-http.json');path.write_text(json.dumps(rows,ensure_ascii=False,indent=2));print('Report:',path)
