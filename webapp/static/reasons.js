// 응답의 reason·handoff를 보고 "장애 때문에 이관된 건"과 "설계대로 처리된 건"을 나눈다.
// 관리자 화면과 node 시험이 같이 쓴다. 새 reason은 '미분류'로 보이게 해 놓친 코드를 알 수 있게 한다.
(function (root) {
  // kind: fault(시스템 장애) · quality(답을 만들었지만 근거·검증 실패) · normal(설계대로)
  const REASONS = {
    // 장애
    agents_failed: ['fault', '분류', '분류 에이전트 실패'],
    payment_failed: ['fault', '조회', '예매·문의 조회 실패'],
    lookup_failed: ['fault', '조회', '조회 실패'],
    user_lookup_failed: ['fault', '조회', '사용자 조회 실패'],
    refund_failed: ['fault', '환불', '환불 계산 실패'],
    llm_unavailable: ['fault', 'LLM', 'LLM 응답 없음'],
    budget_exhausted: ['fault', 'LLM', '시간 예산 소진'],
    ticket_failed: ['fault', '티켓', '티켓 생성 실패'],
    unexpected: ['fault', '워크플로우', '예상 못 한 오류'],
    // 품질
    writer_not_grounded: ['quality', '작성', '근거 없는 답'],
    writer_not_in_context: ['quality', '작성', '문서에 없는 내용'],
    writer_staff_only_terms: ['quality', '작성', '직원 전용 용어'],
    verification_failed: ['quality', '검증', '검증 불통과'],
    no_evidence: ['quality', '검색', '쓸 근거 없음'],
    // 정상 (설계대로 이관·거절·차단·보완)
    low_confidence_or_missing: ['normal', '분류', '정보 부족 → 보완 질문'],
    clarify_limit_reached: ['normal', '분류', '보완 질문 한도'],
    customer_asked_human: ['normal', '분류', '상담원 요청'],
    strong_negative_sentiment: ['normal', '분류', '강한 불만'],
    registry_handoff: ['normal', '분류', '담당 부서 업무'],
    staff_only_request: ['normal', '분류', '직원 전용 요청'],
    scalping_report: ['normal', '분류', '암표 신고'],
    macro_detected: ['normal', '분류', '매크로 의심'],
    urgent_entry: ['normal', '이관', '공연 임박 긴급'],
    payment_error_handoff: ['normal', '조회', '결제 오류 → 상담원'],
    payment_error: ['normal', '조회', '결제 오류'],
    not_owner: ['normal', '조회', '본인 건 아님'],
    lookup_forbidden: ['normal', '조회', '조회 권한 없음'],
    record_not_found: ['normal', '조회', '번호 없음'],
    refund_quote_pending_confirm: ['normal', '환불', '환불 금액 안내'],
    refund_confirmed: ['normal', '환불', '환불 확정 → 티켓'],
    refund_already_confirmed: ['normal', '환불', '이미 확정된 환불'],
    refund_declined: ['normal', '환불', '환불 취소'],
    refund_requote: ['normal', '환불', '환불 금액 재안내'],
    no_pending_refund: ['normal', '환불', '확정할 환불 없음'],
    show_day_cancel: ['normal', '환불', '공연 당일 취소'],
    over_limit: ['normal', '환불', '금액 한도 초과'],
    injection_pattern: ['normal', '보안', '주입 문구 차단'],
    too_many_requests: ['normal', '보안', '반복 요청 차단'],
    country_not_allowed: ['normal', '보안', '해외 접속 차단'],
    invalid_request: ['normal', '입력', '잘못된 입력'],
  };

  const KIND_LABEL = { fault: '장애', quality: '품질', normal: '정상', unknown: '미분류', error: '연결 오류' };

  // status: 웹훅 HTTP 상태, body: 응답 본문
  function classify(status, body) {
    const b = body && typeof body === 'object' ? body : {};
    if (status === 400) return { kind: 'normal', stage: '입력', label: '잘못된 입력', reason: 'invalid_request' };
    if (status !== 200 || !b.route) {
      return { kind: 'error', stage: '연결', label: b.error ? String(b.error).slice(0, 60) : 'HTTP ' + status, reason: '' };
    }
    const handoff = (b.agents && b.agents.handoff) || {};
    // 티켓 실패는 reason보다 우선한다 (이관하려 했는데 티켓을 못 만든 건).
    if (b.route === '담당자 이관' && !b.ticket && (handoff.dlq || handoff.error)) {
      return { kind: 'fault', stage: '티켓', label: '티켓 생성 실패' + (handoff.dlq ? ' · DLQ' : ''), reason: 'ticket_failed' };
    }
    const reason = String(b.reason || '');
    if (!reason) return { kind: 'normal', stage: '', label: b.route, reason: '' };
    const hit = REASONS[reason];
    if (hit) return { kind: hit[0], stage: hit[1], label: hit[2], reason };
    if (/_failed$|_error$|timeout|unavailable/.test(reason)) return { kind: 'fault', stage: '?', label: reason, reason };
    return { kind: 'unknown', stage: '?', label: reason, reason };
  }

  const api = { REASONS, KIND_LABEL, classify };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.TicketmoaReasons = api;
})(this);
