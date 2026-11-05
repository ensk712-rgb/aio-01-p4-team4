// 실제 응답 모양(runs/ 보고서에서 옮김)으로 경로 재생 순서를 확인한다.
const test = require('node:test');
const assert = require('node:assert');
const { buildPath } = require('../static/flow.js');

const ids = (p) => p.order.map((o) => o.ids.join('+'));

test('WF-01 자동 답변: 분류 → 검색 → 작성·검증', () => {
  const p = buildPath(200, { route: '자동 답변', reason: '', sources: [{ score: 0.63 }], ticket: null,
    agents: { used: ['ticketmoa-agents', 'ticketmoa-search', 'ticketmoa-tech'], llm_calls: 3, intents: ['tech_issue'], confidence: 0.95 },
    security: { blocked_by: '' }, timings: { total_ms: 5218, agents_ms: 2065, search_ms: 524, tech_ms: 2582 } });
  assert.deepStrictEqual(ids(p), ['input', 'guard', 'agents', 'search', 'tech', 'reply']);
  assert.strictEqual(p.states.tech.state, 'done');
  assert.strictEqual(p.llm, 3);
});

test('WF-12 긴급: 검색·조회 함께, 이관에 티켓·알림', () => {
  const p = buildPath(200, { route: '담당자 이관', sources: [], ticket: { id: 'T-2007', priority: 'high' },
    agents: { used: ['ticketmoa-agents', 'ticketmoa-search', 'ticketmoa-tech', 'ticketmoa-payment', 'ticketmoa-handoff'], llm_calls: 3,
      alert: { channel: 'venue-staff' } }, security: {}, timings: {} });
  assert.deepStrictEqual(ids(p), ['input', 'guard', 'agents', 'search+payment', 'tech', 'handoff', 'reply']);
  assert.match(p.states.handoff.note, /T-2007 · 긴급 · 현장 알림/);
});

test('WF-08 주입: 보안 규칙에서 멈춤, LLM 0회', () => {
  const p = buildPath(200, { route: '차단', agents: { used: [], llm_calls: 0 }, security: { blocked_by: 'rule' }, timings: { total_ms: 7 } });
  assert.deepStrictEqual(ids(p), ['input', 'guard', 'reply']);
  assert.strictEqual(p.states.guard.state, 'stop');
});

test('WF-06 남의 건: 조회에서 거절', () => {
  const p = buildPath(200, { route: '권한 없음', reason: 'not_owner', agents: { used: ['ticketmoa-agents', 'ticketmoa-payment'], llm_calls: 0 }, security: {}, timings: {} });
  assert.strictEqual(p.states.payment.state, 'stop');
});

test('TM-03 환불 확정: 분류 생략, 환불 → 티켓', () => {
  const p = buildPath(200, { route: '담당자 이관', ticket: { id: 'T-2001' }, agents: { used: ['ticketmoa-refund'], llm_calls: 0, pending_action: null }, security: {}, timings: {} });
  assert.deepStrictEqual(ids(p), ['input', 'guard', 'refund', 'handoff', 'reply']);
});

test('400 입력 거절', () => {
  const p = buildPath(400, { error: 'invalid request', codes: ['empty_question'] });
  assert.deepStrictEqual(ids(p), ['input']);
  assert.strictEqual(p.route, '입력 거절');
});
