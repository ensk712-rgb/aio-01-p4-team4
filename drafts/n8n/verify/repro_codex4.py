"""Final targeted recheck. Only the ticketmoa-verify API is reset/mutated."""
import json
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path
import runner

HERE=Path(__file__).resolve().parent
PREFIX='codex4-'+uuid.uuid4().hex[:10]
R=runner.Runner()
rows=[]

def post(hook,body):
    status,value,seconds=runner.http('POST','http://127.0.0.1:5699/webhook/'+hook,body)
    rows.append({'hook':hook,'request':body,'status':status,'response':value,'seconds':seconds})
    print(hook,status,round(seconds,3),json.dumps(value,ensure_ascii=True)[:1200],flush=True)
    return value

def support(tag,q,user='이도윤',**kw):
    return post('ticketmoa-support',{'request_id':PREFIX+'-'+tag,'user':user,'channel':'web','question':q,**kw})

try:
    R.reset()
    guide=support('quote','C-2005 예매 취소 환불 얼마예요?')
    a=support('confirm','확정합니다',context={'pending_action':'refund_request','booking_id':'T20261104-0412','confirm':True})
    R.api('/tickets-reset',{})
    replacement=R.api('/tickets',{'key':PREFIX+'-replacement','title':'recycled ID fixture','requester':'박서준','category':'general','priority':'normal'})
    b=support('requote-after-reset','C-2005 환불 금액을 다시 안내해 주세요')
    rows.append({'case':'recycled-ticket-id','original':a,'replacement':replacement,'response':b,'actual_tickets':R.api('/tickets-created')})

    R.reset()
    original=support('owner-cache','C-2002 처리 상태 알려 주세요. 상담원 연결',user='김하늘')
    R.api('/cache-clear',{})  # Simulate ownership cache expiry/loss while created tickets survive.
    reused=support('owner-cache-other','상담원 연결 문의합니다',user='박서준',request_id=PREFIX+'-owner-cache')
    rows.append({'case':'ownership-cache-loss','original':original,'reused':reused,'actual_tickets':R.api('/tickets-created')})

    # JSON permits escaped unpaired UTF-16 values. Use ensure_ascii=True for transport.
    body={'request_id':PREFIX+'-surrogate','user':'김하늘','channel':'web','question':'\ud800'}
    req=urllib.request.Request('http://127.0.0.1:5699/webhook/ticketmoa-support',data=json.dumps(body,ensure_ascii=True).encode(),headers={'Content-Type':'application/json','X-Team-Key':runner.TEAM_KEY})
    start=time.monotonic()
    try:
        with urllib.request.urlopen(req,timeout=10) as resp:status,raw=resp.status,resp.read()
    except urllib.error.HTTPError as e:status,raw=e.code,e.read()
    except (TimeoutError,urllib.error.URLError) as e:status,raw=0,str(e).encode()
    try:value=json.loads(raw)
    except ValueError:value=raw.decode(errors='replace')
    rows.append({'case':'unpaired-surrogate','request':body,'status':status,'response':value,'seconds':time.monotonic()-start})
    print('unpaired-surrogate',status,repr(value),flush=True)
finally:
    R.api('/admin/fault',{'tickets':'ok','dlq':'ok'})
    R.mock({'mode':'ok'})
    path=HERE/'reports'/(PREFIX+'-targeted.json')
    path.write_text(json.dumps(rows,ensure_ascii=True,indent=2))
    print('Report:',path,flush=True)
