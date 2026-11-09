"""수업 원본을 수정하지 않고 팀 시험의 준비·복구 hook 실패를 전파한다."""
from argparse import Namespace


class HookFailure(RuntimeError):
    pass


def install_strict_hooks(flow):
    def run_step(label, step):
        if 'sleep' in step:
            flow.time.sleep(float(step['sleep']))
            return
        if step.get('llm') in ('down', 'up'):
            state = step['llm']
            good = flow.cmd_llm(Namespace(state=state)) == 0
            detail = 'LLM ' + state
            if good and state == 'down':
                flow.time.sleep(1)
        else:
            target = step.get('url') or f"{flow.N8N_URL}/webhook/{str(step.get('webhook', '')).strip('/')}"
            body = flow.request_body(step.get('body') or step.get('request', '{}'))
            status, payload, seconds = flow.http('POST', target, body)
            good = status == step['status'] if 'status' in step else 200 <= status < 300
            detail = f'HTTP {status} · {seconds:.1f}s'
            flow.detail(f'{label}: request', body)
            flow.detail(f'{label}: response HTTP {status}', payload)
        allowed_failure = label == 'before' and step.get('allow_fail') and 'llm' not in step
        print(f"{flow.OK if good else flow.WARN if allowed_failure else flow.BAD} {label}: {detail}")
        if not good and not allowed_failure:
            raise HookFailure(f'{label} hook failed ({detail}); subsequent cases stopped')

    def cleanup(steps):
        failures = []
        for step in steps:
            try:
                run_step('after', step)
            except (Exception, SystemExit) as error:
                failures.append(str(error))
        if failures:
            raise HookFailure('cleanup failed; subsequent cases stopped: ' + '; '.join(failures))

    def run_cases(args, path, suite, hook, cases):
        print(f'{len(cases)} case(s) × {args.repeat}')
        results, passed = [], 0
        for case in cases:
            try:
                for step in case.get('before', []):
                    run_step('before', step)
                passed += flow.run_case(args, case, hook, results)
            finally:
                cleanup(case.get('after', []))
        return flow.finish(path, hook, results, passed)

    def cmd_test(args):
        path = flow.resolve(args.cases)
        suite = flow.load_json(path)
        hook = (args.webhook or suite.get('webhook', '')).strip('/')
        cases = suite.get('cases', [])
        if not hook or not cases:
            flow.die('test suite needs webhook and non-empty cases')
        try:
            if not args.no_before:
                for step in suite.get('before', []):
                    run_step('before', step)
            return run_cases(args, path, suite, hook, cases)
        finally:
            cleanup(suite.get('after', []))

    flow.run_step = run_step
    flow.run_cases = run_cases
    flow.cmd_test = cmd_test
