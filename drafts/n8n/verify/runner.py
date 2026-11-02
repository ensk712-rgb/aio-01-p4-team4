#!/usr/bin/env python3
"""Independent contract runner; never imports generated workflow code.
field/as_text/judge below are copied unchanged from Last3Mon/77/tools/flow.py.
"""
import argparse
import datetime
import json
import math
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TEAM_KEY = 'ticketmoa-verify-team-key'  # Deliberately fake, fixed fixture credential.
REQUIRED = {'request_id','route','answer','sources','ticket','agents','security','timings','reason'}
ROUTES = {'자동 답변','보완 질문','담당자 이관','권한 없음','차단'}

def field(payload: object, dotted: str) -> object:
    value = payload
    for part in dotted.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
    return value


def as_text(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def judge(expect: dict, status: int, payload: object, seconds: float = 0.0) -> list[str]:
    problems = []
    if "max_seconds" in expect and seconds > float(expect["max_seconds"]):
        problems.append(f"took {seconds:.1f}s (expected at most {expect['max_seconds']}s)")
    if status != expect.get("status", 200):
        problems.append(f"status {status} (expected {expect.get('status', 200)})")
    for name, wanted in (expect.get("equals") or {}).items():
        actual = field(payload, name)
        if actual != wanted:
            problems.append(f"{name} = {as_text(actual)[:60]} (expected {as_text(wanted)})")
    for name, bounds in (expect.get("range") or {}).items():
        actual = field(payload, name)
        low, high = bounds
        if not isinstance(actual, (int, float)) or isinstance(actual, bool) or not low <= actual <= high:
            problems.append(f"{name} = {as_text(actual)[:40]} (expected {low}..{high})")
    for name, words in (expect.get("contains") or {}).items():
        words = [words] if isinstance(words, str) else words
        text = as_text(field(payload, name) or "")
        if not any(word in text for word in words):
            problems.append(f"{name} has none of {words}")
    for name, words in (expect.get("not_contains") or {}).items():
        words = [words] if isinstance(words, str) else words
        text = as_text(field(payload, name) or "")
        leaked = [word for word in words if word in text]
        if leaked:
            problems.append(f"{name} must not have {leaked}")
    return problems

def http(method, url, body=None, auth=True, timeout=20):
    # Whitelist local harness ports so scenario hooks cannot reach course services.
    if not re.match(r'^http://127\.0\.0\.1:(5699|8899|8898)(/|$)', url):
        raise ValueError('Only isolated harness loopback endpoints are allowed: '+url)
    headers = {'Content-Type': 'application/json'}
    if auth: headers['X-Team-Key'] = TEAM_KEY
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body, ensure_ascii=False).encode(), headers=headers, method=method)
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        return 0, {'error': str(e)}, time.monotonic()-start
    try: payload = json.loads(raw)
    except ValueError: payload = raw.decode(errors='replace')
    return status, payload, time.monotonic()-start


