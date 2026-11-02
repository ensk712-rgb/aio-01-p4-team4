import json,time,uuid,subprocess
from pathlib import Path
import runner
r=runner.Runner();prefix='codex4-'+uuid.uuid4().hex[:10]
if subprocess.run(['pgrep','-f','Python.*runner.py'],capture_output=True).returncode==0:raise SystemExit('Other runner active')
_,old_state,_=runner.http('GET','http://127.0.0.1:8898/admin/state')
old_fault=r.api('/admin/fault');rows=[]
try:
    r.mock({'mode':'slow','slow_seconds':1.9})
    r.api('/admin/fault',{'tickets':'slow','slow_seconds':8})
    body={'request_id':prefix+'-deadline','user':'김하늘','channel':'web','question':'모바일티켓 QR이 회색으로 안 떠요. 검토 '+prefix}
    status,value,seconds=runner.http('POST','http://127.0.0.1:5699/webhook/ticketmoa-support',body,timeout=20)
    rows.append({'case':'llm-plus-ticket-delay','request':body,'status':status,'response':value,'seconds':seconds})
    print(status,round(seconds,3),json.dumps(value,ensure_ascii=False),flush=True)
    # Slow POST keeps running after its caller times out. Observe only our key.
    until=time.monotonic()+9
    while time.monotonic()<until:
        own=[x for x in r.api('/tickets-created')['tickets'] if x.get('key')==body['request_id']]
        if own:break
        time.sleep(.5)
    rows.append({'case':'late-ticket-observation','tickets':own,'dlq':[x for x in r.api('/dlq')['items'] if x.get('item',{}).get('id')==body['request_id']]})
    print('Late tickets:',own,flush=True)
finally:
    r.api('/admin/fault',old_fault);r.mock(old_state)
    path=Path(__file__).parent/'reports'/(prefix+'-deadline.json');path.write_text(json.dumps(rows,ensure_ascii=False,indent=2));print('Report:',path,flush=True)
