// 티켓모아 관리자 화면: 웹앱을 지나간 대화(/api/admin/chats)와 데이터 API 운영 기록(/api/admin/ops/*)을 보여 준다.
// 대화는 1.5초, 운영 기록은 5초마다 새로 읽는다. 장애/품질/정상 분류는 reasons.js 한 곳에서 한다.
(() => {
  const { NODES, buildPath } = window.TicketmoaFlow;
  const { classify, KIND_LABEL } = window.TicketmoaReasons;
  const $ = (id) => document.getElementById(id);
  const RECENT_MS = 30 * 60 * 1000;
  const STAGE_ORDER = ['분류', '검색', '조회', '환불', '작성', '검증', 'LLM', '티켓', '워크플로우', '연결', '?'];
  const STEP_MS = [['agents', '분류'], ['search', '검색'], ['payment', '조회'], ['refund', '환불'], ['tech', '작성·검증'], ['handoff', '이관']];
  const ROUTE_CLASS = { '자동 답변': 'auto', '보완 질문': 'clarify', '담당자 이관': 'handoff', '권한 없음': 'forbid', '차단': 'block' };
  const FILTERS = [
    ['all', '전체'], ['fault', '장애'], ['quality', '품질'], ['handoff', '이관'],
    ['refund', '환불'], ['block', '차단'], ['urgent', '긴급'],
  ];
  const OPS_TABS = [['tickets', '티켓'], ['alerts', '알림'], ['dlq', 'DLQ'], ['logs', '실행 기록'], ['fault', '장애 스위치']];

  const state = { items: [], seq: 0, selected: null, filter: 'all', opsTab: 'tickets', ops: {}, target: '' };

  // ── 도우미 ─────────────────────────
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  const time = (iso) => (iso ? new Date(iso).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '-');
  const secs = (ms) => (typeof ms === 'number' ? (ms < 1000 ? ms + 'ms' : (ms / 1000).toFixed(1) + 's') : '-');
  async function getJSON(url) {
    const res = await fetch(url, { cache: 'no-store' });
    return res.json();
  }

  // 대화 한 건에서 화면에 필요한 값을 뽑는다.
  function view(item) {
    const body = item.body && typeof item.body === 'object' ? item.body : {};
    const agents = body.agents || {};
    const used = agents.used || [];
    const cls = classify(item.status, body);
    const urgent = (body.ticket && body.ticket.priority === 'high') || body.reason === 'urgent_entry';
    const refund = used.includes('ticketmoa-refund') || /^refund_/.test(body.reason || '');
    const blocked = body.route === '차단';
    const icon = cls.kind === 'error' ? '⛔' : urgent ? '🚨' : blocked ? '🛡' : cls.kind === 'fault' ? '⚠️'
      : cls.kind === 'quality' ? '🔍' : refund ? '💸' : body.route === '자동 답변' ? '✅'
      : body.route === '보완 질문' ? '💬' : body.route === '권한 없음' ? '🙅' : '📨';
    const total = (body.timings && body.timings.total_ms) || item.elapsed_ms;
    return { item, body, agents, cls, urgent, refund, blocked, icon, total, at: Date.parse(item.at) || 0 };
  }

  function matches(v, f) {
    if (f === 'all') return true;
    if (f === 'fault') return v.cls.kind === 'fault' || v.cls.kind === 'error';
    if (f === 'quality') return v.cls.kind === 'quality';
    if (f === 'handoff') return v.body.route === '담당자 이관';
    if (f === 'refund') return v.refund;
    if (f === 'block') return v.blocked;
    if (f === 'urgent') return v.urgent;
    return true;
  }

  // ── 지표 · 장애 패널 ────────────────
  function drawMetrics(views) {
    const box = $('metrics');
    box.textContent = '';
    const n = views.length;
    const count = (fn) => views.filter(fn).length;
    const auto = count((v) => v.body.route === '자동 답변');
    const totals = views.map((v) => v.total).filter((x) => typeof x === 'number');
    const llm = views.reduce((s, v) => s + (v.agents.llm_calls || 0), 0);
    const cards = [
      ['문의', n, ''],
      ['자동 답변', n ? Math.round((100 * auto) / n) + '%' : '-', 'auto'],
      ['설계대로 이관', count((v) => v.body.route === '담당자 이관' && v.cls.kind === 'normal'), 'handoff'],
      ['장애로 이관', count((v) => v.cls.kind === 'fault' || v.cls.kind === 'error'), 'fault'],
      ['품질 이관', count((v) => v.cls.kind === 'quality'), 'quality'],
      ['차단', count((v) => v.blocked), 'block'],
      ['평균 처리', totals.length ? secs(Math.round(totals.reduce((a, b) => a + b, 0) / totals.length)) : '-', ''],
      ['LLM 호출', llm, ''],
    ];
    for (const [label, value, cls] of cards) {
      const c = el('div', 'metric ' + cls);
      c.append(el('span', 'm-label', label), el('b', 'm-value', String(value)));
      box.append(c);
    }
  }

  function drawFaults(views) {
    const recent = views.filter((v) => Date.now() - v.at < RECENT_MS);
    const stages = new Map();
    for (const v of recent) {
      if (!['fault', 'quality', 'error'].includes(v.cls.kind)) continue;
      const key = v.cls.stage || '?';
      const s = stages.get(key) || { fault: 0, quality: 0, reasons: new Map() };
      s[v.cls.kind === 'quality' ? 'quality' : 'fault'] += 1;
      s.reasons.set(v.cls.label, (s.reasons.get(v.cls.label) || 0) + 1);
      stages.set(key, s);
    }
    // errors 워크플로우 알림(예상 못 한 오류)은 대화에 안 남으므로 /alerts에서 센다.
    const alerts = (state.ops.alerts && state.ops.alerts.alerts) || [];
    const unexpected = alerts.filter((a) => a.reason === 'unexpected' && Date.now() - (a.at || 0) * 1000 < RECENT_MS).length;
    if (unexpected) {
      const s = stages.get('워크플로우') || { fault: 0, quality: 0, reasons: new Map() };
      s.fault += unexpected;
      s.reasons.set('예상 못 한 오류 (errors 워크플로우)', unexpected);
      stages.set('워크플로우', s);
    }

    const box = $('fault-stages');
    box.textContent = '';
    const keys = STAGE_ORDER.filter((k) => stages.has(k)).concat([...stages.keys()].filter((k) => !STAGE_ORDER.includes(k)));
    if (!keys.length) box.append(el('span', 'ok-note', '✓ 최근 30분 장애 없음'));
    for (const k of keys) {
      const s = stages.get(k);
      const chip = el('button', 'fstage ' + (s.fault ? 'fault' : 'quality'));
      chip.type = 'button';
      chip.append(el('b', '', k), el('span', 'n', String(s.fault + s.quality)));
      chip.title = [...s.reasons].map(([r, c]) => `${r} ${c}건`).join('\n');
      const why = el('small', '', [...s.reasons.keys()].slice(0, 2).join(', '));
      chip.append(why);
      chip.onclick = () => setFilter(s.fault ? 'fault' : 'quality');
      box.append(chip);
    }

    // 단계별 평균·최대 시간 (최근 30분)
    const slow = $('fault-slow');
    slow.textContent = '';
    const rows = [];
    for (const [key, label] of STEP_MS) {
      const xs = recent.map((v) => v.body.timings && v.body.timings[key + '_ms']).filter((x) => typeof x === 'number' && x > 0);
      if (xs.length) rows.push({ label, avg: xs.reduce((a, b) => a + b, 0) / xs.length, max: Math.max(...xs) });
    }
    rows.sort((a, b) => b.avg - a.avg);
    if (rows.length) {
      slow.append(el('span', 'muted', '느린 단계 '));
      for (const r of rows.slice(0, 3)) {
        slow.append(el('span', 'slow-chip' + (r.avg > 3000 ? ' hot' : ''), `${r.label} 평균 ${secs(Math.round(r.avg))} · 최대 ${secs(r.max)}`));
      }
    }
  }

  // ── 대화 목록 · 상세 ────────────────
  function setFilter(f) {
    state.filter = f;
    drawFilters();
    drawList();
  }

  function drawFilters() {
    const nav = $('filters');
    nav.textContent = '';
    const views = state.items.map(view);
    for (const [id, label] of FILTERS) {
      const b = el('button', id === state.filter ? 'on' : '', `${label} ${views.filter((v) => matches(v, id)).length}`);
      b.type = 'button';
      b.onclick = () => setFilter(id);
      nav.append(b);
    }
  }

  function drawList(fresh = new Set()) {
    const list = $('chat-list');
    list.textContent = '';
    const views = state.items.map(view).filter((v) => matches(v, state.filter));
    // 최신순, 단 최근 30분 긴급 건은 맨 위
    views.sort((a, b) => {
      const ua = a.urgent && Date.now() - a.at < RECENT_MS;
      const ub = b.urgent && Date.now() - b.at < RECENT_MS;
      return ua !== ub ? (ua ? -1 : 1) : b.item.seq - a.item.seq;
    });
    if (!views.length) list.append(el('li', 'empty', state.items.length ? '이 조건의 대화가 없습니다' : '아직 대화가 없습니다. 고객 화면에서 문의를 보내 보세요.'));
    for (const v of views) {
      const li = el('li', 'chat-item kind-' + v.cls.kind + (v.urgent ? ' urgent' : '') + (fresh.has(v.item.seq) ? ' fresh' : '')
        + (state.selected === v.item.seq ? ' sel' : ''));
      const top = el('div', 'ci-top');
      top.append(el('span', 'ci-icon', v.icon), el('b', '', v.item.request.user || '?'),
        el('span', 'chip route ' + (ROUTE_CLASS[v.body.route] || ''), v.body.route || (v.item.status === 400 ? '입력 거절' : '오류')),
        el('span', 'ci-time', time(v.item.at)));
      const q = el('div', 'ci-q', v.item.request.question || '');
      const meta = el('div', 'ci-meta');
      if (v.cls.kind !== 'normal' || v.cls.reason) meta.append(el('span', 'kind ' + v.cls.kind, `${KIND_LABEL[v.cls.kind]} · ${v.cls.label}`));
      if (v.body.ticket && v.body.ticket.id) meta.append(el('span', 'tk', '🎫 ' + v.body.ticket.id));
      meta.append(el('span', 'ms', secs(v.total)));
      li.append(top, q, meta);
      li.onclick = () => { state.selected = v.item.seq; drawList(); drawDetail(v); };
      list.append(li);
    }
  }

  function drawDetail(v) {
    const box = $('detail');
    box.textContent = '';
    const b = v.body;
    const head = el('div', 'd-head');
    head.append(el('span', 'ci-icon', v.icon), el('b', '', v.item.request.user || '?'),
      el('span', 'chip route ' + (ROUTE_CLASS[b.route] || ''), b.route || '오류'),
      el('span', 'kind ' + v.cls.kind, `${KIND_LABEL[v.cls.kind]}${v.cls.stage ? ' · ' + v.cls.stage : ''} · ${v.cls.label}`),
      el('span', 'muted', `${time(v.item.at)} · ${v.item.request.request_id} · 시도 ${v.item.request.attempt}`));
    box.append(head);

    const talk = el('div', 'd-talk');
    talk.append(el('div', 'd-q', v.item.request.question || ''));
    talk.append(el('div', 'd-a', b.answer || (b.error ? '오류: ' + b.error : '(답변 없음)')));
    box.append(talk);

    // 경로: flow.js가 응답에서 만든 단계별 상태
    const path = buildPath(v.item.status, b);
    const steps = el('ol', 'd-steps');
    for (const n of NODES) {
      const s = path.states[n.id];
      if (s.state === 'skip') continue;
      const li = el('li', 'step ' + s.state);
      li.append(el('b', '', n.label), el('span', 'note', s.note), el('span', 'ms', typeof s.ms === 'number' ? secs(s.ms) : ''));
      steps.append(li);
    }
    box.append(steps);

    const facts = el('div', 'd-facts');
    const fact = (k, val) => { if (val == null || val === '') return; const d = el('div', 'fact'); d.append(el('span', '', k), el('b', '', String(val))); facts.append(d); };
    const tk = b.ticket || null;
    fact('티켓', tk && tk.id ? `${tk.id} · ${tk.category || ''} · ${tk.priority === 'high' ? '긴급' : '보통'}${tk.duplicate ? ' · 중복' : ''}` : (b.route === '담당자 이관' ? '없음' : ''));
    const h = v.agents.handoff;
    if (h) fact('이관 처리', `DLQ ${h.dlq ? '저장' : '-'} · 알림 ${h.alert ? '보냄' : '-'}${h.error ? ' · 오류 ' + h.error : ''}`);
    if (v.agents.alert) fact('현장 알림', '보냄');
    fact('분류', (v.agents.intents || []).join(', ') + (typeof v.agents.confidence === 'number' ? ` (확신 ${v.agents.confidence})` : ''));
    fact('근거 문서', [...new Set((b.sources || []).map((s) => s.doc))].join(', '));
    fact('LLM', v.agents.llm_calls != null ? v.agents.llm_calls + '회' : '');
    fact('보안', b.security && b.security.blocked_by ? `${b.security.blocked_by} · ${b.security.reason}` : '');
    fact('연락처 가림', b.security && b.security.masked ? b.security.masked + '개' : '');
    fact('처리 시간', `${secs(v.total)} (웹앱까지 ${secs(v.item.elapsed_ms)})`);
    box.append(facts);

    const raw = el('details', 'd-raw');
    raw.append(el('summary', '', '응답 원문'), el('pre', '', JSON.stringify(b, null, 2)));
    box.append(raw);
  }

  // ── 운영 데이터 탭 ──────────────────
  function drawOpsTabs() {
    const nav = $('ops-tabs');
    nav.textContent = '';
    for (const [id, label] of OPS_TABS) {
      const d = state.ops[id];
      let n = '';
      if (d && !d.error) n = id === 'tickets' ? d.count : id === 'alerts' ? d.count : id === 'dlq' ? d.size : '';
      const b = el('button', id === state.opsTab ? 'on' : '', label + (n !== '' && n != null ? ' ' + n : ''));
      b.type = 'button';
      b.onclick = () => { state.opsTab = id; drawOpsTabs(); drawOps(); };
      nav.append(b);
    }
  }

  function table(headers, rows) {
    const t = el('table', 'ops-table');
    const tr = el('tr');
    headers.forEach((x) => tr.append(el('th', '', x)));
    t.append(tr);
    for (const r of rows) {
      const row = el('tr', r.cls || '');
      r.cells.forEach((c) => row.append(el('td', '', c == null ? '' : String(c))));
      if (r.request_id) {
        const hit = state.items.find((i) => i.request.request_id === r.request_id);
        if (hit) { row.classList.add('link'); row.onclick = () => { state.selected = hit.seq; drawList(); drawDetail(view(hit)); }; }
      }
      t.append(row);
    }
    return t;
  }

  const epoch = (s) => (typeof s === 'number' ? new Date(s * 1000).toLocaleTimeString('ko-KR') : s || '');

  function drawOps() {
    const box = $('ops-body');
    box.textContent = '';
    const d = state.ops[state.opsTab];
    if (!d) { box.append(el('p', 'muted', '불러오는 중…')); return; }
    if (d.error) {
      box.append(el('p', 'muted', d.error + (state.target === 'vm' ? ' — VM 데이터 API는 밖에서 열려 있지 않아 ticketmoa-ops 웹훅이 있어야 읽을 수 있습니다.' : '')));
      return;
    }
    if (state.opsTab === 'tickets') {
      const rows = (d.tickets || []).slice().reverse().map((t) => ({
        request_id: t.key, cls: t.priority === 'high' ? 'hot' : '',
        cells: [t.ticket_id, t.priority === 'high' ? '긴급' : '보통', t.category, t.requester, t.key, String(t.title || '').slice(0, 90)],
      }));
      box.append(table(['티켓', '우선순위', '분류', '고객', '요청 ID', '내용'], rows));
    } else if (state.opsTab === 'alerts') {
      const rows = (d.alerts || []).slice().reverse().map((a) => ({
        request_id: a.request_id, cls: a.severity === 'critical' ? 'hot' : '',
        cells: [epoch(a.at), a.severity, a.reason, a.workflow, a.node, a.channel || '', a.ticket_id || '', a.request_id || a.execution_id || ''],
      }));
      box.append(table(['시각', '심각도', '사유', '워크플로우', '노드', '채널', '티켓', '요청 / 실행'], rows));
    } else if (state.opsTab === 'dlq') {
      const rows = (d.items || []).slice().reverse().map((x) => ({
        request_id: x.item && x.item.id, cls: x.parked ? 'hot' : '',
        cells: [x.dlq_id, x.attempts, x.parked ? '보류' : '대기', x.item && x.item.requester, x.item && x.item.id, String((x.item && x.item.title) || '').slice(0, 90)],
      }));
      box.append(table(['DLQ', '시도', '상태', '고객', '요청 ID', '내용'], rows));
    } else if (state.opsTab === 'logs') {
      const logs = (d.logs || []).filter((l) => String(l.workflow || '').startsWith('ticketmoa'));
      const byRoute = {};
      logs.forEach((l) => { byRoute[l.route || l.status] = (byRoute[l.route || l.status] || 0) + 1; });
      box.append(el('p', 'muted', logs.length ? '티켓모아 실행 ' + logs.length + '건 · ' + Object.entries(byRoute).map(([k, v]) => `${k} ${v}`).join(' · ')
        : '티켓모아 워크플로우가 남긴 /logs 기록이 없습니다 (과정 견본 기록만 있음).'));
      const rows = logs.slice(-30).reverse().map((l) => ({ cls: l.status !== 'success' ? 'hot' : '', cells: [l.started_at, l.workflow, l.user, l.route, l.status, l.duration_ms, l.error_node || ''] }));
      if (rows.length) box.append(table(['시작', '워크플로우', '고객', 'route', '상태', 'ms', '오류 노드'], rows));
    } else if (state.opsTab === 'fault') {
      const wrap = el('div', 'switches');
      for (const [k, v] of Object.entries(d)) {
        if (typeof v === 'object') continue;
        wrap.append(el('span', 'switch ' + (v === 'ok' || typeof v === 'number' ? 'ok' : 'bad'), `${k}: ${v}`));
      }
      box.append(wrap, el('p', 'muted', '읽기 전용입니다. 시험(flow.py test WF-04·11)이 켜고 끈 상태가 그대로 보입니다.'));
    }
  }

  // ── 갱신 ───────────────────────────
  async function pollChats() {
    try {
      const out = await getJSON('/api/admin/chats?since=' + state.seq);
      state.target = out.target;
      if (out.last_seq < state.seq) { state.items = []; state.seq = 0; state.selected = null; $('detail').textContent = ''; return pollChats(); }
      const fresh = new Set(out.items.map((i) => i.seq));
      if (out.items.length) {
        state.items.push(...out.items);
        state.items = state.items.slice(-500);
        state.seq = out.last_seq;
        // 새 대화가 오면 가장 최근 것을 자동으로 연다 (발표 화면에서 손 안 대도 보이게)
        const last = out.items[out.items.length - 1];
        state.selected = last.seq;
        drawDetail(view(last));
      }
      const views = state.items.map(view);
      drawMetrics(views);
      drawFaults(views);
      drawFilters();
      drawList(fresh);
      $('a-updated').textContent = '갱신 ' + new Date().toLocaleTimeString('ko-KR');
    } catch (e) {
      $('a-updated').textContent = '웹앱 연결 끊김';
    }
  }

  async function pollOps() {
    await Promise.all(OPS_TABS.map(async ([id]) => {
      try { state.ops[id] = await getJSON('/api/admin/ops/' + id); } catch (e) { state.ops[id] = { error: String(e) }; }
    }));
    drawOpsTabs();
    drawOps();
    drawFaults(state.items.map(view));
  }

  async function init() {
    const cfg = await getJSON('/api/config');
    $('a-target').textContent = `${cfg.target === 'vm' ? 'VM' : '로컬'} n8n · ${cfg.n8n_host}`;
    $('a-clear').onclick = async () => {
      await fetch('/api/admin/chats/clear', { method: 'POST' });
      state.items = []; state.seq = 0; state.selected = null;
      $('detail').textContent = '';
      pollChats();
    };
    drawOpsTabs();
    await pollChats();
    pollOps();
    setInterval(pollChats, 1500);
    setInterval(pollOps, 5000);
  }

  init();
})();
