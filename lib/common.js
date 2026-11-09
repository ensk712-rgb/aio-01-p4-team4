// 티켓모아 공통 함수 (n8n Code 노드용)
//
// 쓰는 법: 필요한 함수만 Code 노드 맨 위에 복사해서 붙인다.
// n8n Code 노드는 기본 설정에서 로컬 파일을 require할 수 없으므로, 이 파일이 "원본"이고
// 노드 안의 복사본은 이 파일과 똑같이 유지한다. 함수를 고치면 여기서 고치고 테스트를 돌린 뒤 다시 복사한다.
// 각 함수는 다른 함수에 기대지 않는다 (ROUTES 상수만 예외). 외부 라이브러리 없음.
//
// 테스트: node --test lib/test/*.test.js

// ---------------------------------------------------------------------------
// 1. 공통 계약 상수
// ---------------------------------------------------------------------------

const ROUTES = {
  AUTO: '자동 답변',
  CLARIFY: '보완 질문',
  HANDOFF: '담당자 이관',
  FORBIDDEN: '권한 없음',
  BLOCKED: '차단',
};

const MAX_QUESTION_LENGTH = 500; // 501자부터 400
const MAX_ATTEMPT = 3;           // 3회째 보완 질문 대신 이관
const CONFIDENCE_MIN = 0.7;      // 미만이면 보완 질문
const REFUND_APPROVAL_LIMIT = 300000; // 넘으면 상담원 승인 (refund-policy 4절)
const URGENT_MINUTES = 30;       // 공연 시작 30분 이내 입장 문제 = 긴급 (onsite-entry-fallback 1절)

// ---------------------------------------------------------------------------
// 2. 입력 검사 (본체 ticketmoa-support, LLM 전에)
// ---------------------------------------------------------------------------

/**
 * 요청 본문을 검사한다.
 * @param {object} body  Webhook 요청 본문
 * @param {Array<{name:string}>} users  data/users.json
 * @returns {{ok:boolean, codes:string[], user:object|null}}
 * 실패하면 본체는 HTTP 400 {"error":"invalid request","codes":codes}로 응답한다.
 */
function validateRequest(body, users) {
  const codes = [];
  const b = body || {};
  if (!b.request_id || typeof b.request_id !== 'string') codes.push('missing_request_id');
  const q = typeof b.question === 'string' ? b.question.trim() : '';
  if (!q) codes.push('empty_question');
  if (typeof b.question === 'string' && b.question.length > MAX_QUESTION_LENGTH) codes.push('question_too_long');
  const user = (users || []).find(u => u.name === b.user) || null;
  if (!b.user) codes.push('missing_user');
  else if (!user) codes.push('unknown_user');
  if (b.attempt !== undefined && !(Number.isInteger(b.attempt) && b.attempt >= 1)) codes.push('invalid_attempt');
  return { ok: codes.length === 0, codes, user };
}

// ---------------------------------------------------------------------------
// 3. 주입 차단 (규칙, LLM 전에) · WF-08
// ---------------------------------------------------------------------------

const INJECTION_PATTERNS = [
  /(이전|위|앞)의?\s*(모든\s*)?(지시|명령|규칙|프롬프트)(는|을|를)?\s*(모두\s*)?(무시|잊)/,
  /시스템\s*프롬프트/,
  /(개발자|관리자|디버그)\s*모드/,
  /너는\s*이제\s*(부터)?/,
  /ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts?)/i,
  /system\s+prompt/i,
  /(수수료|환불|결제).{0,10}(0원|무료)으로\s*(처리|해)/,
];

/**
 * @param {string} text
 * @returns {{blocked:boolean, blocked_by:string, reason:string}}
 * blocked면 본체는 LLM을 부르지 않고 route "차단", security.blocked_by "rule"로 응답한다.
 */
function detectInjection(text) {
  const t = String(text || '');
  for (const p of INJECTION_PATTERNS) {
    if (p.test(t)) return { blocked: true, blocked_by: 'rule', reason: 'injection_pattern' };
  }
  return { blocked: false, blocked_by: '', reason: '' };
}

// ---------------------------------------------------------------------------
// 4. 개인정보 가림 · WF-07
// ---------------------------------------------------------------------------

/**
 * 전화번호와 이메일을 가린다. 010-0000-3307 → 010-****-3307, doyoon.lee@example.com → d***@example.com
 * @param {string} text
 * @returns {{text:string, masked:number}}
 */