class Runner:
    def __init__(self, repeat=1, settle=0.2):
        self.repeat, self.settle = repeat, settle
        self.results = []
        self.ticket_ids = {}
        records = json.loads((ROOT/'data/records.json').read_text())
        self.contacts = [v for record in records.values() for v in record.get('contact', {}).values() if v]

    def api(self, path, body=None):
        status, payload, _ = http('GET' if body is None else 'POST', 'http://127.0.0.1:8899'+path, body)
        if not 200 <= status < 300: raise RuntimeError(f'data API {path}: {status} {payload}')
        return payload

    def mock(self, body=None):
        status, payload, _ = http('GET' if body is None else 'POST', 'http://127.0.0.1:8898/admin/'+('stats' if body is None else 'state'), body)
        if status != 200: raise RuntimeError(f'mock: {status} {payload}')
        return payload

    def reset(self):
        # Explicit full isolation boundary; never run between TM-02 and TM-03.
        self.api('/admin/fault', {'tickets':'ok','faq':'ok','dlq':'ok','prompts':'ok','usage':'ok'})
        for path in ['/tickets-reset','/cache-clear','/alerts-clear','/dlq-clear','/logs-reset']:
            self.api(path, {})
        self.mock({'mode':'ok','reset_stats':True})
        self.ticket_ids = {}

    def step(self, step):
        if 'llm' in step:
            self.mock({'mode': 'down' if step['llm'] == 'down' else 'ok'}); return
        if 'mock' in step: self.mock(step['mock']); return
        if 'url' in step:
            url = step['url'].replace('http://localhost:8800', 'http://127.0.0.1:8899')
        else:
            url = 'http://127.0.0.1:5699/webhook/'+step['webhook'].strip('/')
        status, payload, _ = http('POST', url, step.get('body', {}))
        if not 200 <= status < 300: raise RuntimeError(f'setup step failed: {status} {payload}')

    def snapshot(self):
        return {'tickets': self.api('/tickets-created'), 'dlq': self.api('/dlq'),
                'alerts': self.api('/alerts'), 'logs': self.api('/logs?source=live'), 'mock': self.mock()}

    def format_errors(self, status, payload, body):
        # AGENTS.md §3 has nine top-level response keys (len(REQUIRED) == 9).
        if status == 400:
            if not isinstance(payload, dict): return ['400 must be a JSON object']
            if payload.get('error') == 'invalid request' and isinstance(payload.get('codes'), list): return []
            return ['400 outside AGENTS.md invalid request schema (including request_id_conflict)']
        if status != 200: return [f'contract HTTP {status}']
        if not isinstance(payload, dict): return ['response must be object']
        errors = []
        if REQUIRED - payload.keys(): errors.append('missing fields: '+','.join(sorted(REQUIRED-payload.keys())))
        if payload.get('request_id') != body.get('request_id'): errors.append('request_id mismatch')
        if payload.get('route') not in ROUTES: errors.append('invalid route')
        for key in ['answer','reason']:
            if not isinstance(payload.get(key), str): errors.append(key+' must be string')
        sources = payload.get('sources')
        if not isinstance(sources, list): errors.append('sources must be list')
        else:
            for source in sources:
                if not isinstance(source, dict) or not all(isinstance(source.get(k), str) and source[k] for k in ['doc','section']):
                    errors.append('source needs nonempty doc/section'); continue
                score = source.get('score')
                if not isinstance(score, (int,float)) or isinstance(score,bool) or not math.isfinite(score): errors.append('source.score must be finite number')
        for key in ['agents','security','timings']:
            if not isinstance(payload.get(key), dict): errors.append(key+' must be object')
        security = payload.get('security', {})
        if isinstance(security, dict):
            if not all(isinstance(security.get(k), str) for k in ['blocked_by','reason']): errors.append('security blocked_by/reason must be strings')
            if not isinstance(security.get('masked'), int) or isinstance(security.get('masked'), bool) or security['masked'] < 0: errors.append('security.masked must be nonnegative integer')
        agents = payload.get('agents', {})
        if isinstance(agents, dict) and (not isinstance(agents.get('llm_calls'), int) or isinstance(agents.get('llm_calls'), bool) or agents['llm_calls'] < 0): errors.append('agents.llm_calls must be nonnegative integer')
        if isinstance(payload.get('timings'), dict):
            if any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) or v<0 for v in payload['timings'].values()): errors.append('timings values must be finite nonnegative ms')
        ticket = payload.get('ticket')
        if ticket is not None and (not isinstance(ticket, dict) or not isinstance(ticket.get('id'),str) or not ticket['id']): errors.append('ticket needs nonempty string id')
        return errors

    def strict(self, name, status, payload, body, before, after, rules=None, auth=True):
        rules = rules or {}
        if not auth:
            errors = [] if status in [401,403] else ['unauthenticated webhook must return 401/403']
            if after['tickets']['count'] != before['tickets']['count'] or after['mock']['chat_calls'] != before['mock']['chat_calls'] or after['mock']['embedding_calls'] != before['mock']['embedding_calls']:
                errors.append('unauthenticated webhook caused side effects')
            return errors
        # ops 같은 하위 웹훅은 공통 계약 응답 모양이 아니다.
        errors = [] if rules.get('raw_contract') else self.format_errors(status, payload, body)
        text = as_text(payload)
        # AGENTS §6: raw fixture contacts prohibited in every public/persisted sink.
        for sink, value in [('response',payload)] + [(k,after[k]) for k in ['logs','alerts','dlq','tickets']]:
            for contact in self.contacts + rules.get('no_raw_contacts', []):
                if contact in as_text(value): errors.append(f'{sink} raw contact leaked: {contact}')
        ticket = payload.get('ticket') if isinstance(payload,dict) else None
        # cases/README WF-02b/03/09/12, TM-03/08 demand a real created ticket.
        must_ticket = any(name.startswith(x+' ') for x in ['WF-02b','WF-03','WF-09','WF-12','TM-03','TM-08'])
        if (must_ticket or rules.get('require_ticket')) and not (isinstance(ticket,dict) and ticket.get('id')): errors.append('required ticket.id missing')
        if isinstance(ticket,dict) and ticket.get('id'):
            rows = [r for r in after['tickets']['tickets'] if r.get('key') == body.get('request_id')]
            # Confirm replay may return the original confirmation's ticket key.
            if not rows and rules.get('allow_original_key'):
                rows = [r for r in after['tickets']['tickets'] if r.get('ticket_id') == ticket['id']]
            if len(rows)!=1 or rows[0].get('ticket_id') != ticket['id']: errors.append('ticket.id not backed by exactly one created API row')
            elif rows[0].get('requester') != body.get('user') or (ticket.get('key') and rows[0].get('key') != ticket['key']):
                errors.append('ticket owner/key differs from actual API row')
        if name.startswith('WF-09 '):
            rows=[r for r in after['tickets']['tickets'] if r.get('key') == 'wf09']
            if len(rows)!=1: errors.append('WF-09 must create exactly one ticket')
            current = ticket.get('id') if isinstance(ticket,dict) else None
            if self.ticket_ids.get('wf09') and current != self.ticket_ids['wf09']: errors.append('WF-09 changed ticket.id')
            if current: self.ticket_ids['wf09'] = current
        if name.startswith('WF-08 '):
            for kind in ['chat_calls','embedding_calls']:
                if after['mock'][kind] != before['mock'][kind]: errors.append('WF-08 must make zero mock calls: '+kind)
        if name.startswith('WF-12 '):
            if not all(word in (payload.get('answer','') if isinstance(payload,dict) else '') for word in ['현장 발권','접수']): errors.append('WF-12 needs BOTH 현장 발권 and 접수')
            if field(payload,'ticket.priority') != 'high': errors.append('WF-12 priority must be high')
        if name.startswith('TM-02 '):
            answer = payload.get('answer','') if isinstance(payload,dict) else ''
            if not re.search(r'152,?000\s*원', answer): errors.append('TM-02 must show refund 152,000원')
            if not re.search(r'수수료[^\n。.!?]{0,30}0\s*원|0\s*원[^\n。.!?]{0,20}수수료',answer): errors.append('TM-02 must show fee 0원')
        if rules.get('no_ticket') and ticket is not None: errors.append('must not return ticket')
        if rules.get('no_refund_ticket') and isinstance(ticket, dict) and ticket.get('category') == 'refund': errors.append('must not create actionable refund ticket')
        for pattern in rules.get('answer_not_regex', []):
            if re.search(pattern, payload.get('answer','') if isinstance(payload,dict) else ''): errors.append('forbidden answer pattern: '+pattern)
        if 'ticket_delta' in rules and after['tickets']['count']-before['tickets']['count'] != rules['ticket_delta']: errors.append('wrong ticket count delta')
        if 'ticket_total' in rules and after['tickets']['count'] != rules['ticket_total']: errors.append('wrong total ticket count')
        if rules.get('handoff'):
            if status != 200 or field(payload,'route') != '담당자 이관': errors.append('failure must be HTTP 200 + 담당자 이관')
        if rules.get('normal') and field(payload,'route') != '자동 답변': errors.append('clear attempt 3 should be 자동 답변')
        for word in rules.get('no_exposure',[]):
            if word in text: errors.append('forbidden exposure: '+word)
        if rules.get('collision'):
            if isinstance(payload,dict) and payload.get('ticket') is not None: errors.append('collision exposed old ticket')
            if field(payload,'route') == '자동 답변': errors.append('collision returned original automatic response')
        if 'log_channel' in rules: errors += self.log_errors(body, payload, rules)
        marker=rules.get('prompt_absent')
        if marker:
            new=after['mock']['requests'][len(before['mock']['requests']):]
            if marker in as_text(new): errors.append('untrusted context injection entered mock prompt')
        return errors

    def log_errors(self, body, payload, rules):
        # /logs는 응답 뒤에 저장되므로 기대 건수가 찰 때까지 잠깐 기다린다.
        want=rules.get('log_rows',1)
        deadline=time.monotonic()+3
        while True:
            rows=[l for l in self.api('/logs?source=live')['logs'] if l.get('request_id')==body.get('request_id')]
            if len(rows)>=want or time.monotonic()>deadline: break
            time.sleep(0.1)
        errors=[] if len(rows)==want else [f'log rows {len(rows)}, expected {want}']
        for row in rows:
            if row.get('channel')!=rules['log_channel']: errors.append(f"log channel {row.get('channel')!r}, expected {rules['log_channel']!r}")
        # channel은 가린 것이 아니라 버린 값이므로 응답과 기록의 masked가 같아야 한다.
        masked=field(payload,'security.masked')
        if isinstance(masked,int) and rows and rows[-1].get('masked')!=masked: errors.append(f"log masked {rows[-1].get('masked')} != response masked {masked}")
        return errors

    def run_case(self, case, hook, repeats=None):
        name, body = case['name'], case.get('body', {})
        for step in case.get('before', []): self.step(step)
        baseline = self.snapshot()
        try:
            if name.startswith('TM-09 '):
                # BRIEF §6: actual five preceding requests, never trust context.note.
                self.api('/cache-clear', {})
                for i in range(5):
                    prime=dict(body, request_id=f'tm09-prime-{i}-{time.time_ns()}')
                    status, reply, _=http('POST','http://127.0.0.1:5699/webhook/'+hook, prime)
                    if status!=200: raise RuntimeError(f'TM-09 priming failed: {status} {reply}')
            for run in range(1,(repeats or self.repeat)+1):
                before = self.snapshot()
                auth = case.get('auth',True)
                status,payload,seconds=http('POST','http://127.0.0.1:5699/webhook/'+case.get('webhook',hook),body,auth=auth)
                time.sleep(self.settle)  # response-after-log races: bounded observation grace
                after=self.snapshot()
                ordinary=judge(case.get('expect',{}),status,payload,seconds) if auth else []
                strict=self.strict(name,status,payload,body,before,after,case.get('strict'),auth)
                row={'case':name,'run':run,'status':status,'seconds':round(seconds,3),'request':body,'response':payload,
                     'ordinary_errors':ordinary,'strict_errors':strict,'passed':not ordinary and not strict,
                     'observations':{'before':before,'after':after}}
                self.results.append(row)
                print(('PASS' if row['passed'] else 'FAIL'),name,f'#{run}',*ordinary,*strict,sep=' | ')
            final=self.snapshot()
            # PROMPTS D2 and common WF-12: one DLQ/alert per logical case,
            # not merely a truthful-looking ticket:null response. Replays must not duplicate side effects.
            expected={}
            if name.startswith('WF-04 '): expected={'dlq':1,'alerts':1}
            if name.startswith('WF-12 '): expected={'alerts':1}
            expected.update(case.get('strict',{}).get('deltas',{}))
            for sink,wanted in expected.items():
                key='size' if sink=='dlq' else 'count'
                actual=final[sink][key]-baseline[sink][key]
                if actual!=wanted:
                    self.results[-1]['strict_errors'].append(f'case {sink} delta {actual}, expected {wanted}')
                    self.results[-1]['passed']=False
                    print('FAIL | case aggregate', name, sink, actual, 'expected', wanted)
        finally:
            for step in case.get('after',[]): self.step(step)

    def suite(self, path):
        suite=json.loads(Path(path).read_text())
        self.reset()
        for step in suite.get('before',[]): self.step(step)
        try:
            for case in suite['cases']: self.run_case(case,suite.get('webhook','ticketmoa-support'))
        finally:
            for step in suite.get('after',[]): self.step(step)

    def adversarial(self, id_prefix=''):
        suite=json.loads((HERE/'adversarial.json').read_text())
        for group in suite['groups']:
            self.reset()
            for case in group['steps']:
                if id_prefix:
                    body = case['body']
                    if 'request_id' in body: body['request_id'] = id_prefix + '-' + body['request_id']
                    for step in case.get('before', []):
                        if 'url' in step: step['url'] = step['url'].replace('/cache/req:', '/cache/req:' + id_prefix + '-')
                # Sequence is intentional: do not repeat a confirmation before the next step.
                self.run_case(case,'ticketmoa-support',repeats=1)

    def save(self, label):
        HERE.joinpath('reports').mkdir(exist_ok=True)
        path=HERE/'reports'/f'{label}-{datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")}.json'
        path.write_text(json.dumps({'label':label,'actual_date':str(datetime.date.today()),'passed':sum(r['passed'] for r in self.results),
                                    'total':len(self.results),'results':self.results},ensure_ascii=False,indent=2))
        print('Report:',path)
        return all(r['passed'] for r in self.results)


