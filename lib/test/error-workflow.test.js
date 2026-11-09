const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const common = require('../common');

const fixture = () => ({
  workflow: { id: 'support_01', name: 'ticketmoa-support (본체)' },
  execution: {
    id: '123456',
    lastNodeExecuted: 'Call tech',
    error: {
      name: 'NodeApiError',
      message: 'Bearer secret-token user=김하늘 phone=010-0000-5678 question=환불 요청',
      stack: 'private stack',
    },
    data: { request: { body: { question: 'private question', user: '김하늘' } } },
  },
});

test('Error Trigger is connected to the allow-list normalizer and independent alert paths', () => {
  const workflow = JSON.parse(fs.readFileSync(path.join(__dirname, '../../workflows/ticketmoa-errors.json'), 'utf8'));
  const support = JSON.parse(fs.readFileSync(path.join(__dirname, '../../workflows/ticketmoa-support.json'), 'utf8'));
  const handoff = JSON.parse(fs.readFileSync(path.join(__dirname, '../../workflows/ticketmoa-handoff.json'), 'utf8'));
  const names = new Set(workflow.nodes.map(node => node.name));
  assert.ok(workflow.nodes.some(node => node.type === 'n8n-nodes-base.errorTrigger'));
  assert.equal(workflow.settings.errorWorkflow, undefined, 'error workflow must not recursively handle itself');
  assert.equal(support.settings.errorWorkflow, workflow.id);
  assert.equal(handoff.settings.errorWorkflow, workflow.id);
  assert.ok(names.has('오류 정보 정규화'));
  assert.ok(names.has('중복 키 있음?'));
  assert.ok(names.has('중복 알림?'));
  assert.ok(names.has('중복 알림 기록'));
  assert.ok(names.has('중복 판정'));
  assert.ok(names.has('장애 알림 전송'));
  assert.ok(names.has('디스코드 알림'));
  assert.deepEqual(
    workflow.connections['오류 수신'].main[0].map(edge => edge.node),
    ['오류 정보 정규화'],
  );
  assert.ok(workflow.connections['오류 정보 정규화']);
  assert.ok(workflow.connections['중복 키 있음?']);
  assert.ok(workflow.connections['중복 알림?']);
  assert.ok(workflow.connections['중복 알림 기록']);
  assert.ok(workflow.connections['중복 판정']);
  assert.deepEqual(workflow.connections['중복 알림?'].main[0], []);
  assert.equal(workflow.connections['중복 알림?'].main[1][0].node, '중복 알림 기록');
  const independentAlerts = new Set(['장애 알림 전송', '디스코드 알림']);
  assert.deepEqual(new Set(workflow.connections['중복 키 있음?'].main[1].map(edge => edge.node)), independentAlerts);
  assert.deepEqual(new Set(workflow.connections['중복 이력 조회'].main[1].map(edge => edge.node)), independentAlerts);
  for (const output of workflow.connections['중복 알림 기록'].main) {
    assert.deepEqual(new Set(output.map(edge => edge.node)), independentAlerts);
  }
  assert.equal(workflow.nodes.find(node => node.name === '장애 알림 전송').onError, 'continueErrorOutput');
  assert.equal(workflow.nodes.find(node => node.name === '디스코드 알림').onError, 'continueRegularOutput');
  assert.match(workflow.nodes.find(node => node.name === '장애 알림 전송').parameters.jsonBody, /오류 정보 정규화/);
  assert.match(workflow.nodes.find(node => node.name === '디스코드 알림').parameters.content, /오류 정보 정규화/);
  assert.match(workflow.nodes.find(node => node.name === '디스코드 알림').parameters.content, /error_type/);
});

test('normalizer returns bounded metadata and excludes raw error/request content', () => {
  const normalized = common.normalizeErrorEvent(fixture(), new Date('2026-11-06T00:00:00.000Z'));
  assert.deepEqual(normalized, {
    at: '2026-11-06T00:00:00.000Z',
    workflow_id: 'support_01',
    workflow: 'ticketmoa-support',
    execution_id: '123456',
    error_type: 'NodeApiError',
    failed_node: 'Call tech',
    severity: 'critical',
    reason: 'unexpected_execution_error',
    dedupe_key: 'error-alert:support_01:123456',
  });
  assert.doesNotMatch(JSON.stringify(normalized), /secret-token|김하늘|010-0000-5678|환불 요청|private stack/);
});

test('Error Trigger Code node uses the tested common normalizer', () => {
  const workflow = JSON.parse(fs.readFileSync(path.join(__dirname, '../../workflows/ticketmoa-errors.json'), 'utf8'));
  const code = workflow.nodes.find(node => node.name === '오류 정보 정규화').parameters.jsCode;
  const FixedDate = class extends Date { constructor() { super('2026-11-06T00:00:00.000Z'); } };
  const actual = new Function('$json', 'Date', code)(fixture(), FixedDate)[0].json;
  const expected = common.normalizeErrorEvent(fixture(), new Date('2026-11-06T00:00:00.000Z'));
  assert.deepEqual(actual, expected);
});

test('normalizer rejects unsafe identifiers, labels, and unrecognized error types', () => {
  const event = fixture();
  event.workflow.id = 'user@example.com';
  event.workflow.name = 'private-user-name';
  event.execution.id = 'execution-secret';
  event.execution.lastNodeExecuted = '010-0000-5678';
  event.execution.error.name = 'CustomError';
  const normalized = common.normalizeErrorEvent(event, new Date('2026-11-06T00:00:00Z'));
  assert.equal(normalized.workflow_id, 'unknown');
  assert.equal(normalized.workflow, 'ticketmoa-unknown');
  assert.equal(normalized.execution_id, '');
  assert.equal(normalized.error_type, 'unknown_error');
  assert.equal(normalized.failed_node, 'unknown');
  assert.equal(normalized.dedupe_key, '');
});

test('duplicate cache entry suppresses notification while missing or failed cache allows it', () => {
  const key = 'error-alert:w1:42';
  assert.equal(common.shouldSendErrorAlert({ statusCode: 200, body: { value: { dedupe_key: key, sent: true } } }, key), false);
  assert.equal(common.shouldSendErrorAlert({ statusCode: 200, body: { value: { dedupe_key: 'other', sent: true } } }, key), true);
  assert.equal(common.shouldSendErrorAlert({ statusCode: 404, body: {} }, key), true);
  assert.equal(common.shouldSendErrorAlert({ error: 'cache unavailable' }, key), true);
  assert.equal(common.shouldSendErrorAlert({}, ''), true);
});

test('Error Workflow Code node uses the tested duplicate decision', () => {
  const workflow = JSON.parse(fs.readFileSync(path.join(__dirname, '../../workflows/ticketmoa-errors.json'), 'utf8'));
  const code = workflow.nodes.find(node => node.name === '중복 판정').parameters.jsCode;
  const key = 'error-alert:w1:42';
  const $ = name => ({ first: () => ({ json: { dedupe_key: key } }) });
  const duplicate = new Function('$json', '$', code)({ statusCode: 200, body: { value: { dedupe_key: key, sent: true } } }, $)[0].json;
  const firstDelivery = new Function('$json', '$', code)({ statusCode: 404 }, $)[0].json;
  assert.deepEqual(duplicate, { duplicate: true });
  assert.deepEqual(firstDelivery, { duplicate: false });
});
