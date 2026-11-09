import contextlib
import io
import unittest
from pathlib import Path
from types import SimpleNamespace

from tools.flow_hooks import HookFailure, install_strict_hooks


class StrictHooksTests(unittest.TestCase):
    def run_suite(self, suite, statuses=None, llm_failure=None, no_before=False):
        events = []
        statuses = statuses or {}

        def http(_method, target, _body):
            events.append(target)
            return statuses.get(target, 200), {}, 0.01

        def llm(args):
            events.append('llm:' + args.state)
            return int(args.state == llm_failure)

        def run_case(_args, case, _hook, results):
            events.append(case['name'])
            results.append(case['name'])
            return 1

        flow = SimpleNamespace(
            OK='OK', WARN='WARN', BAD='BAD', N8N_URL='http://unused',
            time=SimpleNamespace(sleep=lambda _: None), cmd_llm=llm, http=http,
            request_body=lambda value: value, detail=lambda *args: None,
            run_case=run_case, finish=lambda *args: events.append('finished') or 0,
            resolve=Path, load_json=lambda _: suite,
            die=lambda text: (_ for _ in ()).throw(RuntimeError(text)),
        )
        install_strict_hooks(flow)
        args = SimpleNamespace(cases='suite.json', webhook=None, no_before=no_before, repeat=1)
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                flow.cmd_test(args)
            except HookFailure as error:
                return events, str(error)
        return events, None

    def test_partial_case_preparation_failure_restores_and_stops(self):
        events, error = self.run_suite({'webhook': 'test', 'cases': [
            {'name': 'first', 'before': [{'url': 'prepare'}, {'url': 'bad'}], 'after': [{'url': 'restore'}]},
            {'name': 'second'}]}, {'bad': 503})
        self.assertEqual(events, ['prepare', 'bad', 'restore'])
        self.assertIn('before hook failed', error)

    def test_http_cleanup_failure_stops_later_cases_and_restores_suite(self):
        events, error = self.run_suite({'webhook': 'test', 'after': [{'url': 'suite-restore'}], 'cases': [
            {'name': 'first', 'after': [{'url': 'bad'}]}, {'name': 'second'}]}, {'bad': 503})
        self.assertEqual(events, ['first', 'bad', 'suite-restore'])
        self.assertIn('cleanup failed', error)

    def test_failed_llm_restore_stops_later_cases(self):
        events, error = self.run_suite({'webhook': 'test', 'cases': [
            {'name': 'first', 'before': [{'llm': 'down'}], 'after': [{'llm': 'up'}]},
            {'name': 'second'}]}, llm_failure='up')
        self.assertEqual(events, ['llm:down', 'first', 'llm:up'])
        self.assertIn('LLM up', error)

    def test_global_preparation_failure_still_restores(self):
        events, error = self.run_suite({'webhook': 'test', 'before': [{'url': 'bad'}],
            'after': [{'url': 'restore'}], 'cases': [{'name': 'first'}]}, {'bad': 503})
        self.assertEqual(events, ['bad', 'restore'])
        self.assertIsNotNone(error)

    def test_all_cleanup_steps_attempted_after_one_failure(self):
        events, error = self.run_suite({'webhook': 'test', 'cases': [
            {'name': 'first', 'after': [{'url': 'bad'}, {'url': 'second-restore'}]}]}, {'bad': 503})
        self.assertEqual(events, ['first', 'bad', 'second-restore'])
        self.assertIsNotNone(error)

    def test_cleanup_cannot_ignore_failure_with_allow_fail(self):
        events, error = self.run_suite({'webhook': 'test', 'cases': [
            {'name': 'first', 'after': [{'url': 'bad', 'allow_fail': True}]}, {'name': 'second'}]}, {'bad': 503})
        self.assertEqual(events, ['first', 'bad'])
        self.assertIsNotNone(error)

    def test_expected_error_status_is_valid_hook(self):
        events, error = self.run_suite({'webhook': 'test', 'cases': [
            {'name': 'first', 'before': [{'url': 'expected', 'status': 409}]}, {'name': 'second'}]}, {'expected': 409})
        self.assertEqual(events, ['expected', 'first', 'second', 'finished'])
        self.assertIsNone(error)

    def test_no_before_preserves_case_hooks_and_cleanup(self):
        events, error = self.run_suite({'webhook': 'test', 'before': [{'url': 'suite-prepare'}],
            'after': [{'url': 'suite-restore'}], 'cases': [
            {'name': 'first', 'before': [{'url': 'case-prepare'}], 'after': [{'url': 'case-restore'}]}]}, no_before=True)
        self.assertEqual(events, ['case-prepare', 'first', 'case-restore', 'finished', 'suite-restore'])
        self.assertIsNone(error)


if __name__ == '__main__':
    unittest.main()
