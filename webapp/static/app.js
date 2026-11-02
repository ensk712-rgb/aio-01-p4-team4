'use strict';

const MAX_QUESTION = 500;
const REFUND_CONFIRM_QUESTION = '네 취소 확정할게요';
const FAULT_TARGETS = ['tickets', 'faq', 'dlq'];
const FAULT_MODES = ['ok', 'slow', 'error', 'flaky'];
const TIMING_LABELS = { classify_ms: '분류', retrieve_ms: '검색·조회', answer_ms: '답변', handoff_ms: '이관' };
const RESET_ACTIONS = [
  ['tickets-reset', '티켓 초기화'],
  ['dlq-clear', 'DLQ 비우기'],
  ['alerts-clear', '알림 비우기'],
  ['cache-clear', '캐시 비우기'],
  ['logs-reset', '실행 기록 초기화'],
];
const FORM_CONTEXT_KEYS = ['booking_id', 'client_ip', 'previous_request_id', 'previous_question'];

const $ = id => document.getElementById(id);

const state = {
  users: [],
  presets: [],
  history: [],
  followup: null,
  pendingRefund: null,
  shown: null,
  sending: false,
};

// DOM은 h()로만 만든다. 응답 문구가 HTML로 해석되지 않게 항상 텍스트 노드로 넣는다.
function h(tag, props, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (key === 'class') node.className = value;
    else if (key === 'onclick') node.addEventListener('click', value);
    else if (key === 'width') node.style.width = value;
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child !== null && child !== undefined) node.append(child);
  }
  return node;
}

