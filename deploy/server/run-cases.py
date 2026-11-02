#!/usr/bin/env python3
"""서버용 시나리오 러너 (표준 라이브러리만).
drafts/n8n/verify/runner.py 를 실서버용으로 일반화한 것. mock LLM 관련 검사는 뺐다.
field/as_text/judge 는 과정 키트 flow.py 와 같다.

  cd ~/aio-01-p4-team4
  python3 deploy/server/run-cases.py --suite common --repeat 1 -v
  python3 deploy/server/run-cases.py --suite all --repeat 3
  python3 deploy/server/run-cases.py --index          # 색인 한 번 실행하고 검색 확인
  python3 deploy/server/run-cases.py --wait-ready     # n8n·데이터 API 준비될 때까지 대기

주소·키는 환경변수 또는 저장소 뿌리 .env 에서 읽는다: TM_N8N_URL, TM_DATA_API_URL, TM_TEAM_KEY.
보고서: runs/<suite>-<시각>.json 과 runs/<suite>-<시각>.txt
"""
import argparse
import datetime
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load_env():
    env_file = ROOT / '.env'
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())


load_env()
N8N = os.environ.get('TM_N8N_URL', 'http://localhost:5678').rstrip('/')
DATA_API = os.environ.get('TM_DATA_API_URL', 'http://localhost:8800').rstrip('/')
TEAM_KEY = os.environ.get('TM_TEAM_KEY', '')
REQUIRED = {'request_id', 'route', 'answer', 'sources', 'ticket', 'agents', 'security', 'timings', 'reason'}
ROUTES = {'자동 답변', '보완 질문', '담당자 이관', '권한 없음', '차단'}
VERBOSE = False


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


def http(method, url, body=None, auth=True, timeout=30):
    headers = {'Content-Type': 'application/json'}
    if auth:
        headers['X-Team-Key'] = TEAM_KEY
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body, ensure_ascii=False).encode(), headers=headers, method=method)
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        return 0, {'error': str(e)}, time.monotonic() - start
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = raw.decode(errors='replace')
    return status, payload, time.monotonic() - start


