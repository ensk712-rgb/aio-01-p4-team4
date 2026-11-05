// 응답(공통 계약)만 보고 이 요청이 지나간 워크플로우 경로를 만든다. 브라우저와 node 시험이 같이 쓴다.
(function (root) {
  const NODES = [
    { id: 'input', row: 0, label: '입력 검사', sub: 'support · 길이 · 사용자' },
    { id: 'guard', row: 1, label: '보안 규칙', sub: '주입 · 반복 요청 · IP' },
    { id: 'agents', row: 2, label: '문의 분류', sub: 'agents · LLM' },
    { id: 'search', row: 3, label: '문서 검색', sub: 'search · 권한별 색인' },
    { id: 'payment', row: 3, label: '예매·문의 조회', sub: 'payment · 본인 확인' },
    { id: 'refund', row: 3, label: '환불 계산', sub: 'refund · 규정표' },
    { id: 'tech', row: 4, label: '답변 작성 · 검증', sub: 'tech · LLM' },
    { id: 'handoff', row: 5, label: '담당자 이관', sub: 'handoff · 티켓 · 알림' },
    { id: 'reply', row: 6, label: '응답', sub: '조립 · 가림 · 기록' },
  ];

  const GUARD = { rule: '주입 문구 감지', rate_limit: '같은 질문 반복', geo: '해외 접속', ip_blocklist: '차단 IP' };
  const INTENT = {
    tech_issue: '기술 문제', account_issue: '계정', general_info: '이용 안내', booking_lookup: '예매·문의 조회',
    payment_error: '결제 오류', fair_booking: '예매 제한', scalping_report: '암표 신고',
    refund_request: '환불', human_request: '상담원 요청',
  };

  function buildPath(status, body) {
    const b = body && typeof body === 'object' ? body : {};
    const st = {};
    const set = (id, state, note, ms) => { st[id] = { state, note: note || '', ms: typeof ms === 'number' ? ms : null }; };
    NODES.forEach((n) => set(n.id, 'skip'));

    if (status === 400) {
      set('input', 'stop', '거절 · ' + (b.codes || []).join(', '));
      return finish(st, '입력 거절', 0, null);
    }
    if (status !== 200 || !b.route) {
      set('input', 'stop', '응답 오류 ' + status + (b.error ? ' · ' + b.error : ''));
      return finish(st, '오류', 0, null);
    }

    const agents = b.agents || {};
    const used = Array.isArray(agents.used) ? agents.used : [];
    const t = b.timings || {};
    const sec = b.security || {};
    const reason = String(b.reason || '');
    set('input', 'done', '통과');

    if (sec.blocked_by) {
      set('guard', 'stop', (GUARD[sec.blocked_by] || sec.blocked_by) + ' → 차단');
      set('reply', 'done', 'LLM 0회', t.total_ms);
      return finish(st, b.route, agents.llm_calls || 0, t.total_ms);
    }
    set('guard', 'done', '통과');

    if (used.includes('ticketmoa-agents')) {
      const intents = (agents.intents || []).map((i) => INTENT[i] || i);
      const conf = typeof agents.confidence === 'number' ? ' · 확신 ' + agents.confidence : '';
      set('agents', 'done', (intents.length ? intents.join(' + ') : '등록 업무 없음') + conf, t.agents_ms);
    } else if (used.includes('ticketmoa-refund')) {
      set('agents', 'skip', '확정 답장 → 분류 생략');
    }

    if (used.includes('ticketmoa-search')) {
      const src = Array.isArray(b.sources) ? b.sources : [];
      const top = src.reduce((m, s) => Math.max(m, Number(s.score) || 0), 0);
      set('search', 'done', src.length ? '근거 ' + src.length + '건 · 최고 ' + top.toFixed(2) : '쓸 근거 없음', t.search_ms);
    }
    if (used.includes('ticketmoa-payment')) {
      const note = reason === 'not_owner' ? '본인 건 아님 → 거절'
        : sec.masked ? '조회 · 연락처 ' + sec.masked + '개 가림' : '조회 완료';
      set('payment', reason === 'not_owner' ? 'stop' : 'done', note, t.payment_ms);
    }
    if (used.includes('ticketmoa-refund')) {
      const note = agents.pending_action ? '금액 안내 · 고객 확인 대기'
        : b.ticket ? '고객 확정 → 실행 대신 티켓' : '환불 규정 확인';
      set('refund', 'done', note, t.refund_ms);
    }
    if (used.includes('ticketmoa-tech')) {
      const failed = /^(writer_|verification_|budget_|llm_|no_evidence|tech_)/.test(reason);
      set('tech', failed ? 'stop' : 'done', failed ? '근거 부족 → 이관 (' + reason + ')' : '근거 안에서 작성 · 검증 통과', t.tech_ms);
    }
    if (used.includes('ticketmoa-handoff') || b.ticket) {
      const tk = b.ticket || {};
      const alert = agents.alert || (agents.handoff && agents.handoff.alert);
      const note = (tk.id ? '티켓 ' + tk.id : '접수') + (tk.priority === 'high' ? ' · 긴급' : '')
        + (alert ? ' · 현장 알림' : '');
      set('handoff', 'done', note, t.handoff_ms);
    }
    set('reply', 'done', 'LLM ' + (agents.llm_calls || 0) + '회', t.total_ms);
    return finish(st, b.route, agents.llm_calls || 0, t.total_ms);
  }

  // 재생 순서: 같은 줄(row 3)의 검색·조회는 함께 켠다.
  function finish(states, route, llm, totalMs) {
    const order = [];
    for (const n of NODES) {
      const s = states[n.id];
      if (s.state === 'skip') continue;
      const last = order[order.length - 1];
      if (last && n.row === 3 && last.row === 3) last.ids.push(n.id);
      else order.push({ row: n.row, ids: [n.id] });
    }
    return { states, order, route, llm, totalMs: typeof totalMs === 'number' ? totalMs : null };
  }

  const api = { NODES, buildPath };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.TicketmoaFlow = api;
})(this);