function maskPII(text) {
  let masked = 0;
  let out = String(text == null ? '' : text);
  out = out.replace(/\b(01[016789])[-.\s]?(\d{3,4})[-.\s]?(\d{4})\b/g, (_, a, _b, c) => { masked++; return `${a}-****-${c}`; });
  out = out.replace(/\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b/g, (_, first, domain) => { masked++; return `${first}***@${domain}`; });
  return { text: out, masked };
}

/**
 * 객체 안의 모든 문자열을 가린다 (예약 조회 결과, 티켓 요약 등).
 * @returns {{value:any, masked:number}}
 */
function maskDeep(value) {
  let masked = 0;
  const walk = v => {
    if (typeof v === 'string') { const r = maskPII(v); masked += r.masked; return r.text; }
    if (Array.isArray(v)) return v.map(walk);
    if (v && typeof v === 'object') { const o = {}; for (const k of Object.keys(v)) o[k] = walk(v[k]); return o; }
    return v;
  };
  return { value: walk(value), masked };
}

// ---------------------------------------------------------------------------
// 5. Agent 출력 읽기 (fail-closed)
// ---------------------------------------------------------------------------

/**
 * LLM 출력에서 JSON을 꺼낸다. ```json 코드 블록이나 앞뒤 설명이 있어도 첫 객체를 읽는다.
 * 못 읽거나 required 칸이 없으면 fallback을 돌려준다 (본체는 fallback이면 이관).
 * @param {string|object} raw
 * @param {string[]} required  꼭 있어야 하는 칸
 * @param {object} fallback
 * @returns {{ok:boolean, value:object}}
 */
