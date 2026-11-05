// 티켓모아 상담 채팅 + 워크플로우 흐름 재생.
// ?example=<id>&autoplay=1 이면 예시 민원을 자동으로 입력·전송한다 (GIF 녹화용, 끝나면 body[data-done="1"]).
(() => {
  const { NODES, buildPath } = window.TicketmoaFlow;
  const $ = (id) => document.getElementById(id);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const params = new URLSearchParams(location.search);

  const ROUTE_CLASS = { '자동 답변': 'auto', '보완 질문': 'clarify', '담당자 이관': 'handoff', '권한 없음': 'forbid', '차단': 'block' };
  const BAR_PARTS = [['agents', '분류'], ['search', '검색'], ['payment', '조회'], ['refund', '환불'], ['tech', '작성·검증'], ['handoff', '이관']];

  const state = { config: null, attempt: 1, previous: '', pending: null, busy: false, playing: false };

  // ── 흐름 그래프 ─────────────────────
  function drawGraph() {
    const graph = $('graph');
    graph.textContent = '';
    const rows = new Map();
    for (const n of NODES) {
      if (!rows.has(n.row)) {
        const row = document.createElement('div');
        row.className = 'row' + (n.row === 3 ? ' branch' : '');
        rows.set(n.row, row);
        graph.append(row);
      }
      const el = document.createElement('div');
      el.className = 'node ' + n.id;
      el.id = 'node-' + n.id;
      el.innerHTML = '<div class="top"><b></b><span class="ms"></span></div><div class="sub"></div><div class="note"></div>';
      el.querySelector('b').textContent = n.label;
      el.querySelector('.sub').textContent = n.sub;
      rows.get(n.row).append(el);
    }
  }

  function setNode(id, cls, note, ms) {
    const el = $('node-' + id);
    el.className = 'node ' + id + (cls ? ' ' + cls : '');
    el.querySelector('.note').textContent = note || '';
    el.querySelector('.ms').textContent = typeof ms === 'number' ? (ms / 1000).toFixed(2) + 's' : '';
  }

  function resetGraph() {
    for (const n of NODES) setNode(n.id, '', '', null);
    $('bar').textContent = '';
    $('bar').style.display = 'none';
  }

  async function playPath(path) {
    state.playing = true;
    for (const n of NODES) if (path.states[n.id].state === 'skip') setNode(n.id, 'skip', path.states[n.id].note, null);
    for (const step of path.order) {
      const longest = Math.max(0, ...step.ids.map((id) => path.states[id].ms || 0));
      for (const id of step.ids) setNode(id, 'active', path.states[id].note, path.states[id].ms);
      await sleep(Math.min(950, Math.max(420, 320 + longest * 0.12)));
      for (const id of step.ids) setNode(id, path.states[id].state, path.states[id].note, path.states[id].ms);
    }
    state.playing = false;
  }

  function drawBar(timings) {
    const t = timings || {};
    const total = t.total_ms || 0;
    const bar = $('bar');
    bar.textContent = '';
    if (!total) return;
    let used = 0;
    for (const [key, label] of BAR_PARTS) {
      const ms = t[key + '_ms'];
      if (!ms) continue;
      used += ms;
      const span = document.createElement('span');
      span.className = key;
      span.style.width = (100 * ms / total) + '%';
      span.title = label + ' ' + ms + 'ms';
      span.textContent = `${label} ${(ms / 1000).toFixed(1)}s`;
      bar.append(span);
    }
    if (total > used) {
      const rest = document.createElement('span');
      rest.className = 'rest';
      rest.style.width = (100 * (total - used) / total) + '%';
      bar.append(rest);
    }
    bar.style.display = 'flex';
  }

  // ── 채팅 ───────────────────────────
  const now = () => new Date().toLocaleTimeString('ko-KR', { hour: 'numeric', minute: '2-digit' });

  function addMessage(kind, text, extra) {
    const li = document.createElement('li');
    li.className = 'msg ' + kind;
    if (kind === 'notice') {
      li.innerHTML = '<div class="bubble"></div>';
      li.querySelector('.bubble').textContent = text;
    } else {
      const avatar = kind === 'bot' ? '<div class="avatar bot">TM</div>' : '';
      const name = kind === 'bot' ? '<span class="name">티켓모아 상담봇</span>' : '';
      const time = `<span class="time">${now()}</span>`;
      li.innerHTML = `${avatar}<div class="col">${name}<div class="line"><div class="bubble"></div>${time}</div></div>`;
      const bubble = li.querySelector('.bubble');
      if (text === null) {
        bubble.classList.add('typing-bubble');
        bubble.innerHTML = '<span class="typing"><i></i><i></i><i></i></span>';
      } else bubble.textContent = text;
      if (extra) bubble.append(extra);
    }
    $('messages').append(li);
    $('messages').scrollTop = $('messages').scrollHeight;
    return li;
  }

  function metaChips(body) {
    const wrap = document.createElement('div');
    wrap.className = 'meta';
    const chip = (text, cls) => {
      const s = document.createElement('span');
      s.className = 'chip' + (cls ? ' ' + cls : '');
      s.textContent = text;
      wrap.append(s);
    };
    if (body.route) chip(body.route, 'route ' + (ROUTE_CLASS[body.route] || ''));
    const docs = [...new Set((body.sources || []).map((s) => s.doc))];
    for (const d of docs.slice(0, 2)) chip('📄 ' + d);
    if (body.ticket && body.ticket.id) chip('🎫 ' + body.ticket.id + (body.ticket.priority === 'high' ? ' 긴급' : ''));
    if (body.security && body.security.masked) chip('🔒 연락처 ' + body.security.masked + '개 가림');
    return wrap;
  }

  function botText(status, body) {
    if (status === 400) return '입력을 확인해 주세요. (' + (body.codes || []).join(', ') + ')';
    if (status !== 200) return '지금은 연결이 원활하지 않습니다. 잠시 뒤 다시 시도해 주세요.';
    return body.answer || '(답변 없음)';
  }

  function setQuick(pending) {
    const box = $('quick');
    box.textContent = '';
    box.hidden = !pending;
    if (!pending) return;
    const yes = document.createElement('button');
    yes.type = 'button';
    yes.id = 'quick-yes';
    yes.textContent = '네, 취소 확정할게요';
    yes.onclick = () => send('네 취소 확정할게요', { confirm: true });
    const no = document.createElement('button');
    no.type = 'button';
    no.textContent = '아니요';
    no.onclick = () => { state.pending = null; setQuick(null); addMessage('notice', '취소하지 않았습니다'); };
    box.append(yes, no);
  }

  async function send(question, opts = {}) {
    if (state.busy) return;
    state.busy = true;
    $('send').disabled = true;
    setQuick(null);
    const context = {};
    if (opts.confirm && state.pending) {
      context.pending_action = 'refund_request';
      context.booking_id = state.pending.booking_id;
      context.confirm = true;
    }
    if (state.attempt > 1 && state.previous) context.previous_question = state.previous;
    addMessage('me', question);
    const typing = addMessage('bot', null);

    resetGraph();
    setNode('input', 'wait', 'n8n 처리 중…', null);
    const t0 = performance.now();
    const timer = setInterval(() => { $('status').textContent = `n8n 처리 중 · ${((performance.now() - t0) / 1000).toFixed(1)}s`; }, 100);

    let status = 0;
    let body = {};
    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user: $('user').value, question, attempt: state.attempt, context }),
      });
      const out = await res.json();
      status = res.ok ? out.status : res.status;
      body = res.ok ? out.body : out;
    } catch (e) {
      status = 0;
      body = { error: String(e) };
    }
    clearInterval(timer);
    const path = buildPath(status, body);
    $('status').textContent = '실제 경로 재생';
    await playPath(path);
    typing.remove();
    addMessage('bot', botText(status, body), status === 200 ? metaChips(body) : null);
    const ms = path.totalMs;
    const secs = ms == null ? '-' : ms < 1000 ? ms + 'ms' : (ms / 1000).toFixed(1) + '초';
    $('status').textContent = `${path.route} · 처리 ${secs} · LLM ${path.llm}회`;
    drawBar(body.timings);

    // 다음 턴 상태
    if (body.route === '보완 질문') { state.attempt += 1; state.previous = state.previous || question; }
    else { state.attempt = 1; state.previous = ''; }
    const pa = body.agents && body.agents.pending_action;
    state.pending = pa && pa.type === 'refund_request' ? pa : null;
    setQuick(state.pending);
    state.busy = false;
    $('send').disabled = false;
    return body;
  }

  // ── 예시 민원 자동 재생 ──────────────
  async function typeInto(text) {
    const box = $('question');
    box.value = '';
    for (const ch of text) {
      box.value += ch;
      updateCounter();
      await sleep(28);
    }
    await sleep(350);
  }

  function resetChat() {
    $('messages').textContent = '';
    state.attempt = 1; state.previous = ''; state.pending = null;
    setQuick(null);
    resetGraph();
    $('status').textContent = '대기';
  }

  function showExample(ex) {
    document.querySelectorAll('#examples button').forEach((b) => b.classList.toggle('on', b.dataset.id === (ex && ex.id)));
    $('ex-case').textContent = ex ? `예시 민원 · ${ex.case}` : 'n8n 워크플로우';
    $('ex-title').textContent = ex ? ex.title : '요청이 지나간 길';
    $('ex-point').textContent = ex ? ex.point : '질문을 보내면 실제 응답을 바탕으로 경로를 다시 보여 줍니다.';
  }

  async function runExample(ex) {
    if (state.busy) return;
    resetChat();
    showExample(ex);
    $('user').value = ex.user;
    addMessage('notice', `${ex.user} 님으로 상담 시작`);
    await sleep(600);
    for (const turn of ex.turns) {
      if (turn.confirm_pending) {
        const yes = $('quick-yes');
        if (yes) { yes.classList.add('tap'); await sleep(700); }
        $('question').value = '';
        await send(turn.question, { confirm: true });
      } else {
        await typeInto(turn.question);
        $('question').value = '';
        updateCounter();
        await send(turn.question);
      }
      await sleep(1600);
    }
  }

  // ── 초기화 ─────────────────────────
  function updateCounter() {
    const n = [...$('question').value].length;
    $('counter').textContent = `${n} / 500`;
    $('counter').classList.toggle('over', n > 500);
  }

  async function init() {
    drawGraph();
    resetGraph();
    const res = await fetch('/api/config');
    const cfg = await res.json();
    state.config = cfg;
    $('target').textContent = `${cfg.target === 'vm' ? 'VM' : '로컬'} n8n · ${cfg.n8n_host}${cfg.team_key_configured ? '' : ' · 팀 키 없음'}`;
    for (const u of cfg.users) {
      const o = document.createElement('option');
      o.value = u.name;
      o.textContent = `${u.name} (${u.grade})`;
      $('user').append(o);
    }
    for (const ex of cfg.examples) {
      const b = document.createElement('button');
      b.type = 'button';
      b.dataset.id = ex.id;
      b.textContent = ex.title;
      b.onclick = () => runExample(ex);
      $('examples').append(b);
    }
    $('question').addEventListener('input', updateCounter);
    $('question').addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); $('composer').requestSubmit(); }
    });
    $('composer').addEventListener('submit', (e) => {
      e.preventDefault();
      const q = $('question').value;
      $('question').value = '';
      updateCounter();
      send(q);
    });
    $('user').addEventListener('change', resetChat);

    const pick = cfg.examples.find((e) => e.id === params.get('example'));
    if (pick) {
      if (params.get('autoplay') === '1') {
        await runExample(pick);
        document.body.dataset.done = '1';
      } else showExample(pick);
    }
  }

  init();
})();
