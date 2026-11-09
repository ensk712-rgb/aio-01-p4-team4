const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const workflows = Object.fromEntries(['support', 'tech'].map(name => [name,
  JSON.parse(fs.readFileSync(path.join(__dirname, '../../workflows/ticketmoa-' + name + '.json'), 'utf8'))]));
function execute(workflow, node, input, context = {}) {
  const code = workflows[workflow].nodes.find(n => n.name === node).parameters.jsCode;
  const lookup = name => ({ first: () => ({ json: context[name] || {} }), isExecuted: name === '작성 결과 검사' });
  return new Function('$json', '$', '$execution', code)(input, lookup, { id: 1 })[0].json;
}
function collectAndLog(result) {
  const context = {
    'Plan route': { used: [], llm_calls: 1, steps: {}, intents: ['tech_issue'], confidence: 0.9 },
    'Tech input': { steps: {}, t_tech: Date.now() },
    'Question webhook': { body: { request_id: 'regression', channel: 'web' } },
    'Check input': { started_at: Date.now() },
  };
  const collected = execute('support', 'Collect tech', result, context);
  const response = execute('support', 'Build response', collected, context);
  return { response, log: execute('support', 'Log record', response, context).log };
}
for (const [name, input, reason, issues, kind] of [
  ['검증 LLM 장애', { statusCode: 200, body: { ok: false, issues: ['llm_unavailable'], llm_calls: 1 } }, 'verification_failed', ['llm_unavailable'], 'dependency'],
  ['검증 timeout', { error: 'timeout' }, 'verification_timeout', [], 'dependency'],
  ['검증 품질 거절', { statusCode: 200, body: { ok: false, issues: ['not_grounded'], llm_calls: 1 } }, 'verification_failed', ['not_grounded'], 'verification_rejected'],
]) {
  test(name + ': 정상 답변·무근거로 숨기지 않고 응답과 로그에 사유 보존', () => {
    const result = execute('tech', '답변 결정', input, { '작성 결과 검사': { answer: '검증 전 초안', hits: [] } });
    const { response, log } = collectAndLog(result);
    assert.equal(response.route, '담당자 이관');
    assert.equal(response.reason, reason);
    assert.deepEqual(response.agents.verification_issues, issues);
    assert.deepEqual(response.sources, []);
    assert.ok(!response.answer.includes('검증 전 초안'));
    assert.equal(log.status, 'error');
    assert.equal(log.reason, reason);
    assert.deepEqual(log.verification_issues, issues);
    assert.equal(log.failure_kind, kind);
  });
}
test('작성 LLM 장애와 실제 무근거는 로그에서도 구별', () => {
  const failed = collectAndLog(execute('tech', '작성 실패 결과', { error: 'timeout' }));
  const missing = collectAndLog(execute('tech', '근거 없음 결과', {}));
  assert.equal(failed.response.reason, 'llm_unavailable');
  assert.equal(failed.log.status, 'error');
  assert.equal(missing.response.reason, 'no_evidence');
  assert.equal(missing.log.status, 'success');
  assert.equal(missing.log.failure_kind, 'no_evidence');
});
test('티켓 생성 실패(WF-04)는 사유가 정상 분류값이어도 error 로그, 티켓이 있으면 success', () => {
  const { classifyOutcome } = require('../common.js');
  const failed = classifyOutcome({ reason: 'unregistered_intent', ticket: null, agents: { handoff: { dlq: true, alert: true } } });
  assert.equal(failed.status, 'error');
  assert.equal(failed.reason, 'unregistered_intent');
  assert.equal(failed.failure_kind, 'dependency');
  assert.equal(failed.error_message, 'ticket_not_created');
  const created = classifyOutcome({ reason: 'unregistered_intent', ticket: { id: 'T-1' }, agents: { handoff: { dlq: false, alert: false } } });
  assert.equal(created.status, 'success');
  assert.equal(created.failure_kind, '');
});