class Runner:
    def __init__(self, repeat=1, settle=0.3):
        self.repeat, self.settle = repeat, settle
        self.results = []
        self.ticket_ids = {}
        records = json.loads((ROOT / 'data/records.json').read_text())
        self.contacts = [v for record in records.values() for v in record.get('contact', {}).values() if v]

    def api(self, path, body=None):
        status, payload, _ = http('GET' if body is None else 'POST', DATA_API + path, body)
        if not 200 <= status < 300:
            raise RuntimeError(f'data API {path}: {status} {payload}')
        return payload

    def reset(self):
        self.api('/admin/fault', {'tickets': 'ok', 'faq': 'ok', 'dlq': 'ok', 'prompts': 'ok', 'usage': 'ok'})
        for path in ['/tickets-reset', '/cache-clear', '/alerts-clear', '/dlq-clear', '/logs-reset']:
            self.api(path, {})
        self.ticket_ids = {}

    def step(self, step):
        if 'llm' in step or 'mock' in step:
            print('  (건너뜀: 실서버에서는 LLM 을 끄고 켤 수 없다)', json.dumps(step, ensure_ascii=False))
            return
        if 'url' in step:
            url = re.sub(r'^https?://[^/]+', DATA_API, step['url'])
        else:
            url = N8N + '/webhook/' + step['webhook'].strip('/')
        status, payload, _ = http('POST', url, step.get('body', {}))
        if not 200 <= status < 300:
            raise RuntimeError(f'setup step failed: {status} {payload}')

    def snapshot(self):
        return {'tickets': self.api('/tickets-created'), 'dlq': self.api('/dlq'),
                'alerts': self.api('/alerts'), 'logs': self.api('/logs?source=live')}

    def format_errors(self, status, payload, body):
        if status == 400:
            if not isinstance(payload, dict):
                return ['400 must be a JSON object']
            if payload.get('error') == 'invalid request' and isinstance(payload.get('codes'), list):
                return []
            return ['400 outside AGENTS.md invalid request schema']
        if status != 200:
            return [f'contract HTTP {status}']
        if not isinstance(payload, dict):
            return ['response must be object']
        errors = []
        if REQUIRED - payload.keys():
            errors.append('missing fields: ' + ','.join(sorted(REQUIRED - payload.keys())))
        if payload.get('request_id') != body.get('request_id'):
            errors.append('request_id mismatch')
        if payload.get('route') not in ROUTES:
            errors.append('invalid route')
        for key in ['answer', 'reason']:
            if not isinstance(payload.get(key), str):
                errors.append(key + ' must be string')
        sources = payload.get('sources')
        if not isinstance(sources, list):
            errors.append('sources must be list')
        else:
            for source in sources:
                if not isinstance(source, dict) or not all(isinstance(source.get(k), str) and source[k] for k in ['doc', 'section']):
                    errors.append('source needs nonempty doc/section')
                    continue
                score = source.get('score')
                if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score):
                    errors.append('source.score must be finite number')
        for key in ['agents', 'security', 'timings']:
            if not isinstance(payload.get(key), dict):
                errors.append(key + ' must be object')
        security = payload.get('security', {})
        if isinstance(security, dict):
            if not all(isinstance(security.get(k), str) for k in ['blocked_by', 'reason']):
                errors.append('security blocked_by/reason must be strings')
            if not isinstance(security.get('masked'), int) or isinstance(security.get('masked'), bool) or security['masked'] < 0:
                errors.append('security.masked must be nonnegative integer')
        agents = payload.get('agents', {})
        if isinstance(agents, dict) and (not isinstance(agents.get('llm_calls'), int) or isinstance(agents.get('llm_calls'), bool) or agents['llm_calls'] < 0):
            errors.append('agents.llm_calls must be nonnegative integer')
        if isinstance(payload.get('timings'), dict):
            if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v < 0 for v in payload['timings'].values()):
                errors.append('timings values must be finite nonnegative ms')
        ticket = payload.get('ticket')
        if ticket is not None and (not isinstance(ticket, dict) or not isinstance(ticket.get('id'), str) or not ticket['id']):
            errors.append('ticket needs nonempty string id')
        return errors

    def strict(self, name, status, payload, body, before, after, rules=None, auth=True):
        rules = rules or {}
        if not auth:
            errors = [] if status in [401, 403] else ['unauthenticated webhook must return 401/403']
            if after['tickets']['count'] != before['tickets']['count']:
                errors.append('unauthenticated webhook caused side effects')
            return errors
        errors = self.format_errors(status, payload, body)
        text = as_text(payload)
        for sink, value in [('response', payload)] + [(k, after[k]) for k in ['logs', 'alerts', 'dlq', 'tickets']]:
            for contact in self.contacts + rules.get('no_raw_contacts', []):
                if contact in as_text(value):
                    errors.append(f'{sink} raw contact leaked: {contact}')
        ticket = payload.get('ticket') if isinstance(payload, dict) else None
        must_ticket = any(name.startswith(x + ' ') for x in ['WF-02b', 'WF-03', 'WF-09', 'WF-12', 'TM-03', 'TM-08'])
        if (must_ticket or rules.get('require_ticket')) and not (isinstance(ticket, dict) and ticket.get('id')):
            errors.append('required ticket.id missing')
        if isinstance(ticket, dict) and ticket.get('id'):
            rows = [r for r in after['tickets']['tickets'] if r.get('key') == body.get('request_id')]
            if not rows and rules.get('allow_original_key'):
                rows = [r for r in after['tickets']['tickets'] if r.get('ticket_id') == ticket['id']]
            if len(rows) != 1 or rows[0].get('ticket_id') != ticket['id']:
                errors.append('ticket.id not backed by exactly one created API row')
            elif rows[0].get('requester') != body.get('user') or (ticket.get('key') and rows[0].get('key') != ticket['key']):
                errors.append('ticket owner/key differs from actual API row')
        if name.startswith('WF-09 '):
            rows = [r for r in after['tickets']['tickets'] if r.get('key') == 'wf09']
            if len(rows) != 1:
                errors.append('WF-09 must create exactly one ticket')
            current = ticket.get('id') if isinstance(ticket, dict) else None
            if self.ticket_ids.get('wf09') and current != self.ticket_ids['wf09']:
                errors.append('WF-09 changed ticket.id')
            if current:
                self.ticket_ids['wf09'] = current
        if name.startswith('WF-12 '):
            if not all(word in (payload.get('answer', '') if isinstance(payload, dict) else '') for word in ['현장 발권', '접수']):
                errors.append('WF-12 needs BOTH 현장 발권 and 접수')
            if field(payload, 'ticket.priority') != 'high':
                errors.append('WF-12 priority must be high')
        if name.startswith('TM-02 '):
            answer = payload.get('answer', '') if isinstance(payload, dict) else ''
            if not re.search(r'152,?000\s*원', answer):
                errors.append('TM-02 must show refund 152,000원')
        if rules.get('no_ticket') and ticket is not None:
            errors.append('must not return ticket')
        for word in rules.get('no_exposure', []):
            if word in text:
                errors.append('forbidden exposure: ' + word)
        return errors

    def run_case(self, case, hook, repeats=None):
        name, body = case['name'], case.get('body', {})
        for step in case.get('before', []):
            self.step(step)
        baseline = self.snapshot()
        try:
            if name.startswith('TM-09 '):
                self.api('/cache-clear', {})
                for i in range(5):
                    prime = dict(body, request_id=f'tm09-prime-{i}-{time.time_ns()}')
                    status, reply, _ = http('POST', N8N + '/webhook/' + hook, prime)
                    if status != 200:
                        raise RuntimeError(f'TM-09 priming failed: {status} {reply}')
            for run in range(1, (repeats or self.repeat) + 1):
                before = self.snapshot()
                auth = case.get('auth', True)
                status, payload, seconds = http('POST', N8N + '/webhook/' + case.get('webhook', hook), body, auth=auth)
                time.sleep(self.settle)
                after = self.snapshot()
                ordinary = judge(case.get('expect', {}), status, payload, seconds) if auth else []
                strict = self.strict(name, status, payload, body, before, after, case.get('strict'), auth)
                row = {'case': name, 'run': run, 'status': status, 'seconds': round(seconds, 3), 'request': body, 'response': payload,
                       'ordinary_errors': ordinary, 'strict_errors': strict, 'passed': not ordinary and not strict}
                self.results.append(row)
                print(('PASS' if row['passed'] else 'FAIL'), name, f'#{run}', f'{seconds:.1f}s', *ordinary, *strict, sep=' | ')
                if VERBOSE and isinstance(payload, dict):
                    print('     route:', payload.get('route'), '| answer:', str(payload.get('answer', ''))[:120].replace('\n', ' '))
            final = self.snapshot()
            expected = {}
            if name.startswith('WF-04 '):
                expected = {'dlq': 1, 'alerts': 1}
            if name.startswith('WF-12 '):
                expected = {'alerts': 1}
            expected.update(case.get('strict', {}).get('deltas', {}))
            for sink, wanted in expected.items():
                key = 'size' if sink == 'dlq' else 'count'
                actual = final[sink][key] - baseline[sink][key]
                if actual != wanted:
                    self.results[-1]['strict_errors'].append(f'case {sink} delta {actual}, expected {wanted}')
                    self.results[-1]['passed'] = False
                    print('FAIL | case aggregate', name, sink, actual, 'expected', wanted)
        finally:
            for step in case.get('after', []):
                self.step(step)

    def suite(self, path):
        suite = json.loads(Path(path).read_text())
        self.reset()
        for step in suite.get('before', []):
            self.step(step)
        try:
            for case in suite['cases']:
                self.run_case(case, suite.get('webhook', 'ticketmoa-support'))
        finally:
            for step in suite.get('after', []):
                self.step(step)

    def save(self, label):
        (ROOT / 'runs').mkdir(exist_ok=True)
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        path = ROOT / 'runs' / f'{label}-{stamp}.json'
        passed = sum(r['passed'] for r in self.results)
        path.write_text(json.dumps({'label': label, 'date': str(datetime.date.today()), 'n8n': N8N, 'passed': passed,
                                    'total': len(self.results), 'results': self.results}, ensure_ascii=False, indent=2))
        lines = [f'{label} {passed}/{len(self.results)} ({stamp})']
        for r in self.results:
            lines.append(('PASS ' if r['passed'] else 'FAIL ') + f"{r.get('case')} #{r.get('run', '')} {r.get('seconds', '')}s "
                         + ' | '.join(r.get('ordinary_errors', []) + r.get('strict_errors', []) + ([r['error']] if 'error' in r else [])))
        path.with_suffix('.txt').write_text('\n'.join(lines) + '\n')
        print(f'결과 {passed}/{len(self.results)} → {path.relative_to(ROOT)}')
        return passed == len(self.results)