def ready():
    # Only the dedicated project's endpoints. No long blocking sleeps.
    deadline=time.monotonic()+60
    urls=['http://127.0.0.1:5699/healthz/readiness','http://127.0.0.1:8899/health','http://127.0.0.1:8898/health']
    while time.monotonic()<deadline:
        if all(http('GET',url,timeout=1)[0]==200 for url in urls): return
        time.sleep(0.5)
    raise RuntimeError('Harness services not ready within 60 seconds')


def pre_index(runner):
    # PROMPTS C2 / first-review F15: no store must be distinguishable, before index.
    body={'request_id':'pre-index','query':'QR 모바일티켓','access_level':'all','top_k':3}
    status,payload,seconds=http('POST','http://127.0.0.1:5699/webhook/ticketmoa-search',body)
    problems=[]
    if status!=200 or not isinstance(payload,dict) or payload.get('indexed') is not False:
        problems.append('before index search must explicitly return indexed:false')
    runner.results.append({'case':'pre-index','status':status,'response':payload,'seconds':seconds,'passed':not problems,'strict_errors':problems})
    return runner.save('pre-index')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite',choices=['common','team','adversarial','all'],default='common')
    parser.add_argument('--repeat',type=int,default=1)
    parser.add_argument('--id-prefix', default='', help='Unique namespace for adversarial request IDs; preserves intentional reuse')
    parser.add_argument('--wait-ready',action='store_true')
    parser.add_argument('--pre-index',action='store_true')
    parser.add_argument('--index',action='store_true')
    args=parser.parse_args()
    if args.repeat<1: parser.error('--repeat must be positive')
    if args.wait_ready: ready(); return 0
    runner=Runner()
    if args.pre_index: return 0 if pre_index(runner) else 1
    if args.index:
        status,payload,_=http('POST','http://127.0.0.1:5699/webhook/ticketmoa-index',{})
        print(json.dumps(payload,ensure_ascii=False))
        if status!=200 or not isinstance(payload,dict) or payload.get('error'): return 1
        if payload.get('ready') is False: return 1
        # Ensure success was not a syntactically valid, empty index response.
        status,hits,_=http('POST','http://127.0.0.1:5699/webhook/ticketmoa-search',{'query':'QR 모바일티켓','access_level':'all','top_k':3})
        if status!=200 or not isinstance(hits,dict) or not hits.get('hits'): return 1
        return 0
    runner.repeat=args.repeat
    label=args.suite
    spans=[]
    try:
        for name in ['common','team','adversarial']:
            if args.suite in (name,'all'):
                start=len(runner.results)
                if name=='adversarial': runner.adversarial(args.id_prefix)
                else: runner.suite(ROOT/'cases'/f'{name}.json')
                spans.append((name,start,len(runner.results)))
    except (RuntimeError,ValueError,KeyError) as e:
        runner.results.append({'case':'infrastructure','passed':False,'error':str(e)})
        print('INFRASTRUCTURE FAILURE:',e)
    finally:
        # Restore fault switches even after a failing drill; keep evidence for inspection.
        try:
            runner.api('/admin/fault',{'tickets':'ok','faq':'ok','dlq':'ok','prompts':'ok','usage':'ok'})
            runner.mock({'mode':'ok'})
        except RuntimeError: pass
    ok=runner.save(label)
    if args.suite=='all':
        # 설명 화면은 스위트별 최신 보고서를 읽는다. all 실행도 같은 이름으로 나눠 남긴다.
        everything=runner.results
        for name,start,stop in spans:
            runner.results=everything[start:stop]
            runner.save(name)
        runner.results=everything
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
