"""Final isolated HTTP checks; no workflow edits, only fake fixtures."""
import json,time,uuid,urllib.request,urllib.error
from pathlib import Path
import runner
R=runner.Runner();P='codex5-'+uuid.uuid4().hex[:10];rows=[]

def post(label,hook,body):
    # ASCII JSON also transports unpaired UTF-16 escapes without client encoding failure.
    req=urllib.request.Request('http://127.0.0.1:5699/webhook/'+hook,data=json.dumps(body,ensure_ascii=True).encode(),headers={'Content-Type':'application/json','X-Team-Key':runner.TEAM_KEY})
    start=time.monotonic()
    try:
        with urllib.request.urlopen(req,timeout=15) as resp:status,value=resp.status,json.load(resp)
    except urllib.error.HTTPError as e:status,value=e.code,json.load(e)
    record={'case':label,'request':body,'status':status,'response':value,'seconds':round(time.monotonic()-start,3)};rows.append(record)
    print(label,status,repr(value)[:750],flush=True)
    return record

def support(label,q='C-2002 처리 상태 알려 주세요',user='김하늘',**kw):
    return post(label,'ticketmoa-support',{'request_id':P+'-'+label,'user':user,'channel':'web','question':q,**kw})

def observe(label,**kw):rows.append({'case':label,**kw})

try:
    R.reset()
    first=support('A-first',q='C-2002 처리 상태 알려 주세요. 상담원 연결')
    R.api('/cache-clear',{})
    normal=support('A-self-repeat',q=first['request']['question'],request_id=first['request']['request_id'])
    observe('A-self-check',pass_=normal['response'].get('ticket',{}).get('duplicate') is True and normal['response'].get('ticket',{}).get('id')==first['response'].get('ticket',{}).get('id'))
    R.api('/cache-clear',{})
    before={'tickets':R.api('/tickets-created'),'dlq':R.api('/dlq'),'alerts':R.api('/alerts')}
    foreign=support('A-other',q='상담원 연결 문의합니다',user='박서준',request_id=first['request']['request_id'])
    after={'tickets':R.api('/tickets-created'),'dlq':R.api('/dlq'),'alerts':R.api('/alerts')}
    observe('A-foreign-check',pass_=foreign['response'].get('ticket') is None and 'request_id_conflict' in foreign['response'].get('reason','') and before==after,before=before,after=after)
    support('A-owner-after-rejected-other',q=first['request']['question'],request_id=first['request']['request_id'])

    R.reset()
    for i,channel in enumerate(['010-0000-9901','01000009903','web-010-0000-9901','web_2']):
        support('B-'+str(i),channel=channel)
    time.sleep(.25)
    observe('B-logs',logs=R.api('/logs?source=live'))

    R.reset()
    support('C-quote','C-2005 예매 취소 환불 얼마예요?',user='이도윤')
    confirmed=support('C-confirm','확정합니다',user='이도윤',context={'pending_action':'refund_request','booking_id':'T20261104-0412','confirm':True})
    R.api('/tickets-reset',{})
    replacement=R.api('/tickets',{'key':P+'-replacement','title':'ID reuse fixture','requester':'박서준','category':'general','priority':'normal'})
    requote=support('C-requote','C-2005 환불 금액을 다시 안내해 주세요',user='이도윤')
    observe('C-check',pass_=requote['response'].get('ticket') is None and requote['response'].get('route')=='자동 답변',old_ticket=confirmed['response'].get('ticket'),replacement=replacement,actual=R.api('/tickets-created'))

    R.reset()
    body={'request_id':P+'-F','user':'김하늘','summary':'공연 직전 입장 지원','category':'onsite_entry','priority':'high','alert':{'channel':'venue-staff','priority':'high'},'deadline_ms':int(time.time()*1000)+5000}
    post('F-first','ticketmoa-handoff',body)
    one=R.api('/alerts');history=R.api('/cache/urgent-alerted:'+body['request_id'])
    post('F-repeat','ticketmoa-handoff',dict(body,deadline_ms=int(time.time()*1000)+5000))
    two=R.api('/alerts')
    observe('F-check',pass_=one['count']==two['count']==1 and history.get('value') is True,history=history,alerts=two)

    R.reset()
    for label,q in [('G-high','\ud800'),('G-low','\udc00')]:
        support(label,q=q)
    support('G-booking','확정합니다',context={'pending_action':'refund_request','booking_id':'\ud800','confirm':True})
    post('new-invalid-calendar','ticketmoa-ops',{'from':'2026-99-99','to':'2026-99-99'})
finally:
    R.api('/admin/fault',{'tickets':'ok','faq':'ok','dlq':'ok','prompts':'ok','usage':'ok','slow_seconds':8})
    R.mock({'mode':'ok','slow_seconds':8})
    path=Path(__file__).parent/'reports'/(P+'-http.json');path.write_text(json.dumps(rows,ensure_ascii=True,indent=2));print('Report:',path,flush=True)
