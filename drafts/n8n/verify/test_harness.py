"""Focused offline checks for the independent fixture and runner (no Docker/API keys)."""
import ast
import copy
import io
import json
import math
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer

import mock_openai as mock
import runner


def response(**updates):
    value={'request_id':'unit','route':'자동 답변','answer':'안내','sources':[], 'ticket':None,
           'agents':{'llm_calls':0},'security':{'blocked_by':'','reason':'','masked':0},'timings':{'total_ms':1},'reason':''}
    value.update(updates)
    return value


def snapshot():
    return {'tickets':{'count':0,'tickets':[]},'dlq':{'size':0,'items':[]},'alerts':{'count':0,'alerts':[]},
            'logs':{'count':0,'logs':[]},'mock':{'chat_calls':0,'embedding_calls':0,'requests':[]}}


class MockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),mock.Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base='http://127.0.0.1:'+str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()

    def request(self,path,body=None):
        req=urllib.request.Request(self.base+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=2) as r:return r.status,r.read()
        except urllib.error.HTTPError as e:return e.code,e.read()

    def setUp(self):self.request('/admin/state',{'mode':'ok','reset_stats':True})

    def chat(self,role='triage',question='QR이 안 떠요',**kwargs):
        return self.request('/v1/chat/completions',{'model':'gpt-4.1-mini','messages':[
            {'role':'system','content':'[ROLE:'+role+']'}, {'role':'user','content':'<question>'+question+'</question><context>앱을 업데이트한다.</context>'}],**kwargs})

    def test_triage_semantics(self):
        self.assertEqual(mock.triage('어제부터 계속 안 돼요')['clarity'],'vague')
        outside=mock.triage('제휴 카드 포인트가 적립이 안 됐어요')
        self.assertEqual((outside['intents'],outside['clarity'],outside['confidence']),([], 'clear',0.9))
        both=mock.triage('공연 10분 전 QR 안 떠요 C-2002 처리 상태 확인')
        self.assertEqual(set(both['intents']),{'tech_issue','booking_lookup'})
        self.assertEqual(both['entities']['record_id'],'C-2002')
        self.assertEqual(both['urgency'],'high')
        self.assertEqual(mock.triage('두 번 결제돼서 짜증나네요')['sentiment'],'angry')

    def test_embedding_thresholds_and_determinism(self):
        def cosine(a,b):return sum(x*y for x,y in zip(a,b))
        qr=mock.embedding('QR 모바일티켓')
        self.assertEqual(len(qr),3072)
        self.assertEqual(qr,mock.embedding('QR 모바일티켓'))
        self.assertAlmostEqual(sum(x*x for x in qr),1)
        self.assertGreater(cosine(qr,mock.embedding('QR이 안 떠요')),0.8)
        self.assertLess(cosine(qr,mock.embedding('제휴 카드 포인트')),0.2)
        self.assertLess(cosine(qr,mock.embedding('주차 안내')),0.2)

    def test_chat_modes_and_stats(self):
        status,data=self.chat();self.assertEqual(status,200)
        result=json.loads(json.loads(data)['choices'][0]['message']['content'])
        self.assertIn('tech_issue',result['intents'])
        for mode in ['down','bad_json','bad_shape','verifier_reject','slow']:
            self.request('/admin/state',{'mode':mode,'slow_seconds':0.01})
            status,data=self.chat('verifier' if mode=='verifier_reject' else 'triage')
            self.assertEqual(status,401 if mode=='down' else 200)
            if mode=='bad_json':
                with self.assertRaises(ValueError):json.loads(json.loads(data)['choices'][0]['message']['content'])
            if mode=='bad_shape':self.assertIsInstance(json.loads(json.loads(data)['choices'][0]['message']['content'])['intents'],dict)
            if mode=='verifier_reject':self.assertIs(json.loads(json.loads(data)['choices'][0]['message']['content'])['policy_ok'],False)
        _,data=self.request('/admin/stats');stats=json.loads(data)
        self.assertEqual(stats['chat_calls'],6);self.assertEqual(len(stats['requests']),6)
        self.assertIn('<question>',stats['requests'][0]['messages'][1]['content'])

    def test_writer_extracts_only_context(self):
        self.assertFalse(mock.writer('[]')['grounded'])
        self.assertEqual(mock.writer('[{"doc":"x","text":"앱을 업데이트한다."}]')['answer'],'앱을 업데이트한다.')
        self.assertEqual(mock.writer('새로고침한다.\n현장 발권 창구로 간다.')['answer'],'새로고침한다.\n현장 발권 창구로 간다.')

    def test_writer_selects_relevant_five_sentences(self):
        context = (runner.ROOT/'knowledge/fair-booking-policy.md').read_text()
        result = mock.writer(context, '매크로 쓴 적 없는데 의심받아서 예매가 막혔어요. 언제 풀려요?')
        self.assertTrue(result['grounded'])
        self.assertIn('24시간', result['answer'])
        self.assertLessEqual(len(result['answer'].splitlines()), 5)
        self.assertLessEqual(len(result['answer']), 780)
        self.assertNotIn('해외 예매 인증', result['answer'])
        self.assertEqual(mock.writer('주차는 3,000원입니다. 로그인은 다시 시도합니다.', '로그인 방법')['answer'], '로그인은 다시 시도합니다.')

    def test_embeddings_http_and_models(self):
        status,data=self.request('/v1/embeddings',{'input':['QR','주차']})
        self.assertEqual(status,200);self.assertEqual(len(json.loads(data)['data']),2)
        status,data=self.request('/v1/embeddings',{'input':'QR','encoding_format':'base64'})
        self.assertIsInstance(json.loads(data)['data'][0]['embedding'],str)
        self.request('/admin/state',{'mode':'down'})
        self.assertEqual(self.request('/v1/embeddings',{'input':'QR'})[0],401)
        self.assertEqual(self.request('/v1/models')[0],200)

    def test_stream_and_invalid_inputs(self):
        status,data=self.chat(stream=True)
        self.assertEqual(status,200);self.assertIn(b'[DONE]',data)
        self.assertEqual(self.request('/admin/state',{'mode':'unknown'})[0],400)
        self.assertEqual(self.request('/admin/state',{'slow_seconds':-1})[0],400)
        self.assertEqual(self.chat('unknown')[0],400)


