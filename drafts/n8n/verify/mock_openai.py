#!/usr/bin/env python3
"""Offline deterministic OpenAI fixture. No credentials or outbound requests.
Role markers and output schemas are from BRIEF-codex-2, not generated workflows.
"""
import hashlib
import json
import math
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CONCEPTS = [
    ['qr', '모바일티켓', '마이티켓'], ['로그인', '인증', '계정', '비밀번호'],
    ['결제', '이중결제', '승인'], ['환불', '취소', '수수료'],
    ['주차'], ['입장 시간', '입장시간', '관람 연령'], ['매크로', '보안 문자', '해외', 'vpn'],
    ['암표', '웃돈', '중고 사이트'], ['현장 발권', '대체 입장', '공연 10분', '공연 시작'],
    ['스태프', '수기', '책임자 코드'],
]
LOCK = threading.Lock()
STATE = {'mode': 'ok', 'slow_seconds': 8}
STATS = {'chat_calls': 0, 'embedding_calls': 0, 'by_role': {}, 'requests': []}
MODES = {'ok', 'down', 'bad_json', 'bad_shape', 'slow', 'verifier_reject'}


def embedding(text):
    """Concept vectors share a 0.995 basis; concept-free hash is orthogonal.
    Hash noise is signed and deterministic, so unrelated inputs do not all match.
    The padded 3072 dimensions match text-embedding-3-large's default size.
    """
    text = str(text).lower()
    counts = [sum(text.count(word) for word in words) for words in CONCEPTS]
    # Saturate counts: repeating a word must not drown out a second concept.
    counts = [math.sqrt(v) for v in counts]
    norm = math.sqrt(sum(v*v for v in counts)) or 1
    noise = hashlib.sha256(text.encode()).digest()
    vec = [v/norm for v in counts] + [(b/127.5-1)*0.015 for b in noise]
    norm = math.sqrt(sum(v*v for v in vec)) or 1
    return [v/norm for v in vec] + [0.0]*(3072-len(vec))


def tagged(text, tag):
    match = re.search(rf'<{tag}>(.*?)</{tag}>', text, re.S | re.I)
    return match.group(1).strip() if match else ''


def triage(question):
    q = question.lower()
    intents = []
    entities = {}
    for key, pattern in [('record_id', r'\bC-\d+\b'), ('booking_id', r'\bT\d{8}-\d+\b')]:
        hit = re.search(pattern, question, re.I)
        if hit:
            entities[key] = hit.group().upper()
    vague = bool(re.search(r'어제부터.*안\s*돼|계속 안\s*돼|그게 안\s*돼', q)) and not any(w in q for words in CONCEPTS for w in words)
    if '제휴 카드 포인트' not in q and not vague:
        if any(w in q for w in ['qr', '모바일티켓', '게이트']): intents.append('tech_issue')
        if any(w in q for w in ['로그인', '인증', '비밀번호']): intents.append('account_issue')
        if any(w in q for w in ['주차', '입장 시간', '관람 연령', '물품']): intents.append('general_info')
        if any(w in q for w in ['취소', '환불']): intents.append('refund_request')
        if any(w in q for w in ['두 번 결제', '이중결제', '결제 실패', '결제됐', '결제한']): intents.append('payment_error')
        if any(w in q for w in ['매크로', '해외', 'vpn']): intents.append('fair_booking')
        if any(w in q for w in ['암표', '신고', '두 배 가격', '웃돈']): intents.append('scalping_report')
        if any(w in q for w in ['상담원', '직접 통화', '사람이랑']): intents.append('human_request')
        if entities.get('record_id') and any(w in q for w in ['상태', '상황', '어떻게 됐', '확인', '처리']): intents.append('booking_lookup')
    registry = Path(__file__).with_name('registry.json')
    if not registry.exists(): registry = Path(__file__).resolve().parents[3]/'config/registry.json'
    allowed = {x['intent_id'] for x in json.loads(registry.read_text())['intents']}
    return {'intents': [i for i in dict.fromkeys(intents) if i in allowed], 'entities': entities,
            'sentiment': 'angry' if any(w in q for w in ['짜증', '화나', '최악']) else 'neutral',
            'urgency': 'high' if re.search(r'(10|20|30)분\s*전|공연 직전', q) else 'normal',
            'confidence': 0.3 if vague else 0.9, 'clarity': 'vague' if vague else 'clear'}