function display(value) {
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function replace(target, ...children) {
  target.replaceChildren(...children.flat().filter(Boolean));
}

function pad(number, width = 2) {
  return String(number).padStart(width, '0');
}

function generateRequestId() {
  const d = new Date();
  const stamp = `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
  return `web-${stamp}-${pad(Math.floor(Math.random() * 10000), 4)}`;
}

function kstDate(value) {
  const date = value === undefined ? new Date() : new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Date(date.getTime() + 9 * 3600000).toISOString().slice(0, 10);
}

function previousDay(day) {
  return new Date(new Date(`${day}T00:00:00Z`).getTime() - 86400000).toISOString().slice(0, 10);
}

async function api(path, options = {}) {
  const init = { method: options.method || 'GET' };
  if (init.method === 'POST') {
    init.headers = { 'Content-Type': 'application/json' };
    init.body = JSON.stringify(options.body || {});
  }
  const response = await fetch(path, init);
  let body;
  try {
    body = await response.json();
  } catch (error) {
    body = { error: '응답을 JSON으로 읽지 못했습니다' };
  }
  return { status: response.status, ok: response.ok, body };
}

/* ---------- 탭·상태 표시 ---------- */

function showTab(name) {
  for (const button of document.querySelectorAll('.tab')) {
    const active = button.dataset.tab === name;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
  }
  $('tab-support').hidden = name !== 'support';
  $('tab-ops').hidden = name !== 'ops';
  if (name === 'ops') refreshOps();
  refreshStatus();
}

async function refreshStatus() {
  const dot = (label, item) => h('span', { class: `dot${item && item.ok ? ' ok' : ''}` },
    `${label} ${item && item.ok ? '정상' : '연결 안 됨'}`);
  try {
    const { body } = await api('/api/status');
    replace($('status'),
      dot('데이터 API', body.data_api),
      dot('n8n', body.n8n),
      dot('팀 키', { ok: body.team_key_configured }));
  } catch (error) {
    replace($('status'), h('span', { class: 'dot' }, '웹앱 서버 연결 안 됨'));
  }
}

/* ---------- 요청 폼 ---------- */

function setUserSelection(name) {
  const select = $('user');
  if (name && ![...select.options].some(option => option.value === name)) {
    // WF-13 시연: 없는 사용자도 그대로 보내 서버의 400을 보여 준다.
    select.append(h('option', { value: name }, `${name} (미등록)`));
  }
  if (name) select.value = name;
  updateUserInfo();
}

function updateUserInfo() {
  const user = state.users.find(item => item.name === $('user').value);
  $('user-info').textContent = user
    ? `${user.grade} · ${user.dept} · access_level ${user.access_level}`
    : '등록되지 않은 사용자';
}

function setChannel(channel) {
  const select = $('channel');
  if (channel && ![...select.options].some(option => option.value === channel)) {
    select.append(h('option', { value: channel }, channel));
  }
  select.value = channel || 'web';
}

function updateCounter() {
  const length = $('question').value.length;
  const counter = $('counter');
  counter.textContent = `${length}/${MAX_QUESTION}`;
  counter.classList.toggle('over', length > MAX_QUESTION);
  const warn = $('question-warn');
  if (length > MAX_QUESTION) {
    warn.textContent = `${MAX_QUESTION}자를 넘었습니다. 보내면 서버가 400으로 거절합니다.`;
    warn.hidden = false;
  } else {
    warn.hidden = true;
  }
}

function applyPreset(index) {
  const preset = state.presets[Number(index)];
  if (!preset) return;
  const request = preset.request;
  clearFollowup();
  setUserSelection(request.user);
  setChannel(request.channel);
  $('question').value = request.question || '';
  $('request-id').value = request.request_id || '';
  $('attempt').value = request.attempt || 1;
  const context = { ...(request.context || {}) };
  $('booking-id').value = context.booking_id || '';
  $('client-ip').value = context.client_ip || '';
  for (const key of FORM_CONTEXT_KEYS) delete context[key];
  const hasExtra = Object.keys(context).length > 0;
  $('extra-context').value = hasExtra ? JSON.stringify(context, null, 2) : '';
  $('extra-box').open = hasExtra;
  $('form-error').hidden = true;
  updateCounter();
}

function clearFollowup() {
  state.followup = null;
  $('followup').hidden = true;
}

function resetConversation() {
  clearFollowup();
  state.pendingRefund = null;
  $('attempt').value = 1;
  $('question').value = '';
  $('request-id').value = '';
  $('booking-id').value = '';
  $('client-ip').value = '';
  $('extra-context').value = '';
  $('preset').value = '';
  updateCounter();
  rerenderCurrentResult();
}

function startFollowup(exchange) {
  state.followup = {
    previous_request_id: exchange.request.request_id,
    previous_question: exchange.request.question,
  };
  setUserSelection(exchange.request.user);
  setChannel(exchange.request.channel);
  $('attempt').value = (exchange.request.attempt || 1) + 1;
  $('question').value = '';
  $('request-id').value = '';
  $('preset').value = '';
  $('followup-text').textContent = `이어서 질문 중 · attempt ${$('attempt').value}`;
  $('followup').hidden = false;
  updateCounter();
  $('question').focus();
}

function buildContextFromForm() {
  const raw = $('extra-context').value.trim();
  let context = {};
  if (raw) {
    context = JSON.parse(raw);
    if (context === null || typeof context !== 'object' || Array.isArray(context)) {
      throw new SyntaxError('객체가 아닙니다');
    }
  }
  const booking = $('booking-id').value.trim();
  const clientIp = $('client-ip').value.trim();
  if (booking) context.booking_id = booking;
  if (clientIp) context.client_ip = clientIp;
  if (state.followup) Object.assign(context, state.followup);
  return context;
}

function submitForm(event) {
  event.preventDefault();
  const error = $('form-error');
  error.hidden = true;
  let context;
  try {
    context = buildContextFromForm();
  } catch (parseError) {
    error.textContent = '추가 context는 JSON 객체여야 합니다.';
    error.hidden = false;
    $('extra-box').open = true;
    return;
  }
  const attempt = Number($('attempt').value);
  if (!Number.isInteger(attempt) || attempt < 1) {
    error.textContent = 'attempt는 1 이상의 정수여야 합니다.';
    error.hidden = false;
    return;
  }
  const request = {
    request_id: $('request-id').value.trim() || generateRequestId(),
    user: $('user').value,
    channel: $('channel').value,
    question: $('question').value,
    attempt,
    context,
  };
  send(request);
  if (state.followup) {
    clearFollowup();
    $('attempt').value = 1;
  }
}

function confirmRefund() {
  const pending = state.pendingRefund;
  if (!pending) return;
  const context = { pending_action: 'refund_request', booking_id: pending.booking_id, confirm: true };
  if (pending.client_ip) context.client_ip = pending.client_ip;
  send({
    request_id: generateRequestId(),
    user: pending.user,
    channel: pending.channel,
    question: REFUND_CONFIRM_QUESTION,
    attempt: 1,
    context,
  });
}

async function send(request) {
  if (state.sending) return;
  state.sending = true;
  $('send').disabled = true;
  $('send').textContent = '처리 중…';
  replace($('result'), h('p', { class: 'empty' }, `${request.request_id} 처리 중…`));
  const started = performance.now();
  let exchange;
  try {
    const { status, body } = await api('/api/support', { method: 'POST', body: request });
    exchange = { request, status, body };
  } catch (error) {
    exchange = { request, status: 0, body: { error: '웹앱 서버에 연결하지 못했습니다' } };
  }
  exchange.elapsed_ms = Math.round(performance.now() - started);
  exchange.at = new Date();
  state.sending = false;
  $('send').disabled = false;
  $('send').textContent = '보내기';

  state.history.unshift(exchange);
  trackPendingRefund(exchange);
  renderResult(exchange);
  renderHistory();
}

function trackPendingRefund(exchange) {
  const pending = exchange.body && exchange.body.agents && exchange.body.agents.pending_action;
  if (exchange.status === 200 && pending && pending.type === 'refund_request' && pending.booking_id) {
    state.pendingRefund = {
      user: exchange.request.user,
      channel: exchange.request.channel,
      booking_id: pending.booking_id,
      client_ip: exchange.request.context.client_ip,
    };
    $('booking-id').value = pending.booking_id;
  } else {
    state.pendingRefund = null;
  }
}

/* ---------- 결과 ---------- */

function routeBadge(route) {
  return h('span', { class: `badge ${String(route).replace(/\s/g, '')}` }, route);
}

function keyValues(pairs) {
  return h('dl', null, pairs.flatMap(([key, value]) => [h('dt', null, key), h('dd', null, display(value))]));
}

function dataTable(columns, rows) {
  return h('div', { class: 'table-wrap' }, h('table', null,
    h('thead', null, h('tr', null, columns.map(column =>
      h('th', { class: column.num ? 'num' : '' }, column.label)))),
    h('tbody', null, rows.map(row => h('tr', null, columns.map(column =>
      h('td', { class: column.num ? 'num' : '' }, display(column.get(row)))))))));
}

function sourcesSection(sources) {
  if (!Array.isArray(sources) || !sources.length) {
    return h('div', null, h('h3', null, '근거 문서'), h('p', { class: 'empty' }, '없음'));
  }
  return h('div', null, h('h3', null, '근거 문서'), dataTable([
    { label: 'doc', get: row => row.doc },
    { label: 'section', get: row => row.section },
    { label: 'score', num: true, get: row => (typeof row.score === 'number' ? row.score.toFixed(3) : row.score) },
  ], sources));
}

function ticketCard(ticket) {
  if (!ticket) return h('div', { class: 'card' }, h('h3', null, '티켓'), h('p', { class: 'empty' }, '없음'));
  const { id, priority, duplicate, ...rest } = ticket;
  return h('div', { class: 'card' }, h('h3', null, '티켓'), keyValues([
    ['id', id],
    ['priority', priority],
    ['duplicate', duplicate === undefined ? '-' : String(duplicate)],
    ...Object.entries(rest),
  ]));
}

function agentsCard(agents) {
  const { roles, llm_calls: llmCalls, ...rest } = agents || {};
  return h('div', { class: 'card' }, h('h3', null, '에이전트'), keyValues([
    ['roles', Array.isArray(roles) && roles.length ? roles.join(' → ') : '-'],
    ['llm_calls', llmCalls],
    ...Object.entries(rest),
  ]));
}

function securityCard(security) {
  const value = security || {};
  return h('div', { class: 'card' }, h('h3', null, '보안'), keyValues([
    ['blocked_by', value.blocked_by],
    ['reason', value.reason],
    ['masked', value.masked],
  ]));
}

function timingsSection(timings) {
  const entries = Object.entries(timings || {}).filter(([key, value]) => key !== 'total_ms' && typeof value === 'number');
  const total = timings && typeof timings.total_ms === 'number'
    ? timings.total_ms
    : entries.reduce((sum, [, value]) => sum + value, 0);
  if (!entries.length && !total) return null;
  const bar = (label, value) => {
    const percent = total > 0 ? Math.max(0, Math.min(100, (value / total) * 100)) : 0;
    return h('div', { class: 'bar-row' },
      h('span', null, label),
      h('div', { class: 'bar-track' }, h('div', { class: 'bar-fill', width: `${percent}%` })),
      h('span', { class: 'num' }, `${value} ms`));
  };
  return h('div', null, h('h3', null, '소요 시간'),
    entries.map(([key, value]) => bar(TIMING_LABELS[key] || key, value)),
    bar('전체', total));
}

function rawJson(exchange) {
  return h('details', null, h('summary', null, '원문 JSON'),
    h('pre', null, JSON.stringify({ status: exchange.status, request: exchange.request, response: exchange.body }, null, 2)));
}

function resultActions(exchange, isLatest) {
  if (!isLatest) return null;
  const buttons = [];
  if (state.pendingRefund) {
    buttons.push(h('button', { type: 'button', class: 'primary', onclick: confirmRefund },
      `환불 확정 (${state.pendingRefund.booking_id})`));
  }
  if (exchange.status === 200) {
    buttons.push(h('button', { type: 'button', class: 'secondary', onclick: () => startFollowup(exchange) }, '이어서 질문'));
  }
  buttons.push(h('button', { type: 'button', class: 'secondary', onclick: resetConversation }, '새 대화'));
  return h('div', { class: 'actions' }, buttons);
}

function exchangeMeta(exchange) {
  return `${exchange.request.request_id} · ${exchange.request.user} · attempt ${exchange.request.attempt} · ${exchange.elapsed_ms} ms`;
}

function renderResult(exchange) {
  state.shown = exchange;
  const { status, body } = exchange;
  const isLatest = exchange === state.history[0];
  if (status !== 200 || !body.route) {
    replace($('result'),
      h('div', { class: 'result-head' },
        h('span', { class: 'badge' }, status ? `HTTP ${status}` : '연결 실패'),
        h('span', { class: 'meta' }, exchangeMeta(exchange))),
      h('p', { class: 'answer error-text' }, display(body.error || '결과 형식이 올바르지 않습니다')),
      Array.isArray(body.codes) && body.codes.length ? h('p', { class: 'hint' }, `codes: ${body.codes.join(', ')}`) : null,
      resultActions(exchange, isLatest),
      rawJson(exchange));
    return;
  }
  replace($('result'),
    h('div', { class: 'result-head' }, routeBadge(body.route), h('span', { class: 'meta' }, exchangeMeta(exchange))),
    h('p', { class: 'answer' }, display(body.answer)),
    body.reason ? h('p', { class: 'hint' }, `reason: ${body.reason}`) : null,
    resultActions(exchange, isLatest),
    h('div', { class: 'cards' }, ticketCard(body.ticket), agentsCard(body.agents), securityCard(body.security)),
    sourcesSection(body.sources),
    timingsSection(body.timings),
    rawJson(exchange));
}

function rerenderCurrentResult() {
  if (state.shown) renderResult(state.shown);
}

function renderHistory() {
  replace($('history'), state.history.map(exchange => {
    const { status, body, request } = exchange;
    const badge = status === 200 && body.route
      ? routeBadge(body.route)
      : h('span', { class: 'badge' }, status ? `HTTP ${status}` : '연결 실패');
    return h('div', { class: 'history-item' },
      h('div', { class: 'result-head' }, badge,
        h('span', { class: 'meta' }, `${exchange.at.toLocaleTimeString('ko-KR')} · ${exchangeMeta(exchange)}`),
        h('button', { type: 'button', class: 'link', onclick: () => renderResult(exchange) }, '결과 보기')),
      h('p', { class: 'history-question' }, display(request.question)),
      h('p', { class: 'history-answer' }, display(body.answer || body.error)));
  }));
}

/* ---------- 운영 ---------- */

function errorNotice(result) {
  return h('p', { class: 'error-text' }, `불러오지 못했습니다 (HTTP ${result.status}): ${display(result.body.error)}`);
}

function period() {
  const today = kstDate();
  const from = $('from').value || today;
  const to = $('to').value || today;
  return { from, to };
}

async function loadSection(targetId, path, render) {
  const target = $(targetId);
  try {
    const result = await api(path);
    replace(target, result.ok ? render(result.body) : errorNotice(result));
  } catch (error) {
    replace(target, h('p', { class: 'error-text' }, '웹앱 서버에 연결하지 못했습니다'));
  }
}

function unionColumns(rows) {
  const keys = [];
  for (const row of rows) {
    for (const key of Object.keys(row)) if (!keys.includes(key)) keys.push(key);
  }
  return keys.map(key => ({
    label: key,
    get: row => (key === 'at' && typeof row[key] === 'number'
      ? new Date(row[key] * 1000).toLocaleString('ko-KR')
      : row[key]),
  }));
}

function genericRows(rows, summary) {
  return [
    h('p', { class: 'section-note' }, summary),
    rows.length ? dataTable(unionColumns(rows), rows) : h('p', { class: 'empty' }, '없음'),
  ];
}

function renderTickets(body) {
  return genericRows(body.tickets || [], `총 ${body.count ?? 0}건`);
}

function renderAlerts(body) {
  return genericRows([...(body.alerts || [])].reverse(), `총 ${body.count ?? 0}건`);
}

function renderDlq(body) {
  return genericRows(body.items || [], `총 ${body.size ?? 0}건 · parked ${body.parked ?? 0}건`);
}

function renderLogs(body, range) {
  // 기록의 started_at은 UTC라 하루 넓게 읽은 뒤 한국 날짜로 거른다(지표 워크플로우와 같은 기준).
  const rows = (body.logs || [])
    .filter(row => {
      const day = kstDate(row.started_at);
      return day >= range.from && day <= range.to;
    })
    .sort((a, b) => String(b.started_at).localeCompare(String(a.started_at)));
  const counts = {};
  for (const row of rows) counts[row.route] = (counts[row.route] || 0) + 1;
  if (!rows.length) return h('p', { class: 'empty' }, '기간 안의 기록이 없습니다.');
  return [
    h('div', { class: 'chips' }, Object.entries(counts).map(([route, count]) =>
      h('span', { class: `badge ${String(route).replace(/\s/g, '')}` }, `${route} ${count}`))),
    dataTable([
      { label: '시각', get: row => (row.started_at ? new Date(row.started_at).toLocaleString('ko-KR') : '') },
      { label: 'request_id', get: row => row.request_id },
      { label: 'channel', get: row => row.channel },
      { label: 'attempt', num: true, get: row => row.attempt },
      { label: 'route', get: row => row.route },
      { label: 'ticket', get: row => row.ticket },
      { label: 'blocked_by', get: row => row.blocked_by },
      { label: 'masked', num: true, get: row => row.masked },
      { label: 'llm', num: true, get: row => row.llm_calls },
      { label: '전체 ms', num: true, get: row => row.timings && row.timings.total_ms },
      { label: 'reason', get: row => row.reason },
    ], rows),
  ];
}

function renderMetrics(body) {
  const rate = typeof body.handoff_rate === 'number' ? `${Math.round(body.handoff_rate * 100)}%` : body.handoff_rate;
  const nodes = [
    body.answer ? h('p', { class: 'section-note' }, body.answer) : null,
    dataTable([
      { label: '기간', get: row => row.period },
      { label: '전체', num: true, get: row => row.total },
      { label: '이관 비율', num: true, get: row => row.rate },
      { label: '현재 DLQ', num: true, get: row => row.dlq },
      { label: '현재 티켓', num: true, get: row => row.tickets },
      { label: '읽기 실패', get: row => row.partial },
    ], [{
      period: body.period ? `${body.period.from} ~ ${body.period.to}` : '',
      total: body.total,
      rate,
      dlq: body.dlq_size_now,
      tickets: body.tickets_created_now,
      partial: Array.isArray(body.partial) ? body.partial.join(', ') : body.partial,
    }]),
  ];
  const routes = Object.entries(body.by_route || {});
  if (routes.length) {
    nodes.push(h('h3', null, 'route별 건수'), dataTable([
      { label: 'route', get: row => row[0] },
      { label: '건수', num: true, get: row => row[1] },
    ], routes));
  }
  const steps = Object.entries(body.steps || {});
  if (steps.length) {
    nodes.push(h('h3', null, '구간별 소요 시간 (ms)'), dataTable([
      { label: '구간', get: row => TIMING_LABELS[row[0]] || row[0] },
      { label: 'p50', num: true, get: row => row[1].p50 },
      { label: 'p95', num: true, get: row => row[1].p95 },
      { label: '건수', num: true, get: row => row[1].n },
    ], steps));
  }
  return nodes;
}

async function loadMetrics() {
  const target = $('ops-metrics');
  try {
    const result = await api('/api/ops', { method: 'POST', body: period() });
    replace(target, result.ok ? renderMetrics(result.body) : errorNotice(result));
  } catch (error) {
    replace(target, h('p', { class: 'error-text' }, '웹앱 서버에 연결하지 못했습니다'));
  }
}

async function loadFault() {
  const message = $('fault-message');
  try {
    const { ok, status, body } = await api('/api/data/admin/fault');
    if (!ok) {
      message.textContent = `현재 값을 읽지 못했습니다 (HTTP ${status}): ${display(body.error)}`;
      return;
    }
    for (const target of FAULT_TARGETS) $(`fault-${target}`).value = body[target] || 'ok';
    $('slow-seconds').value = body.slow_seconds ?? '';
    const active = FAULT_TARGETS.filter(target => body[target] && body[target] !== 'ok');
    message.textContent = active.length ? `장애 주입 중: ${active.join(', ')}` : '';
  } catch (error) {
    message.textContent = '웹앱 서버에 연결하지 못했습니다';
  }
}

async function saveFault(event) {
  event.preventDefault();
  const payload = {};
  for (const target of FAULT_TARGETS) payload[target] = $(`fault-${target}`).value;
  const seconds = $('slow-seconds').value;
  if (seconds !== '') payload.slow_seconds = Number(seconds);
  const message = $('fault-message');
  try {
    const { ok, status, body } = await api('/api/data/admin/fault', { method: 'POST', body: payload });
    if (!ok) {
      message.textContent = `저장 실패 (HTTP ${status}): ${display(body.error)}`;
      return;
    }
    await loadFault();
    if (!message.textContent) message.textContent = '저장했습니다. 모든 대상이 정상입니다.';
  } catch (error) {
    message.textContent = '웹앱 서버에 연결하지 못했습니다';
  }
}

async function runReset(path, label) {
  if (!window.confirm(`${label}를 실행할까요? 되돌릴 수 없습니다.`)) return;
  const message = $('reset-message');
  try {
    const { ok, status, body } = await api(`/api/data/${path}`, { method: 'POST', body: {} });
    message.textContent = ok
      ? `${label} 완료: ${display(body.cleared)}건`
      : `${label} 실패 (HTTP ${status}): ${display(body.error)}`;
  } catch (error) {
    message.textContent = '웹앱 서버에 연결하지 못했습니다';
  }
  refreshOps();
}

function refreshOps() {
  const range = period();
  const query = new URLSearchParams({ source: 'live', from: previousDay(range.from), to: range.to });
  loadMetrics();
  loadSection('ops-logs', `/api/data/logs?${query}`, body => renderLogs(body, range));
  loadSection('ops-tickets', '/api/data/tickets-created', renderTickets);
  loadSection('ops-alerts', '/api/data/alerts', renderAlerts);
  loadSection('ops-dlq', '/api/data/dlq', renderDlq);
  loadFault();
}

/* ---------- 시작 ---------- */

function buildOpsControls() {
  const today = kstDate();
  $('from').value = today;
  $('to').value = today;
  replace($('fault-fields'), FAULT_TARGETS.map(target => h('div', null,
    h('label', { for: `fault-${target}` }, target),
    h('select', { id: `fault-${target}` }, FAULT_MODES.map(mode => h('option', { value: mode }, mode))))));
  replace($('reset-buttons'), RESET_ACTIONS.map(([path, label]) =>
    h('button', { type: 'button', class: 'secondary', onclick: () => runReset(path, label) }, label)));
}

async function loadInitialData() {
  try {
    const users = await api('/api/users');
    state.users = Array.isArray(users.body) ? users.body : [];
    replace($('user'), state.users.map(user => h('option', { value: user.name }, `${user.name} (${user.grade})`)));
    updateUserInfo();

    const presets = await api('/api/presets');
    state.presets = Array.isArray(presets.body) ? presets.body : [];
    const groups = new Map();
    state.presets.forEach((preset, index) => {
      if (!groups.has(preset.group)) groups.set(preset.group, []);
      groups.get(preset.group).push(h('option', { value: String(index) }, preset.name));
    });
    $('preset').append(...[...groups].map(([group, options]) => h('optgroup', { label: group }, options)));
  } catch (error) {
    $('user-info').textContent = '사용자·프리셋을 불러오지 못했습니다';
  }
}

function init() {
  for (const button of document.querySelectorAll('.tab')) {
    button.addEventListener('click', () => showTab(button.dataset.tab));
  }
  $('form').addEventListener('submit', submitForm);
  $('question').addEventListener('input', updateCounter);
  $('user').addEventListener('change', updateUserInfo);
  $('preset').addEventListener('change', event => applyPreset(event.target.value));
  $('new-conversation').addEventListener('click', resetConversation);
  $('ops-refresh').addEventListener('click', refreshOps);
  $('fault-form').addEventListener('submit', saveFault);
  $('from').addEventListener('change', refreshOps);
  $('to').addEventListener('change', refreshOps);
  buildOpsControls();
  loadInitialData();
  refreshStatus();
}

init();
