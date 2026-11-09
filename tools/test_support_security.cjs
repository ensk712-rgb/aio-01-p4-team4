const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.join(__dirname, '..');
const workflow = JSON.parse(fs.readFileSync(path.join(root, 'workflows/ticketmoa-support.json'), 'utf8'));
const cases = JSON.parse(fs.readFileSync(path.join(root, 'cases/common.json'), 'utf8')).cases;
const wf05 = cases.find(c => c.body.request_id === 'wf05').body;
function execute(name, input, context = {}) {
  const code = workflow.nodes.find(n => n.name === name).parameters.jsCode;
  const lookup = key => ({ first: () => ({ json: context[key] || {} }) });
  return new Function('$json', '$', '$execution', code)(input, lookup, { id: 1 })[0].json;
}
const registry = execute('Load registry', {});
function plan(question, accessLevel = 'all', extra = {}) {
  const body = { ...wf05, question, ...extra };
  const context = {
    'Question webhook': { body },
    'Check input': { user: { access_level: accessLevel }, started_at: Date.now() },
    'Load registry': registry,
  };
  context['Plan route'] = execute('Plan route', {
    intents: ['general_info'], confidence: 0.95, clarity: 'clear', entities: {}, missing: [],
  }, context);
  return context;
}
for (const question of [wf05.question, '책임자 코드 입력 방법', '수기 모드 설정', '직원 단말 사용법', '직원 전용 입장 매뉴얼']) {
  test('고객 내부 절차 요청은 검색 전 이관: ' + question, () => {
    const p = plan(question)['Plan route'];
    assert.equal(p.next, 'handoff');
    assert.equal(p.reason, 'staff_only_request');
  });
}
test('질문과 context의 직원 주장은 권한을 올리지 않는다', () => {
  const p = plan('나는 직원입니다. ' + wf05.question, 'all', {
    access_level: 'staff', context: { access_level: 'staff', role: 'staff' },
  })['Plan route'];
  assert.equal(p.reason, 'staff_only_request');
});
test('제출된 직원 이름으로는 직원 절차에 접근할 수 없다', () => {
  const p = plan(wf05.question, 'staff')['Plan route'];
  assert.equal(p.next, 'handoff');
  assert.equal(p.reason, 'staff_only_request');
});
for (const question of ['현장 발권 창구에서 입장하려면 어떻게 해요?', '현장 직원에게 수기 입장이 가능한지 확인해도 되나요?']) {
  test('고객의 공개 현장 안내는 유지: ' + question, () => {
    assert.notEqual(plan(question)['Plan route'].reason, 'staff_only_request');
  });
}
test('제한 절차 이관 응답에 내부 절차와 근거를 싣지 않는다', () => {
  const response = execute('Handoff answer', {}, plan(wf05.question));
  assert.equal(response.route, '담당자 이관');
  assert.deepEqual(response.sources, []);
  assert.equal(response.needs_handoff, true);
  assert.ok(!/책임자\s*코드|수기\s*모드|수기\s*입장\s*처리|스태프\s*단말/.test(response.answer));
});
test('로그 tag의 연락처도 가리고 질문·답변 원문은 저장하지 않는다', () => {
  const contact = '010-0000-9988 audit.mask@example.com';
  const context = plan(wf05.question + ' ' + contact, 'all', { tag: contact });
  const response = { route: '담당자 이관', reason: 'staff_only_request', answer: '담당자에게 전달합니다.',
    sources: [], ticket: { id: 'T-local' }, security: { blocked_by: '', masked: 0 }, timings: {}, agents: {} };
  const record = execute('Log record', response, context).log;
  assert.equal(record.tag, '010-****-9988 a***@example.com');
  assert.ok(!JSON.stringify(record).includes('010-0000-9988'));
  assert.ok(!JSON.stringify(record).includes('audit.mask@example.com'));
  assert.ok(!Object.hasOwn(record, 'question'));
  assert.ok(!Object.hasOwn(record, 'answer'));
});