def writer(context, question=''):
    """Extract at most five relevant source sentences; never concatenate all hits.
    Section concepts are inherited by short factual sentences (e.g. restriction
    duration without repeating the word 'macro'). No scenario-specific response.
    """
    if not context or context.strip() in ('[]', '{}', 'null'):
        return {'answer': '근거를 찾지 못했습니다.', 'grounded': False}
    try:
        value = json.loads(context)
        def texts(v):
            if isinstance(v, str): return [v]
            if isinstance(v, list): return [s for x in v for s in texts(x)]
            if isinstance(v, dict):
                for key in ('text', 'pageContent', 'content'):
                    if key in v: return texts(v[key])
                return [s for key in ('hits', 'documents', 'context') if key in v for s in texts(v[key])]
            return []
        context = '\n'.join(texts(value))
    except ValueError:
        pass
    q = question.lower()
    concepts = lambda text: {i for i, words in enumerate(CONCEPTS) if any(w in text.lower() for w in words)}
    qconcepts = concepts(q)
    terms = {t for t in re.findall(r'[가-힣a-z0-9]+', q) if len(t) >= 2}
    temporal = bool(re.search(r'언제|며칠|몇\s*시간|얼마나|풀려|풀리', q))
    candidates, section_concepts, section_text = [], set(), ''
    lines = context.splitlines()
    for line_index, line in enumerate(lines):
        line = line.strip()
        if line.startswith('##'):
            section_concepts = concepts(line)
            section_text = line.lower()
            continue
        if not line or line.startswith(('#', '>', '|')) or re.match(r'^\[\d+\]', line):
            continue
        if line_index+1 < len(lines) and lines[line_index+1].lstrip().startswith('##'):
            continue  # document title before section heading is not an answer sentence
        line = re.sub(r'^\s*(?:[-*]\s+|\d+\.\s+)', '', line).replace('**', '')
        for sentence in re.split(r'(?<=[.!?。])\s+', line):
            sentence = sentence.strip()
            if not sentence: continue
            direct = concepts(sentence)
            score = 3*len(qconcepts & direct) + len(qconcepts & section_concepts)
            score += sum(t in sentence.lower() for t in terms)
            score += 3*sum(word in q and (word in sentence.lower() or word in section_text)
                           for words in CONCEPTS for word in words)
            if temporal and re.search(r'\d+\s*(시간|일|분)', sentence): score += 4
            candidates.append((score, len(candidates), sentence))
    ranked = sorted(candidates, key=lambda c: (-c[0], c[1]))
    selected, length, seen = [], 0, set()
    for score, index, sentence in ranked:
        if question and qconcepts and score <= 0: continue
        if sentence in seen or length + len(sentence) + 1 > 780: continue
        seen.add(sentence); selected.append((index, sentence)); length += len(sentence)+1
        if len(selected) == 5: break
    answer = '\n'.join(sentence for _, sentence in sorted(selected))
    return {'answer': answer or '근거를 찾지 못했습니다.', 'grounded': bool(selected)}


