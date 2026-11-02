import subprocess,time,json
import repro_codex3 as r
# Abort rather than change a global mock mode while a suite runner is visible.
active=subprocess.run(['pgrep','-f','Python.*runner.py'],capture_output=True,text=True)
if active.returncode==0:raise SystemExit('Concurrent runner detected; delay probe not run')
_,state,_=r.call('/admin/state',service=8898)
_,fault,_=r.call('/admin/fault',service=8899)
if state['mode']!='ok' or fault['tickets']!='ok':raise SystemExit('Existing drill in progress; abort')
try:
 r.call('/admin/state',{'mode':'slow','slow_seconds':1.7},service=8898)
 r.probe('llm-delay','모바일티켓 QR이 회색으로 안 떠요. 확인번호 '+r.PREFIX,user='김하늘')
 time.sleep(2)
 _,stats,_=r.call('/admin/stats',service=8898)
 r.RESULTS.append({'label':'delay-stats','counts':{k:stats[k] for k in ['chat_calls','embedding_calls','by_role']},'requests':stats['requests']})
finally:
 r.call('/admin/state',state,service=8898)
 r.save()