function parseAgentJson(raw, required, fallback) {
  const fb = { ok: false, value: fallback || {} };
  let obj = raw;
  if (typeof raw === 'string') {
    const s = raw.replace(/```(?:json)?/gi, '');
    const start = s.indexOf('{');
    const end = s.lastIndexOf('}');
    if (start < 0 || end <= start) return fb;
    try { obj = JSON.parse(s.slice(start, end + 1)); } catch (e) { return fb; }
  }
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return fb;
  for (const k of required || []) if (!(k in obj)) return fb;
  return { ok: true, value: obj };
}

// ---------------------------------------------------------------------------
// 6. 재시도 판단 · WF-04, WF-11
// ---------------------------------------------------------------------------

/**
 * 429·5xx·timeout만 재시도한다. 401·403·그 밖의 4xx는 재시도하지 않는다.
 * @param {number|null} status  HTTP 상태 (응답이 없으면 null)
 * @param {string} [errorCode]  예: 'ETIMEDOUT', 'ECONNABORTED', 'ECONNREFUSED'
 */
function shouldRetry(status, errorCode) {
  if (status === 429) return true;
  if (typeof status === 'number' && status >= 500) return true;
  if (!status && /TIMEDOUT|ABORTED|ECONNRESET|timeout/i.test(String(errorCode || ''))) return true;
  return false;
}

/**
 * 다음 재시도까지 기다릴 시간(ms). Retry-After(초)가 있으면 그것을 따르되 상한을 둔다.
 * attempt는 1부터. 기본 500ms, 1000ms, 2000ms ...
 */
function backoffMs(attempt, retryAfterSeconds, capMs) {
  const cap = capMs || 3000;
  if (retryAfterSeconds && Number(retryAfterSeconds) > 0) return Math.min(Number(retryAfterSeconds) * 1000, cap);
  return Math.min(500 * Math.pow(2, Math.max(0, attempt - 1)), cap);
}

// ---------------------------------------------------------------------------
// 7. 응답 조립 (공통 계약) · 모든 시나리오
// ---------------------------------------------------------------------------

/**
 * 공통 계약의 칸을 모두 채운 응답을 만든다. 빠진 칸은 기본값.
 * answer는 여기서 한 번 더 가리고, 가린 개수를 security.masked에 더한다.
 */
function buildResponse(p) {
  const x = p || {};
  const m = maskPII(x.answer || '');
  const security = Object.assign({ blocked_by: '', reason: '', masked: 0 }, x.security || {});
  security.masked = (security.masked || 0) + m.masked;
  return {
    request_id: x.request_id || '',
    route: x.route || ROUTES.HANDOFF,
    answer: m.text,
    sources: Array.isArray(x.sources) ? x.sources.map(s => ({ doc: s.doc, section: s.section, score: s.score })) : [],
    ticket: x.ticket === undefined ? null : x.ticket,
    agents: x.agents || {},
    security,
    timings: x.timings || {},
    reason: x.reason || '',
  };
}

/** 400 응답 본문 */
function badRequest(codes) {
  return { error: 'invalid request', codes: codes || [] };
}

// ---------------------------------------------------------------------------
// 8. 라우팅 규칙 (LLM 아님) · WF-02, 02b, 12, TM-05
// ---------------------------------------------------------------------------

/**
 * 분류 결과와 요청으로 다음 갈 곳을 정한다.
 * @param {{intents:string[], confidence:number, missing:string[], sentiment:string, urgency:string}} cls
 * @param {{attempt:number}} req
 * @returns {{next:'clarify'|'handoff'|'handler', reason:string}}
 */
function decideRoute(cls, req) {
  const c = cls || {};
  const attempt = (req && req.attempt) || 1;
  const intents = c.intents || [];
  if (intents.includes('human_request')) return { next: 'handoff', reason: 'customer_asked_human' };
  if (c.sentiment === 'angry') return { next: 'handoff', reason: 'strong_negative_sentiment' };
  if (!intents.length && c.clarity === 'clear' && (c.confidence || 0) >= CONFIDENCE_MIN) return { next: 'handoff', reason: 'unregistered_intent' };
  const unsure = !intents.length || (c.confidence || 0) < CONFIDENCE_MIN || (c.missing || []).length > 0;
  if (unsure) {
    if (attempt >= MAX_ATTEMPT) return { next: 'handoff', reason: 'clarify_limit_reached' };
    return { next: 'clarify', reason: 'low_confidence_or_missing' };
  }
  return { next: 'handler', reason: '' };
}

/**
 * 공연 시작까지 남은 시간으로 긴급도를 정한다.
 * @param {string} showStartISO  예: '2026-11-08T19:30:00+09:00'
 * @param {Date} [now]
 */
function urgencyFor(showStartISO, now) {
  if (!showStartISO) return 'normal';
  const diffMin = (new Date(showStartISO) - (now || new Date())) / 60000;
  return diffMin >= -20 && diffMin <= URGENT_MINUTES ? 'high' : 'normal';
}

// ---------------------------------------------------------------------------
// 9. 환불 계산 · TM-02, 03, 06 (knowledge/refund-policy.md 2절과 같아야 함)
// ---------------------------------------------------------------------------

/**
 * 환불 예정 금액을 계산한다. 날짜는 한국 시간 기준 날짜로 센다.
 * @param {{amount:number, qty:number, bookedAt:string, showAt:string, now?:string}} b
 * @returns {{allowed:boolean, fee:number, bookingFeeRefund:number, refund:number, rule:string, needsApproval:boolean}}
 */
function calcRefund(b) {
  const now = b.now ? new Date(b.now) : new Date();
  const kstDay = d => { const k = new Date(d.getTime() + 9 * 3600000); return Date.UTC(k.getUTCFullYear(), k.getUTCMonth(), k.getUTCDate()); };
  const day = 86400000;
  const show = new Date(b.showAt);
  const booked = new Date(b.bookedAt);
  const daysToShow = Math.round((kstDay(show) - kstDay(now)) / day);
  const daysSinceBooked = Math.round((kstDay(now) - kstDay(booked)) / day);
  const qty = b.qty || 1;
  const amount = b.amount || 0;

  // 관람일 전날 오후 5시(KST)까지
  const deadline = new Date(kstDay(show) - day + 17 * 3600000 - 9 * 3600000);
  if (now > deadline) return { allowed: false, fee: 0, bookingFeeRefund: 0, refund: 0, rule: 'after_deadline', needsApproval: true };

  let fee; let rule;
  if (daysSinceBooked <= 7 && daysToShow >= 10) { fee = 0; rule = 'within_7_days_of_booking'; }
  else if (daysToShow >= 10) { fee = Math.min(2000 * qty, Math.floor(amount * 0.1)); rule = 'flat_2000_per_ticket'; }
  else if (daysToShow >= 7) { fee = Math.floor(amount * 0.1); rule = '9_to_7_days'; }
  else if (daysToShow >= 3) { fee = Math.floor(amount * 0.2); rule = '6_to_3_days'; }
  else { fee = Math.floor(amount * 0.3); rule = '2_days_to_day_before'; }

  const bookingFeeRefund = daysSinceBooked === 0 ? 1000 * qty : 0;
  const refund = amount - fee + bookingFeeRefund;
  return { allowed: true, fee, bookingFeeRefund, refund, rule, needsApproval: refund > REFUND_APPROVAL_LIMIT };
}

// ---------------------------------------------------------------------------
// 10. 권한 · WF-05
// ---------------------------------------------------------------------------

/** 사용자 권한에 맞는 검색 메모리 키 (검색 전 필터) */
function memoryKeysFor(user) {
  const keys = ['ticketmoa_kb_v1_all'];
  if (user && user.access_level === 'staff') keys.push('ticketmoa_kb_v1_staff');
  return keys;
}

// ---------------------------------------------------------------------------
// 11. 실행 기록 (/logs) · 개인정보 없이
// ---------------------------------------------------------------------------

/** 기록에 남겨도 되는 channel 값. 자유 문자열을 그대로 쓰면 연락처가 로그에 남을 수 있다. */
const CHANNELS = ['web', 'app', 'phone', 'kiosk', 'email', 'other'];

/** 승인 목록에 없는 값은 가리지 않고 통째로 other로 바꾼다. 가린 것이 아니므로 security.masked에 세지 않는다. */
function normalizeChannel(channel) {
  return typeof channel === 'string' && CHANNELS.includes(channel) ? channel : 'other';
}

/**
 * POST /logs에 보낼 기록. 질문 원문·답변·연락처는 넣지 않는다.
 * @param {object} req   요청 본문
 * @param {object} res   buildResponse 결과
 * @param {object} [extra]  {intents, retries, top_scores, started_at}
 */
function classifyOutcome(res) {
  const agents = res.agents || {};
  const code = x => typeof x === 'string' && /^[a-z][a-z0-9_:-]{0,79}$/.test(x);
  const reason = code(res.reason) ? res.reason : '';
  const issues = Array.isArray(agents.verification_issues) ? [...new Set(agents.verification_issues.filter(code))].slice(0, 10) : [];
  const dependency = /(?:unavailable|timeout|_failed)$/.test(reason) && reason !== 'verification_failed'
    || issues.some(x => /(?:unavailable|timeout)$/.test(x))
    || Boolean(agents.error || agents.search_error || (agents.handoff || {}).error);
  // 이관을 시도했는데 티켓이 없으면 사유와 상관없이 장애다 (WF-04: 사유는 원래 분류값으로 남는다).
  const ticketMissing = Boolean(agents.handoff) && !res.ticket;
  const malformed = ['writer_unreadable', 'writer_empty_answer'].includes(reason) || issues.includes('unreadable');
  const rejected = reason === 'verification_failed';
  const error = dependency || ticketMissing || malformed || rejected;
  const failure_kind = dependency || ticketMissing ? 'dependency' : malformed ? 'model_output' : rejected ? (issues.length ? 'verification_rejected' : 'verification_unknown') : reason === 'no_evidence' ? 'no_evidence' : '';
  return { reason, verification_issues: issues, failure_kind, status: error ? 'error' : 'success', error_message: error ? (ticketMissing ? 'ticket_not_created' : (reason || 'upstream_error')) : null };
}

function buildLog(req, res, extra) {
  const e = extra || {};
  return {
    request_id: (req && req.request_id) || '',
    channel: normalizeChannel(req && req.channel),
    attempt: (req && req.attempt) || 1,
    route: res.route,
    intents: e.intents || [],
    sources: (res.sources || []).map(s => `${s.doc}#${s.section}`),
    top_scores: e.top_scores || (res.sources || []).map(s => s.score),
    ticket: res.ticket ? (res.ticket.id || res.ticket.key || true) : null,
    retries: e.retries || 0,
    blocked_by: res.security.blocked_by,
    masked: res.security.masked,
    timings: res.timings,
    started_at: e.started_at || '',
    finished_at: new Date().toISOString(),
    ...classifyOutcome(res),
  };
}

// ---------------------------------------------------------------------------
// 11b. Error Workflow 이벤트 정규화 · 오류 알림에 허용된 필드만 전달
// ---------------------------------------------------------------------------

const ERROR_WORKFLOW_SLUGS = [
  'support', 'agents', 'refund', 'payment', 'handoff', 'errors', 'tech', 'search', 'index', 'ops',
];
const ERROR_TYPES = new Set([
  'Error', 'TypeError', 'RangeError', 'ReferenceError', 'SyntaxError', 'TimeoutError',
  'AbortError', 'NodeApiError', 'NodeOperationError', 'WorkflowError',
]);

/**
 * Error Trigger payload를 허용 필드로 축소한다. 메시지, 요청 본문, 스택은 반환하지 않는다.
 * @param {object} event n8n Error Trigger 입력
 * @param {Date} [now] 테스트용 시각
 */
function normalizeErrorEvent(event, now) {
  const e = event && typeof event === 'object' ? event : {};
  const workflow = e.workflow && typeof e.workflow === 'object' ? e.workflow : {};
  const execution = e.execution && typeof e.execution === 'object' ? e.execution : {};
  const error = execution.error && typeof execution.error === 'object' ? execution.error : {};
  const rawName = String(workflow.name || '').toLowerCase();
  const slug = ERROR_WORKFLOW_SLUGS.find(name => new RegExp(`(^|[^a-z0-9])ticketmoa-${name}([^a-z0-9]|$)`).test(rawName));
  const workflowIdRaw = String(workflow.id || '');
  const workflowId = /^[A-Za-z0-9_-]{1,80}$/.test(workflowIdRaw) ? workflowIdRaw : 'unknown';
  const executionIdRaw = String(execution.id || '');
  const executionId = /^\d{1,24}$/.test(executionIdRaw) ? executionIdRaw : '';
  const typeRaw = String(error.name || '');
  const errorType = ERROR_TYPES.has(typeRaw) ? typeRaw : 'unknown_error';
  const nodeRaw = String(execution.lastNodeExecuted || error.node?.name || '');
  const safeNode = /^[\p{L}\p{N}][\p{L}\p{N} ._()/-]{0,79}$/u.test(nodeRaw)
    && !/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/.test(nodeRaw)
    && !/\b\d{2,3}[-. ]\d{3,4}[-. ]\d{4}\b/.test(nodeRaw);
  const normalized = {
    at: (now || new Date()).toISOString(),
    workflow_id: workflowId,
    workflow: slug ? `ticketmoa-${slug}` : 'ticketmoa-unknown',
    execution_id: executionId,
    error_type: errorType,
    failed_node: safeNode ? nodeRaw : 'unknown',
    severity: 'critical',
    reason: 'unexpected_execution_error',
  };
  normalized.dedupe_key = executionId ? `error-alert:${workflowId}:${executionId}` : '';
  return normalized;
}

/** 캐시에서 같은 실행이 확인되면 알림을 생략하고, 캐시 실패 시 알림을 허용한다. */
function shouldSendErrorAlert(cacheResponse, dedupeKey) {
  if (!dedupeKey) return true;
  const response = cacheResponse && typeof cacheResponse === 'object' ? cacheResponse : {};
  const value = response.body && typeof response.body === 'object' ? response.body.value : null;
  return !(response.statusCode === 200 && value && value.dedupe_key === dedupeKey && value.sent === true);
}

// ---------------------------------------------------------------------------
// 12. 반복 요청 차단 (매크로 대응, 가산) · TM-09
// ---------------------------------------------------------------------------

const RATE_LIMIT = { max: 5, windowSeconds: 60 }; // 같은 사용자·같은 질문이 60초에 5건 넘으면 차단

/**
 * 반복 요청을 세는 캐시 키. 같은 사용자가 같은 질문을 되풀이하는 것(매크로)만 센다.
 * 사용자 단위로만 세면 공통 시나리오(김하늘 유효 요청 5건)와 시연에서 정상 문의까지 막힌다.
 * 질문 원문은 키에 남기지 않고 공백을 정리한 앞 100자의 FNV-1a 해시만 쓴다.
 * @param {string} user
 * @param {string} question
 * @returns {string} 예: "ratelimit:박서준:1a2b3c4d"
 */
function rateLimitKey(user, question) {
  const q = String(question == null ? '' : question).replace(/\s+/g, ' ').trim().toLowerCase().slice(0, 100);
  let h = 0x811c9dc5;
  for (let i = 0; i < q.length; i++) {
    h ^= q.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return `ratelimit:${String(user || '')}:${h.toString(16).padStart(8, '0')}`;
}

/**
 * 최근 요청 목록으로 차단 여부를 정한다.
 * 목록은 데이터 API /cache/<rateLimitKey>에 저장하고, 돌려준 recent를 다시 저장한다.
 * requestId를 주면 같은 request_id는 한 번만 센다 (--repeat·bench·재전송은 같은 본문을 다시 보낸다).
 * @param {Array<string|{at:string,rid:string}>} recent  이전 요청 (ISO 문자열 또는 {at, rid}, 없으면 [])
 * @param {Date} [now]
 * @param {string} [requestId]
 * @returns {{blocked:boolean, recent:Array, count:number, reason:string}}
 * blocked면 LLM을 부르지 않고 route "차단", security.blocked_by "rate_limit".
 */
function checkRateLimit(recent, now, requestId) {
  const t = now || new Date();
  const from = t.getTime() - RATE_LIMIT.windowSeconds * 1000;
  const at = x => new Date(x && typeof x === 'object' ? x.at : x).getTime();
  const kept = (Array.isArray(recent) ? recent : []).filter(x => at(x) > from);
  const seen = requestId && kept.some(x => x && typeof x === 'object' && x.rid === requestId);
  if (!seen) kept.push(requestId ? { at: t.toISOString(), rid: String(requestId) } : t.toISOString());
  const blocked = kept.length > RATE_LIMIT.max;
  return { blocked, recent: kept, count: kept.length, reason: blocked ? 'too_many_requests' : '' };
}

// ---------------------------------------------------------------------------
// 13. 가상 IP 차단 (해외 접속·블랙리스트, 가산) · TM-10, TM-11
// ---------------------------------------------------------------------------

/**
 * 요청 context.client_ip를 config/ip-policy.json으로 검사한다.
 * IP가 없으면(수업 환경의 일반 요청) 통과시킨다.
 * @param {string} ip
 * @param {{geo:Array<{prefix:string,country:string}>, allowed_countries:string[], blocklist:string[], blocklist_reason:object}} policy
 * @returns {{blocked:boolean, blocked_by:string, reason:string, country:string}}
 * blocked면 LLM을 부르지 않고 route "차단". 해외 차단 안내는 fair-booking-policy 3절 문구를 쓴다.
 */
function checkIpPolicy(ip, policy) {
  const p = policy || {};
  if (!ip) return { blocked: false, blocked_by: '', reason: '', country: '' };
  if ((p.blocklist || []).includes(ip)) {
    return { blocked: true, blocked_by: 'ip_blocklist', reason: (p.blocklist_reason || {})[ip] || 'blocklisted', country: '' };
  }
  const hit = (p.geo || []).find(g => ip.startsWith(g.prefix));
  const country = hit ? hit.country : 'UNKNOWN';
  if (!(p.allowed_countries || []).includes(country)) {
    return { blocked: true, blocked_by: 'geo', reason: 'country_not_allowed', country };
  }
  return { blocked: false, blocked_by: '', reason: '', country };
}

// ---------------------------------------------------------------------------
// 14. 티켓 담당 (규칙, LLM 아님) · docs/TICKET-EVIDENCE.md
// ---------------------------------------------------------------------------

/**
 * 티켓을 처리할 담당 역할. 긴급(입장 장애)은 현장 스태프, 암표 신고는 보안팀, 나머지는 CS 상담원이다.
 * 분류를 못 한 티켓(unknown)도 주인 없이 남지 않도록 CS 상담원이 받는다.
 * @param {string} category
 * @param {string} priority
 * @returns {string}
 */
function ticketAssignee(category, priority) {
  if (priority === 'high') return '현장 스태프';
  if (category === 'scalping_report') return '보안팀';
  return 'CS 상담원';
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    ROUTES, MAX_QUESTION_LENGTH, MAX_ATTEMPT, CONFIDENCE_MIN, REFUND_APPROVAL_LIMIT, URGENT_MINUTES,
    validateRequest, detectInjection, maskPII, maskDeep, parseAgentJson, shouldRetry, backoffMs,
    buildResponse, badRequest, decideRoute, urgencyFor, calcRefund, memoryKeysFor, CHANNELS, normalizeChannel, buildLog, classifyOutcome,
    RATE_LIMIT, rateLimitKey, checkRateLimit, checkIpPolicy, ticketAssignee,
    normalizeErrorEvent, shouldSendErrorAlert,
  };
}