def completion(body):
    messages = body.get('messages', [])
    system = '\n'.join(str(m.get('content', '')) for m in messages if m.get('role') in ('system', 'developer'))
    user = '\n'.join(str(m.get('content', '')) for m in messages if m.get('role') == 'user')
    role = next((r for r in ('triage', 'writer', 'verifier') if f'[ROLE:{r}]' in system), 'unknown')
    with LOCK:
        mode, delay = STATE['mode'], STATE['slow_seconds']
        STATS['chat_calls'] += 1
        STATS['by_role'][role] = STATS['by_role'].get(role, 0)+1
        STATS['requests'].append({'kind': 'chat', 'role': role, 'messages': messages})
    if mode == 'slow': time.sleep(delay)
    if mode == 'down': return 401, {'error': {'message': 'mock down', 'type': 'invalid_api_key'}}
    if role == 'unknown': return 400, {'error': {'message': 'Missing system ROLE marker'}}
    if mode == 'bad_json': content = '{broken-json'
    elif mode == 'bad_shape': content = json.dumps({'intents': {}, 'confidence': 'high', 'answer': [], 'grounded': 'true', 'policy_ok': 'true'})
    else:
        value = (triage(tagged(user, 'question')) if role == 'triage' else
                 writer(tagged(user, 'context'), tagged(user, 'question')) if role == 'writer' else
                 {'relevant': mode != 'verifier_reject', 'grounded': mode != 'verifier_reject', 'policy_ok': mode != 'verifier_reject',
                  'issues': ['mock rejected'] if mode == 'verifier_reject' else []})
        content = json.dumps(value, ensure_ascii=False)
    return 200, {'id': 'chatcmpl-mock', 'object': 'chat.completion', 'created': int(time.time()),
                 'model': body.get('model', 'gpt-4.1-mini'),
                 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': content}, 'finish_reason': 'stop'}],
                 'usage': {'prompt_tokens': 10, 'completion_tokens': 10, 'total_tokens': 20}}


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body):
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code); self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        if self.path == '/admin/stats':
            with LOCK: result = json.loads(json.dumps(STATS))
            return self.send(200, result)
        if self.path in ('/health', '/admin/state'): return self.send(200, dict(STATE))
        if self.path == '/v1/models': return self.send(200, {'object': 'list', 'data': [{'id': x, 'object': 'model', 'owned_by': 'mock'} for x in ['gpt-4.1-mini', 'text-embedding-3-large']]})
        self.send(404, {'error': 'unknown path'})

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            if not isinstance(body, dict): raise ValueError()
        except (ValueError, TypeError): return self.send(400, {'error': 'object body required'})
        if self.path == '/admin/state':
            if body.get('mode', 'ok') not in MODES: return self.send(400, {'error': 'invalid mode'})
            delay = body.get('slow_seconds', 8)
            if not isinstance(delay, (int, float)) or not math.isfinite(delay) or not 0 <= delay <= 60:
                return self.send(400, {'error': 'invalid slow_seconds'})
            with LOCK:
                STATE.update(mode=body.get('mode', 'ok'), slow_seconds=delay)
                if body.get('reset_stats'):
                    STATS.update(chat_calls=0, embedding_calls=0, by_role={}, requests=[])
            return self.send(200, dict(STATE))
        if self.path == '/v1/chat/completions':
            code, result = completion(body)
            if code != 200 or not body.get('stream'): return self.send(code, result)
            self.send_response(200); self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Connection', 'close'); self.end_headers()
            for delta, finish in [({'role': 'assistant', 'content': result['choices'][0]['message']['content']}, None), ({}, 'stop')]:
                chunk = {k: result[k] for k in ('id', 'created', 'model')}
                chunk.update(object='chat.completion.chunk', choices=[{'index': 0, 'delta': delta, 'finish_reason': finish}])
                self.wfile.write(('data: '+json.dumps(chunk, ensure_ascii=False)+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n'); self.wfile.flush(); return
        if self.path == '/v1/embeddings':
            inputs = body.get('input', [])
            if isinstance(inputs, str): inputs = [inputs]
            if not isinstance(inputs, list): return self.send(400, {'error': 'invalid input'})
            with LOCK:
                STATS['embedding_calls'] += 1
                STATS['requests'].append({'kind': 'embedding', 'input': inputs})
                mode, delay = STATE['mode'], STATE['slow_seconds']
            if mode == 'slow': time.sleep(delay)
            if mode == 'down': return self.send(401, {'error': {'message': 'mock down'}})
            if inputs and isinstance(inputs[0], int): inputs = [inputs]
            def decode(v):
                if isinstance(v, str): return v
                # OpenAI clients may tokenize. Keep explicit failure rather than inventing semantics.
                raise ValueError('Token-array embeddings unsupported; send raw strings (encoding_format=float)')
            try:
                data = [{'object': 'embedding', 'index': i, 'embedding': embedding(decode(v))} for i, v in enumerate(inputs)]
            except ValueError as e: return self.send(400, {'error': {'message': str(e)}})
            if body.get('encoding_format') == 'base64':
                import base64, struct
                for item in data: item['embedding'] = base64.b64encode(struct.pack('<3072f', *item['embedding'])).decode()
            return self.send(200, {'object': 'list', 'model': 'text-embedding-3-large', 'data': data, 'usage': {'prompt_tokens': len(inputs), 'total_tokens': len(inputs)}})
        self.send(404, {'error': 'unknown path'})

    def log_message(self, *args): pass


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', int(os.getenv('PORT', '8898'))), Handler).serve_forever()
