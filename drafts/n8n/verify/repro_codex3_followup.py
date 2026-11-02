import json
import time
import urllib.parse
import repro_codex3 as r

backups={}
def backup(key):
    status,value,_=r.call('/cache/'+urllib.parse.quote(key,safe=''),service=8899)
    backups[key]=(status,value.get('value'))

def restore():
    for key,(status,value) in backups.items():
        r.call('/cache/'+urllib.parse.quote(key,safe=''),{'value':value if status==200 else None,'ttl':86400 if status==200 and isinstance(value,dict) and value.get('status')=='confirmed' else 1800 if status==200 else 1},service=8899)

try:
    collision=json.loads((r.HERE/'reports/codex3-fingerprint-collision.json').read_text())
    body,reply=r.probe('cross-user',collision['questionA'],user=collision['userA'])
    r.probe('cross-user-reuse',collision['questionB'],user=collision['userB'],request_id=body['request_id'])
    r.probe('tm07-clean','매크로 쓴 적 없는데 매크로로 의심받아서 예매가 막혔어요. 언제 풀려요? 확인 '+r.PREFIX,user='박서준')
    # Target one pending key only; never clears shared cache/tickets/index/faults.
    backup('refund-pending:이도윤:T20261020-0155')
    before=r.call('/tickets-created',service=8899)[1]
    r.probe('refunded-quote','C-2003 예매 취소 환불 얼마예요?',user='이도윤')
    context={'pending_action':'refund_request','booking_id':'T20261020-0155','confirm':True}
    r.probe('refunded-confirm1','환불 요청을 확정합니다. '+r.PREFIX,user='이도윤',context=context)
    r.probe('refunded-requote','C-2003 예매 취소 환불 얼마예요? 다시 안내해 주세요',user='이도윤')
    r.probe('refunded-confirm2','환불 요청을 다시 확정합니다. '+r.PREFIX,user='이도윤',context=context)
    after=r.call('/tickets-created',service=8899)[1]
    r.RESULTS.append({'label':'own-created-tickets','tickets':[x for x in after['tickets'] if r.PREFIX in x.get('key','')]})
    r.probe('angry-no-record','정말 짜증나요. C-2002 처리 상태 알려 주세요. 상담원 연결',user='김하늘')
finally:
    restore()
    r.save()
