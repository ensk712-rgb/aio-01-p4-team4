// node --test webapp/test/
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { classify, REASONS } = require('../static/reasons.js');

const ok = (route, reason, extra = {}) => classify(200, { route, reason, agents: { used: [] }, ...extra });

test('설계대로 처리한 건은 정상', () => {
  assert.strictEqual(ok('자동 답변', '').kind, 'normal');
  assert.strictEqual(ok('담당자 이관', 'urgent_entry').kind, 'normal');
  assert.strictEqual(ok('차단', 'injection_pattern').kind, 'normal');
  assert.strictEqual(ok('담당자 이관', 'payment_error_handoff').kind, 'normal');
});

test('장애·품질 이관을 단계와 함께 나눈다', () => {
  assert.deepStrictEqual([ok('담당자 이관', 'agents_failed').kind, ok('담당자 이관', 'agents_failed').stage], ['fault', '분류']);
  assert.deepStrictEqual([ok('담당자 이관', 'verification_failed').kind, ok('담당자 이관', 'verification_failed').stage], ['quality', '검증']);
  assert.strictEqual(ok('담당자 이관', 'payment_failed').kind, 'fault');
});

test('티켓을 못 만든 이관은 reason보다 티켓 장애가 우선', () => {
  const c = ok('담당자 이관', 'writer_not_grounded', { ticket: null, agents: { handoff: { dlq: true, alert: true } } });
  assert.deepStrictEqual([c.kind, c.stage, c.reason], ['fault', '티켓', 'ticket_failed']);
});

test('모르는 reason은 미분류, 실패처럼 보이면 장애', () => {
  assert.strictEqual(ok('담당자 이관', 'brand_new_reason').kind, 'unknown');
  assert.strictEqual(ok('담당자 이관', 'search_failed').kind, 'fault');
});

test('HTTP 오류·400', () => {
  assert.strictEqual(classify(502, { error: 'n8n 연결 실패' }).kind, 'error');
  assert.strictEqual(classify(400, { error: 'invalid request', codes: [] }).kind, 'normal');
});

test('워크플로우 코드에 있는 reason은 모두 분류표에 있다', () => {
  const dir = path.join(__dirname, '..', '..', 'workflows');
  const found = new Set();
  for (const f of fs.readdirSync(dir).filter((x) => x.endsWith('.json'))) {
    const text = fs.readFileSync(path.join(dir, f), 'utf8');
    for (const m of text.matchAll(/reason\\?["']?\s*[:=]\s*\\?["']([a-z][a-z_0-9]+)/g)) found.add(m[1]);
  }
  // 응답 reason이 아니라 내부 알림·로그용인 값
  const internal = new Set(['urgent_handoff', 'refund_requote']);
  const missing = [...found].filter((r) => !REASONS[r] && !internal.has(r));
  assert.deepStrictEqual(missing, []);
});