class RunnerTests(unittest.TestCase):
    def setUp(self):self.r=runner.Runner(settle=0)

    def test_judges_are_exact_course_copies(self):
        original=runner.ROOT.parent/'aio-01d4-stu/Last3Mon/77/tools/flow.py'
        source=original.read_text();ours=Path(runner.__file__).read_text()
        def funcs(s):return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(s).body if isinstance(n,ast.FunctionDef)}
        a,b=funcs(source),funcs(ours)
        for name in ['field','as_text','judge']:self.assertEqual(a[name],b[name])
        self.assertFalse(runner.judge({'contains':{'answer':['A','B']}},200,{'answer':'A'}))
        # Course's null-ticket false positive intentionally retained, strict must catch it.
        self.assertFalse(runner.judge({'not_contains':{'ticket':['null']}},200,{'ticket':None}))

    def test_strict_catches_missing_ticket_and_contract(self):
        self.assertFalse(self.r.format_errors(200,response(),{'request_id':'unit'}))
        errors=self.r.strict('WF-03 지식에 없음',200,response(),{'request_id':'unit'},snapshot(),snapshot())
        self.assertIn('required ticket.id missing',errors)
        p=response();del p['security']
        self.assertTrue(self.r.format_errors(200,p,{'request_id':'unit'}))
        self.assertTrue(self.r.format_errors(400,{'error':'request_id_conflict'},{'request_id':'unit'}))

    def test_strict_catches_privacy_every_sink(self):
        for sink in ['tickets','dlq','alerts','logs']:
            after=snapshot();after[sink]['leak']=self.r.contacts[0]
            errors=self.r.strict('unit',200,response(),{'request_id':'unit'},snapshot(),after)
            self.assertTrue(any(sink+' raw contact' in e for e in errors))

    def test_wf08_calls_wf12_both_words_tm02_amount(self):
        after=snapshot();after['mock']['chat_calls']=1
        self.assertTrue(any('zero mock' in e for e in self.r.strict('WF-08 주입',200,response(),{'request_id':'unit'},snapshot(),after)))
        errors=self.r.strict('WF-12 복합',200,response(answer='현장 발권'),{'request_id':'unit'},snapshot(),snapshot())
        self.assertTrue(any('BOTH' in e for e in errors))
        errors=self.r.strict('TM-02 환불',200,response(answer='환불 152,000원, 수수료 0원'),{'request_id':'unit'},snapshot(),snapshot())
        self.assertFalse(errors)
        self.assertTrue(self.r.strict('TM-02 환불',200,response(answer='환불 0원'),{'request_id':'unit'},snapshot(),snapshot()))

    def test_context_injection_and_no_auth(self):
        after=snapshot();after['mock']['requests']=[{'messages':['MARKER']}]
        self.assertTrue(self.r.strict('unit',200,response(),{'request_id':'unit'},snapshot(),after,{'prompt_absent':'MARKER'}))
        self.assertEqual(self.r.strict('auth',401,{}, {},snapshot(),snapshot(),auth=False),[])
        self.assertTrue(self.r.strict('auth',200,{}, {},snapshot(),snapshot(),auth=False))

    def test_headers_url_rewrite_and_llm_hook(self):
        class Fake:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return b'{}'
        with patch('urllib.request.urlopen',return_value=Fake()) as open_url:
            runner.http('POST','http://127.0.0.1:5699/webhook/test',{})
            req=open_url.call_args.args[0]
            self.assertEqual(req.get_header('X-team-key'),runner.TEAM_KEY)
        with self.assertRaises(ValueError):runner.http('POST','http://localhost:8800/tickets-reset',{})
        with patch.object(runner,'http',return_value=(200,{},0)) as h:
            self.r.step({'url':'http://localhost:8800/admin/fault','body':{'tickets':'error'}})
            self.assertIn(':8899/admin/fault',h.call_args.args[1])
        with patch.object(self.r,'mock') as m:
            self.r.step({'llm':'down'});self.assertEqual(m.call_args.args[0],{'mode':'down'})

    def test_repeat_order_and_tm09_priming(self):
        self.r.repeat=3
        with patch.object(self.r,'snapshot',side_effect=lambda:snapshot()), patch.object(runner,'http',return_value=(200,response(),0)) as h, patch('builtins.print'):
            self.r.run_case({'name':'unit','body':{'request_id':'unit'},'expect':{}},'ticketmoa-support')
            self.assertEqual(len(self.r.results),3);self.assertEqual(h.call_count,3)
        self.r.repeat=1
        with patch.object(self.r,'snapshot',side_effect=lambda:snapshot()),patch.object(self.r,'api'),patch.object(runner,'http',return_value=(200,response(),0)) as h,patch('builtins.print'):
            self.r.run_case({'name':'TM-09 repeated','body':{'request_id':'tm09','question':'같은 질문'},'expect':{}},'ticketmoa-support')
            self.assertEqual(h.call_count,6)
            ids=[call.args[2]['request_id'] for call in h.call_args_list]
            self.assertEqual(len(set(ids)),6)

    def test_nine_fields_and_custom_contact_sink(self):
        self.assertEqual(len(runner.REQUIRED), 9)
        after=snapshot();after['logs']['logs']=[{'channel':'010-0000-9901'}]
        errors=self.r.strict('unit',200,response(),{'request_id':'unit'},snapshot(),after,{'no_raw_contacts':['010-0000-9901']})
        self.assertTrue(any('logs raw contact' in e for e in errors))

    def test_existing_ticket_requires_correct_owner_and_key(self):
        after=snapshot();after['tickets']={'count':1,'tickets':[{'ticket_id':'T-1','key':'other-key','requester':'other-user'}]}
        errors=self.r.strict('unit',200,response(ticket={'id':'T-1','key':'original-key'}),{'request_id':'unit','user':'owner'},snapshot(),after,{'allow_original_key':True})
        self.assertIn('ticket owner/key differs from actual API row',errors)

    def test_adversarial_namespace_preserves_deliberate_reuse(self):
        with patch.object(self.r,'reset'),patch.object(self.r,'run_case') as run:
            self.r.adversarial('unique-unit')
            calls=[call.args[0] for call in run.call_args_list]
            a=next(c for c in calls if c['name']=='ADV4-hash-a')
            b=next(c for c in calls if c['name']=='ADV4-hash-b')
            self.assertEqual(a['body']['request_id'],b['body']['request_id'])
            self.assertTrue(a['body']['request_id'].startswith('unique-unit-'))

    def test_adversarial_sequences_are_independent(self):
        suite=json.loads((runner.HERE/'adversarial.json').read_text())
        self.assertGreaterEqual(len(suite['groups']),18)
        self.assertTrue(all(g['basis'] for g in suite['groups']))
        auth=next(g for g in suite['groups'] if g['name']=='no-auth')
        self.assertEqual(len(auth['steps']),9)
        twice=next(g for g in suite['groups'] if g['name']=='confirm-twice')
        self.assertEqual(len(twice['steps']),3)
        self.assertNotEqual(twice['steps'][1]['body']['request_id'],twice['steps'][2]['body']['request_id'])


if __name__ == '__main__':unittest.main(verbosity=2)