def ready():
    deadline = time.monotonic() + 90
    urls = [N8N + '/healthz/readiness', DATA_API + '/health']
    while time.monotonic() < deadline:
        if all(http('GET', url, timeout=2)[0] == 200 for url in urls):
            print('ready:', *urls)
            return
        time.sleep(1)
    raise RuntimeError('n8n 또는 데이터 API 가 90초 안에 준비되지 않음')


def main():
    global VERBOSE
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--suite', choices=['common', 'team', 'all'], default='common')
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--wait-ready', action='store_true')
    parser.add_argument('--index', action='store_true')
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()
    VERBOSE = args.verbose
    if args.repeat < 1:
        parser.error('--repeat must be positive')
    if not TEAM_KEY:
        parser.error('TM_TEAM_KEY 가 없다 (.env 또는 환경변수)')
    if args.wait_ready:
        ready()
        return 0
    if args.index:
        status, payload, seconds = http('POST', N8N + '/webhook/ticketmoa-index', {}, timeout=180)
        print(f'index {status} {seconds:.1f}s', json.dumps(payload, ensure_ascii=False)[:500])
        if status != 200 or not isinstance(payload, dict) or payload.get('error') or payload.get('ready') is False:
            return 1
        status, hits, _ = http('POST', N8N + '/webhook/ticketmoa-search', {'query': 'QR 모바일티켓', 'access_level': 'all', 'top_k': 3})
        ok = status == 200 and isinstance(hits, dict) and bool(hits.get('hits'))
        print('search', status, 'hits', len(hits.get('hits', [])) if isinstance(hits, dict) else hits)
        return 0 if ok else 1
    runner = Runner(repeat=args.repeat)
    label = args.suite
    try:
        for name in ['common', 'team']:
            if args.suite in (name, 'all'):
                runner.suite(ROOT / 'cases' / f'{name}.json')
    except (RuntimeError, ValueError, KeyError) as e:
        runner.results.append({'case': 'infrastructure', 'passed': False, 'error': str(e)})
        print('INFRASTRUCTURE FAILURE:', e)
    finally:
        try:
            runner.api('/admin/fault', {'tickets': 'ok', 'faq': 'ok', 'dlq': 'ok', 'prompts': 'ok', 'usage': 'ok'})
        except RuntimeError:
            pass
    return 0 if runner.save(label) else 1


if __name__ == '__main__':
    raise SystemExit(main())
