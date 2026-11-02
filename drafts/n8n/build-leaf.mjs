// 말단 워크플로우: index, search, payment, handoff, errors, ops
import { Flow, lib, READ_HTTP, DATA_API, ERROR_WORKFLOW_ID } from './lib-build.mjs';

const js = String.raw;

export function buildIndex() {
  const f = new Flow({
    file: 'ticketmoa-index', name: 'ticketmoa-index', id: 'ticketmoaIndex001', owner: 'C RAG (정예진)',
    purpose: '지식 문서를 절(##) 단위로 나누어 권한별 In-Memory 저장소에 색인한다. 고객 요청 경로에서는 절대 부르지 않고, 배포·재시작 뒤 한 번 실행한다.',
    reference: 'Last3Mon/71/reference/lab01-example2-index.json',
    scenarios: 'WF-01, WF-05, WF-12의 선행 조건',
  });
  f.webhook('색인 요청 수신', 'ticketmoa-index', {
    role: '관리자가 색인을 시작하는 입구다.',
    input: 'POST /webhook/ticketmoa-index, X-Team-Key 헤더. 본문은 비어 있어도 된다.',
    work: '팀 키가 맞을 때만 진행한다. 응답은 마지막 응답 노드가 보낸다.',
    output: '요청 항목 1개.',
    fail: '키가 틀리면 n8n이 거부하고 아래 노드는 실행되지 않는다.',
  });
  f.http('문서 목록 조회', { url: DATA_API + '/docs', timeout: 5000, auth: 'data' }, {
    role: '색인할 문서 이름을 데이터 API에서 읽는다.',
    input: '없음.',
    work: 'GET /docs. 운영에서는 data-api의 docs 폴더에 knowledge/*.md가 올라가 있어야 한다.',
    output: '{statusCode, body:{docs:[{name,title}]}}.',
    fail: 'timeout·연결 실패는 오류 출력으로 다음 노드에 넘겨 색인을 멈춘다. 기존 색인은 지우지 않는다.',
  });
  f.code('문서 이름 펼치기', READ_HTTP + js`
const r = readHttp($json);
const docs = r.ok && Array.isArray(r.body.docs) ? r.body.docs : [];
if (!docs.length) return [{ json: { fatal: 'doc_list_unavailable', status: r.status } }];
return docs.map(d => ({ json: { name: d.name } }));`, {
    role: '문서 목록을 문서 하나당 항목 하나로 펼친다.',
    input: '문서 목록 조회 응답.',
    work: '응답이 정상이고 문서가 있을 때만 펼친다.',
    output: '{name} 항목 여러 개. 실패하면 {fatal} 항목 1개.',
    fail: '목록이 없으면 fatal 표시를 달아 다음 분기에서 색인을 중단한다.',
  });
  f.iff('목록 정상?', '={{ !$json.fatal }}', {
    role: '문서 목록을 읽었는지 확인한다.',
    input: '{name} 또는 {fatal}.',
    work: 'fatal이 없으면 위쪽(참) 출력으로 간다.',
    output: '참: 문서 본문 조회. 거짓: 색인 실패 응답.',
  });
  f.http('문서 본문 조회', { url: '=' + DATA_API + '/docs/{{ encodeURIComponent($json.name) }}', timeout: 5000, auth: 'data' }, {
    role: '문서 본문을 하나씩 읽는다.',
    input: '{name}.',
    work: 'GET /docs/<name>을 문서 수만큼 실행한다.',
    output: '{statusCode, body:{name,title,text}}.',
    fail: '실패한 문서는 품질 검사에서 issues에 적고 색인에서 뺀다.',
  });
  f.code('문서 품질 검사', READ_HTTP + js`
const PHONE = /01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}/;
const EMAIL = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/;
const issues = [];
const chunks = [];
const usedDocs = new Set();
const inputs = $input.all();
inputs.forEach((item, i) => {
  const r = readHttp(item.json);
  const name = (r.body && r.body.name) || ('#' + i);
  if (!r.ok || typeof r.body.text !== 'string') { issues.push({ doc: name, issue: 'read_failed' }); return; }
  const text = r.body.text;
  const access = (text.match(/access_level:\s*(all|staff)\b/) || [])[1];
  if (!access) { issues.push({ doc: name, issue: 'missing_access_level' }); return; }
  if (PHONE.test(text) || EMAIL.test(text)) { issues.push({ doc: name, issue: 'contains_contact' }); return; }
  const first = text.indexOf('\n## ');
  if (first < 0) { issues.push({ doc: name, issue: 'no_sections' }); return; }
  const sections = text.slice(first + 1).split(/\n(?=## )/).map(s => s.trim());
  if (sections.length < 3) { issues.push({ doc: name, issue: 'too_few_sections' }); return; }
  if (sections.some(s => s.split('\n').slice(1).join('').trim() === '')) { issues.push({ doc: name, issue: 'empty_section' }); return; }
  usedDocs.add(name);
  for (const s of sections) {
    const section = s.split('\n')[0].replace(/^##\s*/, '').trim();
    chunks.push({ doc: name, title: r.body.title || name, section, access_level: access, text: (r.body.title || name) + '\n' + s });
  }
});
const lengths = chunks.map(c => c.text.length).sort((a, b) => a - b);
const report = {
  documents: usedDocs.size,
  chunks: chunks.length,
  by_access: { all: chunks.filter(c => c.access_level === 'all').length, staff: chunks.filter(c => c.access_level === 'staff').length },
  chunk_lengths: lengths.length ? { min: lengths[0], median: lengths[Math.floor(lengths.length / 2)], max: lengths[lengths.length - 1] } : null,
  issues,
};
if (!chunks.length) return [{ json: { no_chunks: true, error: 'no_valid_documents', report } }];
// 권한별 저장소 하나가 비면 그쪽 저장 노드가 실행되지 않아 이전 내용이 남는다. 일부만 바뀌는 일을 막기 위해 색인을 멈춘다.
if (!report.by_access.all || !report.by_access.staff) return [{ json: { no_chunks: true, error: 'access_group_empty', report } }];
return chunks.map(c => ({ json: { ...c, report } }));`, {
    role: '색인 전에 문서를 검사하고 절 단위 청크로 나눈다.',
    input: '문서 본문 조회 응답 전체.',
    work: 'access_level 줄이 없으면 색인하지 않는다(권한을 모르는 문서를 공개 저장소에 넣지 않기 위해서다). 연락처 형식, 절 3개 미만, 빈 절도 제외하고 사유를 남긴다. 문서 머리말은 청크에서 뺀다.',
    output: '{doc, section, access_level, text, report} 항목 여러 개.',
    fail: '통과한 문서가 없거나 all·staff 중 한쪽 청크가 0개면 {no_chunks, error}를 내보내 저장소를 건드리지 않는다. 스태프 문서를 정말 없앨 때는 n8n을 재시작해 메모리를 비운 뒤 정책을 고쳐야 한다.',
  });
  f.iff('청크 있음?', '={{ !$json.no_chunks }}', {
    role: '저장할 청크가 있는지 확인한다.',
    input: '청크 또는 {no_chunks}.',
    work: '없으면 저장소를 비우는 일이 생기지 않도록 여기서 갈라진다.',
    output: '참: 권한 분기. 거짓: 색인 실패 응답.',
  });
  f.iff('스태프 문서?', "={{ $json.access_level === 'staff' }}", {
    role: '청크를 권한별 저장소로 나눈다. 권한 필터를 검색 전에 거는 핵심 지점이다.',
    input: '청크 항목.',
    work: "access_level이 'staff'면 위쪽, 그 밖에는 아래쪽으로 보낸다.",
    output: '참: 스태프 저장소. 거짓: 일반 저장소.',
  });
  const store = (name, key, emb, loader) => {
    f.add(name, '@n8n/n8n-nodes-langchain.vectorStoreInMemory', 1.3,
      { mode: 'insert', memoryKey: { __rl: true, mode: 'list', value: key, cachedResultName: key }, clearStore: true }, {
        role: '청크를 메모리 키 ' + key + ' 저장소에 다시 채운다.',
        input: '같은 권한의 청크 항목들과 임베딩·로더 보조 노드.',
        work: '기존 내용을 지운 뒤(clearStore) 새로 넣는다. n8n이 재시작되면 이 저장소는 비므로 색인을 다시 실행해야 한다.',
        output: '저장된 항목.',
        fail: '임베딩 API가 멈추면 오류 출력으로 색인 요약에 가서 ok:false로 답한다. 이때 저장소가 비어 있을 수 있으므로 검색은 indexed:false 또는 search_failed로 드러나고 본체가 알림을 보낸다.',
      }, { onError: 'continueErrorOutput' });
    f.add(emb, '@n8n/n8n-nodes-langchain.embeddingsOpenAi', 1.2, { model: 'text-embedding-3-large', options: {} }, {
      role: name + '에 쓰는 임베딩 모델이다.',
      work: 'text-embedding-3-large로 청크를 벡터로 바꾼다. 키는 Credential OpenAI에만 있다.',
    }, { credentials: { openAiApi: { id: 'ticketmoaOpenAi01', name: 'OpenAI' } } });
    f.add(loader, '@n8n/n8n-nodes-langchain.documentDefaultDataLoader', 1.1, {
      jsonMode: 'expressionData', jsonData: '={{ $json.text }}', textSplittingMode: 'simple',
      options: { metadata: { metadataValues: [
        { name: 'doc', value: '={{ $json.doc }}' },
        { name: 'section', value: '={{ $json.section }}' },
        { name: 'access_level', value: '={{ $json.access_level }}' },
      ] } },
    }, {
      role: name + '에 넣을 문서 형태를 만든다.',
      work: 'text를 본문으로, doc·section·access_level을 메타데이터로 붙인다. sources 칸이 이 메타데이터에서 나온다.',
    });
    f.link(emb, name, 0, 0, 'ai_embedding');
    f.link(loader, name, 0, 0, 'ai_document');
  };
  store('일반 문서 저장', 'ticketmoa_kb_v1_all', '일반 저장 임베딩', '일반 문서 로더');
  store('스태프 문서 저장', 'ticketmoa_kb_v1_staff', '스태프 저장 임베딩', '스태프 문서 로더');
  f.merge('저장 완료 모으기', {
    role: '두 저장소 저장이 끝나기를 기다린다.',
    input: '일반 문서 저장, 스태프 문서 저장.',
    work: '두 갈래 출력을 이어 붙인다. n8n v1 실행 순서에서는 차례로 실행된다.',
    output: '저장된 항목 전체.',
  });
  f.code('색인 요약', js`
const failed = $input.all().some(i => i.json.error);
const report = $('문서 품질 검사').first().json.report;
if (failed) return [{ json: { ok: false, error: 'embedding_failed', ...report } }];
return [{ json: { ok: true, ...report, indexed_at: new Date().toISOString() } }];`, {
    role: '색인 결과를 숫자로 정리한다. RAG 설계서에 옮길 값이다.',
    input: '저장 완료 신호 또는 저장 오류, 문서 품질 검사의 report.',
    work: '저장이 한 갈래라도 실패하면 ok:false다. 하위 웹훅 규칙대로 HTTP 200으로 답한다.',
    output: '{ok, documents, chunks, by_access, chunk_lengths, issues, indexed_at} 또는 {ok:false, error:"embedding_failed"}.',
  });
  f.respond('색인 결과 응답', '={{ $json }}', { role: '색인 결과를 호출자에게 돌려준다.', input: '색인 요약.', output: 'HTTP 200 JSON.' });
  f.code('색인 실패 정리', js`
const j = $json;
return [{ json: { ok: false, error: j.fatal || j.error || 'no_valid_documents', report: j.report || null } }];`, {
    role: '색인을 하지 못한 이유를 정리한다.',
    input: '{fatal} 또는 {no_chunks, report}.',
    work: '이 경로에서는 저장소를 건드리지 않아 이전 색인이 그대로 남는다.',
    output: '{ok:false, error, report}.',
  });
  f.respond('색인 실패 응답', '={{ $json }}', { role: '실패도 HTTP 200 + error로 돌려준다 (하위 웹훅 공통 규칙).', input: '색인 실패 정리.', output: 'HTTP 200 JSON.' });

  f.link('색인 요청 수신', '문서 목록 조회');
  f.both('문서 목록 조회', '문서 이름 펼치기');
  f.link('문서 이름 펼치기', '목록 정상?');
  f.link('목록 정상?', '문서 본문 조회', 0);
  f.link('목록 정상?', '색인 실패 정리', 1);
  f.both('문서 본문 조회', '문서 품질 검사');
  f.link('문서 품질 검사', '청크 있음?');
  f.link('청크 있음?', '스태프 문서?', 0);
  f.link('청크 있음?', '색인 실패 정리', 1);
  f.link('스태프 문서?', '스태프 문서 저장', 0);
  f.link('스태프 문서?', '일반 문서 저장', 1);
  f.both('일반 문서 저장', '저장 완료 모으기', 0);
  f.both('스태프 문서 저장', '저장 완료 모으기', 1);
  f.link('저장 완료 모으기', '색인 요약');
  f.link('색인 요약', '색인 결과 응답');
  f.link('색인 실패 정리', '색인 실패 응답');
  return f;
}

export function buildSearch() {
  const f = new Flow({
    file: 'ticketmoa-search', name: 'ticketmoa-search', id: 'ticketmoaSearch01', owner: 'C RAG (정예진)',
    purpose: '사용자 권한에 맞는 저장소만 검색하고, 점수 기준을 넘는 근거만 돌려준다.',
    reference: 'Last3Mon/71/reference/lab01-example2-search.json',
    scenarios: 'WF-01, WF-03, WF-05, WF-12, TM-01, TM-05, TM-06, TM-07',
  });
  f.webhook('검색 요청 수신', 'ticketmoa-search', {
    role: '내부 검색 요청을 받는다.',
    input: '{query, access_level, top_k, scope}. access_level은 본체가 사용자 조회로 정한 값이다.',
    work: '팀 키가 있어야 호출할 수 있다. 그래야 access_level을 위조해 스태프 문서를 검색하지 못한다.',
    output: '요청 항목 1개.',
  });
  f.code('검색 준비', lib('memoryKeysFor') + js`
const b = $input.first().json.body || {};
const access_level = b.access_level === 'staff' ? 'staff' : 'all';
const keys = memoryKeysFor({ access_level });
return [{ json: {
  query: String(b.query || '').trim().slice(0, 700),
  access_level,
  keys,
  search_staff: keys.includes('ticketmoa_kb_v1_staff'),
  top_k: Math.min(Math.max(Number(b.top_k) || 3, 1), 8),
  scope: Array.isArray(b.scope) ? b.scope.map(String) : [],
} }];`, {
    role: '권한으로 검색할 메모리 키를 정한다. 검색 전 필터다.',
    input: '요청 본문.',
    work: 'memoryKeysFor를 그대로 쓴다. staff가 아니면 무조건 all이고, 스태프 저장소 검색 플래그는 거짓이다.',
    output: '{query, access_level, keys, search_staff, top_k, scope}.',
  });
  f.iff('질문 있음?', '={{ $json.query.length > 0 }}', {
    role: '빈 검색어로 임베딩을 호출하지 않게 막는다.',
    input: '검색 준비 결과.',
    output: '참: 일반 저장소 검색. 거짓: 검색 없이 빈 결과.',
  });
  const vector = (name, key, prompt, emb) => {
    f.add(name, '@n8n/n8n-nodes-langchain.vectorStoreInMemory', 1.3, {
      mode: 'load', memoryKey: { __rl: true, mode: 'list', value: key, cachedResultName: key },
      prompt, topK: 8, includeDocumentMetadata: true,
    }, {
      role: key + ' 저장소에서 질문과 비슷한 청크를 찾는다.',
      input: 'query.',
      work: '범위 필터와 점수 기준으로 줄어들 것을 고려해 넉넉히 8개를 가져온다.',
      output: '{document:{pageContent, metadata}, score} 항목 여러 개. 결과가 없어도 빈 항목 하나를 내보낸다 (alwaysOutputData).',
      fail: '임베딩 실패는 오류 출력으로 넘긴다. 검색 실패로 표시되어 본체가 이관한다.',
    }, { onError: 'continueErrorOutput', alwaysOutputData: true });
    f.add(emb, '@n8n/n8n-nodes-langchain.embeddingsOpenAi', 1.2, { model: 'text-embedding-3-large', options: {} }, {
      role: name + '에 쓰는 임베딩 모델이다.',
      work: '색인 때와 같은 text-embedding-3-large로 질문을 벡터로 바꾼다.',
    }, { credentials: { openAiApi: { id: 'ticketmoaOpenAi01', name: 'OpenAI' } } });
    f.link(emb, name, 0, 0, 'ai_embedding');
  };
  vector('일반 저장소 검색', 'ticketmoa_kb_v1_all', '={{ $json.query }}', '일반 검색 임베딩');
  vector('스태프 저장소 검색', 'ticketmoa_kb_v1_staff', "={{ $('검색 준비').first().json.query }}", '스태프 검색 임베딩');
  const readDocs = js`
const items = $input.all();
const failed = items.some(i => i.json.error);
const raw = items.filter(i => i.json.document).map(i => ({
  doc: i.json.document.metadata?.doc,
  section: i.json.document.metadata?.section,
  score: Math.round((i.json.score ?? 0) * 1000) / 1000,
  text: i.json.document.pageContent ?? '',
}));
return [{ json: { failed, raw } }];`;
  f.code('일반 결과 정리', readDocs, {
    role: '일반 저장소 결과를 한 항목으로 모은다.',
    input: '일반 저장소 검색의 성공 또는 오류 출력.',
    work: '문서가 있는 항목만 남겨 {doc, section, score, text}로 바꾼다. 메타데이터의 access_level은 내보내지 않는다.',
    output: '{failed, raw:[...]}.',
  });
  f.iff('스태프 권한?', "={{ $('검색 준비').first().json.search_staff }}", {
    role: 'staff 사용자에게만 스태프 저장소 검색을 허용한다.',
    input: '검색 준비의 search_staff.',
    output: '참: 스태프 저장소 검색. 거짓: 바로 결과 조립.',
    work: '일반 고객은 이 분기에서 스태프 저장소에 아예 닿지 않는다 (WF-05).',
  });
  f.code('스태프 결과 정리', readDocs, {
    role: '스태프 저장소 결과를 한 항목으로 모은다.',
    input: '스태프 저장소 검색의 성공 또는 오류 출력.',
    output: '{failed, raw:[...]}.',
  });
  f.code('검색 결과 조립', js`
const SCORE_MIN = 0.42; // 실측(2026-11-02, text-embedding-3-large): 관련 질문 top 0.47~0.68, 무관 질문(제휴 카드 포인트) 0.38. 둘 사이에 둔다.
const p = $('검색 준비').first().json;
const a = $('일반 결과 정리').first().json;
const s = $('스태프 결과 정리').isExecuted ? $('스태프 결과 정리').first().json : { failed: false, raw: [] };
const indexed = a.raw.length > 0;
const scope = p.scope.length ? new Set(p.search_staff ? [...p.scope, 'staff-entry-manual'] : p.scope) : null;
const seen = new Set();
const hits = [...a.raw, ...s.raw]
  .filter(h => h.doc && (!scope || scope.has(h.doc)) && h.score >= SCORE_MIN)
  .sort((x, y) => y.score - x.score)
  .filter(h => { const k = h.doc + '#' + h.section; if (seen.has(k)) return false; seen.add(k); return true; })
  .slice(0, p.top_k);
const out = { hits, top_score: hits.length ? hits[0].score : 0, indexed };
if (a.failed) out.error = 'search_failed';
else if (!indexed) out.error = 'index_unavailable';
else if (p.search_staff && s.failed) out.error = 'staff_search_failed';
if (p.search_staff) out.staff_indexed = s.raw.length > 0;
return [{ json: out }];`, {
    role: '검색 결과를 계약 모양으로 조립한다. 점수 기준이 있는 유일한 곳이다.',
    input: '일반·스태프 결과와 검색 준비.',
    work: 'kb_scope 범위, 점수 기준(SCORE_MIN), 중복(문서+절)을 차례로 거른 뒤 top_k만 남긴다. 저장소 결과가 0건이면 색인 안 됨으로 구분한다. 점수 미달은 hits가 비어도 indexed:true다.',
    output: '{hits:[{doc,section,score,text}], top_score, indexed, staff_indexed?, error?}.',
    fail: '임베딩 실패는 search_failed, 빈 저장소는 index_unavailable이고 hits가 비어 본체가 이관한다. 스태프 저장소만 실패하면 일반 근거는 돌려주되 staff_search_failed로 표시한다. 본체는 셋 모두 담당자에게 알린다.',
  });
  f.code('빈 질문 결과', js`return [{ json: { hits: [], top_score: 0, indexed: null, error: 'empty_query' } }];`, {
    role: '검색어가 없을 때의 정해진 결과다.',
    output: '{hits:[], error:"empty_query"}.',
  });
  f.respond('검색 결과 응답', '={{ $json }}', { role: '검색 결과를 호출자에게 돌려준다.', input: '검색 결과 조립 또는 빈 질문 결과.', output: 'HTTP 200 JSON. 오류여도 200이다.' });

  f.chain('검색 요청 수신', '검색 준비', '질문 있음?');
  f.link('질문 있음?', '일반 저장소 검색', 0);
  f.link('질문 있음?', '빈 질문 결과', 1);
  f.both('일반 저장소 검색', '일반 결과 정리');
  f.link('일반 결과 정리', '스태프 권한?');
  f.link('스태프 권한?', '스태프 저장소 검색', 0);
  f.link('스태프 권한?', '검색 결과 조립', 1);
  f.both('스태프 저장소 검색', '스태프 결과 정리');
  f.link('스태프 결과 정리', '검색 결과 조립');
  f.link('검색 결과 조립', '검색 결과 응답');
  f.link('빈 질문 결과', '검색 결과 응답');
  return f;
}

export function buildPayment() {
  const f = new Flow({
    file: 'ticketmoa-payment', name: 'ticketmoa-payment', id: 'ticketmoaPayment1', owner: 'D 연동·안정성 (심환석)',
    purpose: '본인 건만 조회해 연락처를 가린 기록을 돌려준다. 결제 취소나 변경은 하지 않는다.',
    reference: 'Last3Mon/73/reference/lab02-example1-own.json',
    scenarios: 'WF-06, WF-07, WF-11, WF-12, TM-02, TM-03',
  });
  f.webhook('조회 요청 수신', 'ticketmoa-payment', {
    role: '내부 기록 조회 요청을 받는다.',
    input: '{request_id, user, record_id, deadline_ms}. user는 본체가 검증한 값이다.',
    work: '팀 키가 있어야 호출할 수 있다. 질문 글이 아니라 user로 권한을 판단한다.',
    output: '요청 항목 1개.',
  });
  f.code('조회 준비', js`
const b = $input.first().json.body || {};
const record_id = String(b.record_id || '').toUpperCase();
const deadline_ms = Number(b.deadline_ms) || Date.now() + 3000;
return [{ json: { request_id: b.request_id || '', user: String(b.user || ''), record_id, deadline_ms, try_no: 1, valid: /^C-\d{4}$/.test(record_id) && !!b.user } }];`, {
    role: '입력을 정리하고 재시도 상태를 시작한다.',
    input: '요청 본문.',
    work: '문의번호 형식(C-0000)만 URL에 넣는다. 다른 값은 조회하지 않는다.',
    output: '{request_id, user, record_id, deadline_ms, try_no:1, valid}.',
  });
  f.iff('형식 정상?', '={{ $json.valid }}', {
    role: '형식이 틀린 번호로 API를 부르지 않게 막는다.',
    input: '조회 준비 결과.',
    output: '참: 조회 시도. 거짓: 없는 건으로 응답.',
  });
  f.code('조회 시도 상태', js`return [{ json: $json }];`, {
    role: '재시도 루프의 시작점이다. 이번 시도의 상태를 고정한다.',
    input: '조회 준비 결과 또는 재시도 대기 결과.',
    work: '조회 판정이 이 노드의 값을 읽어 몇 번째 시도인지 안다.',
    output: '입력과 같다.',
  });
  f.http('본인 건 조회', {
    url: "=" + DATA_API + "/tickets/{{ encodeURIComponent($json.record_id) }}?requester={{ encodeURIComponent($json.user) }}",
    timeout: '={{ Math.max(300, Math.min(2500, $json.deadline_ms - Date.now() - 200)) }}', auth: 'data',
  }, {
    role: '데이터 API로 기록을 조회한다.',
    input: '{record_id, user, deadline_ms}.',
    work: 'GET /tickets/<id>?requester=<user>. timeout은 2.5초와 남은 시간 중 짧은 쪽이다 (WF-11).',
    output: '{statusCode, body}. 403·404도 정상 출력으로 받아 다음 노드에서 판단한다.',
    fail: 'timeout·연결 실패는 오류 출력으로 조회 판정에 간다.',
  });
  f.code('조회 판정', READ_HTTP + lib('shouldRetry', 'backoffMs', 'maskPII', 'maskDeep') + js`
const st = $('조회 시도 상태').last().json;
const r = readHttp($json);
if (r.status === 200) {
  if (r.body.requester !== st.user) return [{ json: { ...st, outcome: 'done', result: { status: 'forbidden', record: null, forbidden: true, masked: 0 } } }];
  const m = maskDeep(r.body);
  return [{ json: { ...st, outcome: 'done', result: { status: 'ok', record: m.value, forbidden: false, masked: m.masked } } }];
}
if (r.status === 403) return [{ json: { ...st, outcome: 'done', result: { status: 'forbidden', record: null, forbidden: true, masked: 0 } } }];
if (r.status === 404) return [{ json: { ...st, outcome: 'done', result: { status: 'not_found', record: null, forbidden: false, masked: 0 } } }];
const remaining = st.deadline_ms - Date.now();
const wait = backoffMs(st.try_no);
const nextTry = r.status === null ? 2500 : 500; // 다음 시도에 필요한 시간
if (st.try_no < 3 && shouldRetry(r.status, r.errorCode) && remaining > wait + nextTry) {
  return [{ json: { ...st, outcome: 'retry', wait_ms: wait } }];
}
const reason = r.status === 401 ? 'auth_failed' : (r.status === null ? 'timeout_or_network' : 'http_' + r.status);
return [{ json: { ...st, outcome: 'done', result: { status: 'error', record: null, forbidden: false, masked: 0, error: reason } } }];`, {
    role: '조회 결과의 의미를 정하고 재시도 여부를 판단한다.',
    input: '본인 건 조회 응답 또는 오류, 조회 시도 상태.',
    work: '200이면 주인을 한 번 더 확인하고 maskDeep으로 연락처를 가린다. 403은 권한 없음, 404는 없는 건이다. 429·5xx·timeout만 최대 2회 재시도하되, 남은 시간이 다음 시도 시간보다 적으면 포기한다. 401은 재시도하지 않는다.',
    output: '{outcome:"done", result} 또는 {outcome:"retry", wait_ms}.',
    fail: '재시도를 다 쓰면 status:"error"로 끝낸다. 본체가 이관한다.',
  });
  f.switchOn('재시도할까?', '={{ $json.outcome }}', ['retry', 'done'], {
    role: '재시도 루프와 종료를 가른다.',
    input: '조회 판정 결과.',
    output: 'retry: 재시도 대기. done: 조회 응답 조립. 예상 밖 값도 조회 응답 조립으로 보낸다.',
  });
  f.code('재시도 대기', js`
const j = $json;
await new Promise(resolve => setTimeout(resolve, j.wait_ms));
const { outcome, wait_ms, ...state } = j;
return [{ json: { ...state, try_no: j.try_no + 1 } }];`, {
    role: '다음 시도 전에 기다린다.',
    input: '{wait_ms, try_no}.',
    work: 'backoffMs가 정한 시간(0.5초, 1초)만 기다린 뒤 시도 번호를 올린다. wait 노드가 reference에 없어 Code에서 기다린다.',
    output: '조회 시도 상태로 돌아간다.',
  });
  f.code('조회 응답 조립', js`
const j = $json;
const result = j.result || { status: 'error', record: null, forbidden: false, masked: 0, error: 'unexpected_outcome' };
return [{ json: { request_id: j.request_id, ...result } }];`, {
    role: '하위 웹훅 계약 모양으로 응답을 만든다.',
    input: '조회 판정 결과.',
    output: '{request_id, status, record(가림), forbidden, masked, error?}.',
  });
  f.code('없는 건 결과', js`return [{ json: { request_id: $json.request_id, status: 'not_found', record: null, forbidden: false, masked: 0 } }];`, {
    role: '형식이 틀린 번호를 없는 건으로 돌려준다.',
    input: '조회 준비 결과.',
    output: '{status:"not_found"}.',
  });
  f.respond('조회 결과 응답', '={{ $json }}', { role: '조회 결과를 돌려준다.', input: '조회 응답 조립 또는 없는 건 결과.', output: 'HTTP 200 JSON. 실패여도 200이다.' });

  f.chain('조회 요청 수신', '조회 준비', '형식 정상?');
  f.link('형식 정상?', '조회 시도 상태', 0);
  f.link('형식 정상?', '없는 건 결과', 1);
  f.link('조회 시도 상태', '본인 건 조회');
  f.both('본인 건 조회', '조회 판정');
  f.link('조회 판정', '재시도할까?');
  f.link('재시도할까?', '재시도 대기', 0);
  f.link('재시도할까?', '조회 응답 조립', 1);
  f.link('재시도할까?', '조회 응답 조립', 2);
  f.link('재시도 대기', '조회 시도 상태');
  f.link('조회 응답 조립', '조회 결과 응답');
  f.link('없는 건 결과', '조회 결과 응답');
  return f;
}

export function buildHandoff() {
  const f = new Flow({
    file: 'ticketmoa-handoff', name: 'ticketmoa-handoff', id: 'ticketmoaHandoff1', owner: 'D 연동·안정성 (심환석)',
    purpose: '가린 요약으로 상담 티켓을 만든다. 재시도, DLQ, 알림을 맡는 유일한 부작용 소유자다.',
    reference: 'Last3Mon/76/reference/lab02-example1-dlq.json',
    scenarios: 'WF-02b, WF-03, WF-04, WF-09, WF-10, WF-11, WF-12, TM-03, TM-05, TM-06, TM-08',
  });
  f.webhook('이관 요청 수신', 'ticketmoa-handoff', {
    role: '내부 이관 요청을 받는다.',
    input: '{request_id, user, summary, category, priority, alert, deadline_ms}.',
    work: '팀 키가 있어야 호출할 수 있다. 없으면 누구나 티켓을 만들 수 있기 때문이다.',
    output: '요청 항목 1개.',
  });
  f.code('티켓 내용 조립', lib('maskPII', 'maskDeep') + js`
const b = $input.first().json.body || {};
const summary = maskPII(String(b.summary || ''));
const alert = b.alert ? maskDeep(b.alert) : { value: null, masked: 0 };
const category = String(b.category || 'general');
const priority = b.priority === 'high' ? 'high' : 'normal';
// 데이터 API는 title, requester, category, priority만 저장한다. 요약을 잃지 않도록 title에 담는다.
const title = ('[' + category + '] ' + summary.text).replace(/\s+/g, ' ').slice(0, 500);
return [{ json: {
  request_id: String(b.request_id || ''), user: String(b.user || ''), title, summary: summary.text, category, priority,
  alert: alert.value, masked: summary.masked + alert.masked,
  deadline_ms: Number(b.deadline_ms) || Date.now() + 5000, try_no: 1,
} }];`, {
    role: '티켓 본문을 만들고 연락처를 가린다.',
    input: '요청 본문.',
    work: 'maskPII로 요약을, maskDeep으로 알림을 가린다. 데이터 API가 summary 칸을 버리므로 요약을 title에도 넣는다. 질문 원문이 그대로 나가지 않는다.',
    output: '{request_id, user, title, summary, category, priority, alert, masked, deadline_ms, try_no:1}.',
  });
  f.code('티켓 시도 상태', js`return [{ json: $json }];`, {
    role: '재시도 루프의 시작점이다.',
    input: '티켓 내용 조립 또는 티켓 재시도 대기.',
    work: '티켓 판정이 이 값으로 시도 번호를 읽는다.',
    output: '입력과 같다.',
  });
  f.iff('시간 남음?', '={{ $json.deadline_ms - Date.now() > 300 }}', {
    role: '시간 예산이 없으면 느린 API를 새로 부르지 않는다.',
    input: '티켓 시도 상태.',
    work: 'WF-11처럼 조회에서 시간을 다 쓴 경우 응답을 늦추지 않기 위한 문이다.',
    output: '참: 티켓 생성. 거짓: 시간 초과 처리.',
  });
  f.http('티켓 생성', {
    method: 'POST', url: DATA_API + '/tickets',
    body: '={{ JSON.stringify({ key: $json.request_id, title: $json.title, requester: $json.user, category: $json.category, priority: $json.priority, summary: $json.summary }) }}',
    timeout: '={{ Math.max(200, Math.min(5000, $json.deadline_ms - Date.now() - 200)) }}', auth: 'data',
  }, {
    role: '상담 티켓을 만든다.',
    input: '{request_id, title, user, category, priority, summary}.',
    work: 'POST /tickets. key에 request_id를 넣어 같은 요청이 와도 티켓이 1건만 생긴다.',
    output: '{statusCode, body:{ticket_id, duplicate}}.',
    fail: '500·timeout은 티켓 판정이 재시도를 정한다. timeout 뒤에도 서버가 티켓을 만들 수 있으나 같은 key라서 수습된다.',
  });
  f.code('티켓 판정', READ_HTTP + lib('shouldRetry', 'backoffMs') + js`
const st = $('티켓 시도 상태').last().json;
const r = readHttp($json);
if (r.ok && r.body.ticket_id) {
  return [{ json: { ...st, outcome: 'ok', ticket: { id: r.body.ticket_id, key: st.request_id, category: st.category, priority: st.priority, duplicate: r.body.duplicate === true } } }];
}
const wait = backoffMs(st.try_no);
if (st.try_no < 3 && shouldRetry(r.status, r.errorCode) && st.deadline_ms - Date.now() > wait + 700) {
  return [{ json: { ...st, outcome: 'retry', wait_ms: wait } }];
}
const reason = (r.status === 401 || r.status === 403) ? 'auth_failed' : (r.status === null ? 'timeout_or_network' : 'http_' + r.status);
return [{ json: { ...st, outcome: 'fail', reason } }];`, {
    role: '티켓 결과를 판단한다.',
    input: '티켓 생성 응답 또는 오류, 티켓 시도 상태.',
    work: 'API의 ticket_id를 id로 바꾸고 요청의 priority·category를 붙인다 (WF-12가 ticket.priority를 본다). 429·5xx·timeout만 최대 2회 재시도하고 401·403은 바로 실패로 간다.',
    output: 'ok: {ticket}. retry: {wait_ms}. fail: {reason}.',
  });
  f.switchOn('티켓 결과 분기', '={{ $json.outcome }}', ['ok', 'retry', 'fail'], {
    role: '티켓 결과에 따라 길을 나눈다.',
    input: '티켓 판정 결과.',
    output: 'ok: 알림 판단. retry: 대기 후 다시. fail 또는 예상 밖: DLQ.',
  });
  f.code('티켓 재시도 대기', js`
const j = $json;
await new Promise(resolve => setTimeout(resolve, j.wait_ms));
const { outcome, wait_ms, ...state } = j;
return [{ json: { ...state, try_no: j.try_no + 1 } }];`, {
    role: '다음 시도 전에 기다린다.',
    input: '{wait_ms, try_no}.',
    output: '티켓 시도 상태로 돌아간다.',
    work: 'backoffMs가 정한 0.5초, 1초를 기다린다.',
  });
  f.code('시간 초과 처리', js`return [{ json: { ...$json, outcome: 'fail', reason: 'budget_exhausted' } }];`, {
    role: '시간이 없어 티켓을 시도하지 못한 경우를 실패로 표시한다.',
    input: '티켓 시도 상태.',
    output: '{outcome:"fail", reason:"budget_exhausted"}.',
    work: '요청을 잃지 않도록 DLQ로 보낸다.',
  });
  f.iff('중복 티켓?', '={{ $json.ticket.duplicate }}', {
    role: '이미 있던 key의 티켓이 돌아왔는지 본다.',
    input: '티켓 판정 결과.',
    work: '데이터 API는 key만 보고 기존 티켓을 돌려준다. 본체의 주인 기록이 사라진 뒤 다른 사용자가 같은 request_id를 쓰면 남의 티켓 번호를 받게 되므로 확인한다.',
    output: '참: 중복 주인 조회. 거짓: 긴급 건 판단.',
  });
  f.http('중복 주인 조회', { url: DATA_API + '/tickets-created', timeout: 800, auth: 'data' }, {
    role: '그 key의 티켓을 누가 만들었는지 읽는다.',
    input: '없음.',
    work: 'GET /tickets-created.',
    output: '{statusCode, body:{tickets}}.',
    fail: '확인하지 못하면 남의 티켓 번호를 내주지 않도록 충돌로 처리한다.',
  });
  f.code('중복 주인 판정', READ_HTTP + js`
const st = $('티켓 판정').last().json;
const r = readHttp($json);
const list = r.ok && Array.isArray(r.body.tickets) ? r.body.tickets : [];
const row = list.find(t => t.key === st.request_id && t.ticket_id === st.ticket.id);
const unverified = !r.ok || !Array.isArray(r.body.tickets) || !row;
const foreign = !unverified && row.requester !== st.user;
return [{ json: { ...st, foreign, unverified, stop: foreign || unverified, true_owner: row ? row.requester : st.user } }];`, {
    role: '돌아온 티켓이 이 사용자의 것인지 판단한다.',
    input: '중복 주인 조회 응답, 티켓 판정.',
    work: '확인하지 못한 경우(unverified)와 남의 티켓(foreign)을 구분한다. 둘 다 번호를 내주지 않는다.',
    output: '{foreign, unverified, stop, true_owner, ticket, ...}.',
  });
  f.iff('남의 티켓?', '={{ $json.stop }}', {
    role: '남의 티켓이거나 확인할 수 없으면 번호를 내주지 않는다.',
    input: 'stop.',
    output: '참: 소유 기록 복구. 거짓: 긴급 건 판단.',
  });
  f.http('소유 기록 복구', {
    method: 'POST', url: "=" + DATA_API + "/cache/{{ encodeURIComponent('req:' + $json.request_id) }}",
    body: '={{ JSON.stringify({ value: { owner: $json.true_owner, fp: null }, ttl: 86400 }) }}', timeout: 500, auth: 'data',
  }, {
    role: '본체의 사전 확인을 지나쳐 적힌 주인 기록을 실제 티켓 주인으로 되돌린다.',
    input: '{request_id, true_owner}.',
    work: 'POST /cache. 본체의 티켓 주인 조회가 실패했거나 동시에 들어온 요청이면 여기까지 온다. 거절된 요청이 주인 자리를 차지하면 진짜 주인의 재전송이 충돌로 막힌다. 질문 지문은 알 수 없어 null로 둔다.',
    output: '{statusCode, body}.',
    fail: '실패하면 다음 재전송이 충돌로 거절될 수 있으나 티켓은 노출되지 않는다.',
  });
  f.iff('긴급 건?', '={{ !!$json.alert }}', {
    role: '긴급 알림이 필요한 이관인지 본다.',
    input: '티켓 판정 결과.',
    output: '참: 긴급 이력 조회. 거짓: 결과 조립.',
  });
  f.http('긴급 이력 조회', {
    url: "=" + DATA_API + "/cache/{{ encodeURIComponent('urgent-alerted:' + $json.request_id) }}", timeout: 500, auth: 'data',
  }, {
    role: '이 요청의 긴급 알림이 이미 성공했는지 확인한다.',
    input: 'request_id.',
    work: '티켓의 duplicate만 보면 첫 알림이 실패한 경우 알림이 영영 나가지 않는다. 그래서 알림 성공 기록을 따로 본다.',
    output: '{statusCode, body}. 처음이면 404.',
    fail: '읽지 못하면 보낸다. 빠지는 것보다 중복이 낫다.',
  });
  f.iff('긴급 알림 필요?', '={{ $json.statusCode !== 200 }}', {
    role: '긴급 알림을 성공할 때까지 요청당 한 번만 보낸다.',
    input: '긴급 이력 조회 응답.',
    output: '참: 긴급 알림. 거짓: 결과 조립.',
  });
  f.http('긴급 알림', {
    method: 'POST', url: DATA_API + '/alerts',
    body: "={{ JSON.stringify({ ...$('티켓 판정').last().json.alert, workflow: 'ticketmoa-handoff', node: '긴급 알림', severity: 'high', reason: 'urgent_handoff', request_id: $('티켓 판정').last().json.request_id, ticket_id: $('티켓 판정').last().json.ticket.id }) }}",
    timeout: 800, auth: 'data',
  }, {
    role: '현장 스태프 채널에 긴급 알림을 보낸다.',
    input: '{alert, request_id, ticket}.',
    work: 'POST /alerts. 예매번호는 앞에서 가려져 있다. 공연명·좌석 등급과 티켓 번호를 전한다.',
    output: '{stored, count}.',
    fail: '알림이 실패해도 고객 응답은 막지 않는다. 결과의 alert 칸이 false가 된다.',
  });
  f.iff('긴급 알림 성공?', '={{ $json.statusCode >= 200 && $json.statusCode < 300 }}', {
    role: '알림이 실제로 저장됐을 때만 이력을 남긴다.',
    input: '긴급 알림 응답.',
    work: 'HTTP 500도 정상 출력으로 오므로 상태 코드를 본다. 실패를 성공으로 기록하면 복구 뒤에도 알림이 나가지 않는다.',
    output: '참: 긴급 이력 저장. 거짓: 결과 조립.',
  });
  f.iff('장애 알림 성공?', '={{ $json.statusCode >= 200 && $json.statusCode < 300 }}', {
    role: '알림이 실제로 저장됐을 때만 이력을 남긴다.',
    input: '장애 알림 응답.',
    output: '참: 알림 이력 저장. 거짓: 결과 조립.',
  });
  f.http('긴급 이력 저장', {
    method: 'POST', url: "=" + DATA_API + "/cache/{{ encodeURIComponent('urgent-alerted:' + $('티켓 판정').last().json.request_id) }}",
    body: '={{ JSON.stringify({ value: true, ttl: 3600 }) }}', timeout: 500, auth: 'data',
  }, {
    role: '긴급 알림이 성공했다고 기록한다.',
    input: 'request_id.',
    work: 'POST /cache, 1시간 유지.',
    output: '{statusCode, body}.',
    fail: '실패하면 재전송 때 알림이 한 번 더 갈 수 있다.',
  });
  f.http('DLQ 저장', {
    method: 'POST', url: DATA_API + '/dlq',
    body: "={{ JSON.stringify({ item: { id: $json.request_id, title: $json.title, requester: $json.user, category: $json.category, priority: $json.priority, summary: $json.summary }, reason: $json.reason, workflow: 'ticketmoa-handoff' }) }}",
    timeout: 800, auth: 'data',
  }, {
    role: '티켓을 만들지 못한 요청을 실패 대기열에 보관한다.',
    input: '{request_id, title, summary, category, priority, reason}.',
    work: 'POST /dlq. item.id를 request_id로 두어 같은 요청은 attempts만 늘어난다. 재처리 때 같은 key를 쓴다.',
    output: '{stored, size}.',
    fail: 'DLQ도 실패하면 결과의 dlq 칸이 false가 된다. 저장했다고 거짓으로 말하지 않는다.',
  });
  f.http('알림 이력 조회', {
    url: "=" + DATA_API + "/cache/{{ encodeURIComponent('alerted:' + $('티켓 내용 조립').first().json.request_id) }}", timeout: 500, auth: 'data',
  }, {
    role: '같은 요청의 장애 알림을 이미 보냈는지 확인한다.',
    input: 'request_id.',
    work: 'GET /cache/alerted:<id>. 호출자가 같은 요청을 다시 보내면 DLQ는 attempts만 늘지만 알림은 그대로 쌓이기 때문이다 (WF-04 알림 1건).',
    output: '{statusCode, body}. 처음이면 404.',
    fail: '읽지 못하면 처음으로 본다. 알림이 빠지는 것보다 중복이 낫다.',
  });
  f.iff('처음 실패?', '={{ $json.statusCode !== 200 }}', {
    role: '처음 실패한 요청에만 장애 알림을 보낸다.',
    input: '알림 이력 조회 응답.',
    output: '참: 장애 알림. 거짓: 결과 조립.',
    work: '오류 출력 항목에는 statusCode가 없어 처음으로 처리된다.',
  });
  f.http('장애 알림', {
    method: 'POST', url: DATA_API + '/alerts',
    body: "={{ JSON.stringify({ workflow: 'ticketmoa-handoff', node: '티켓 생성', severity: 'critical', reason: $('티켓 내용 조립').first().json.alert ? 'ticket_failed_urgent' : 'ticket_failed', request_id: $('티켓 내용 조립').first().json.request_id, channel: 'cs-oncall', urgent: $('티켓 내용 조립').first().json.alert || null }) }}",
    timeout: 800, auth: 'data',
  }, {
    role: '티켓 실패를 담당자에게 알린다.',
    input: 'request_id, 사유, (있으면) 가린 긴급 알림 내용.',
    work: 'POST /alerts 1건. 긴급 건이면 현장 알림 내용을 함께 실어 알림이 두 번 나가지 않게 한다.',
    output: '{stored, count}.',
    fail: '실패해도 고객 응답은 200으로 나간다. 이력을 남기지 않아 다음 시도가 다시 알린다.',
  });
  f.http('알림 이력 저장', {
    method: 'POST', url: "=" + DATA_API + "/cache/{{ encodeURIComponent('alerted:' + $('티켓 내용 조립').first().json.request_id) }}",
    body: '={{ JSON.stringify({ value: true, ttl: 3600 }) }}', timeout: 500, auth: 'data',
  }, {
    role: '이 요청의 장애 알림을 보냈다고 기록한다.',
    input: 'request_id.',
    work: 'POST /cache, 1시간 유지.',
    output: '{statusCode, body}.',
    fail: '실패하면 다음 시도에서 알림이 한 번 더 갈 수 있다.',
  });
  f.code('이관 결과 조립', READ_HTTP + js`
const base = $('티켓 내용 조립').first().json;
const ran = n => { try { return $(n).isExecuted; } catch (e) { return false; } };
const urgentAlready = ran('긴급 이력 조회') && !ran('긴급 알림');
const httpOk = n => { if (!ran(n)) return false; const a = $(n).all(0); return a.length > 0 && readHttp(a[0].json).ok; };
const failAlertOk = ran('장애 알림') ? httpOk('장애 알림') : ran('알림 이력 조회');
const judged = ran('티켓 판정') ? $('티켓 판정').last().json : null;
if (ran('중복 주인 판정') && $('중복 주인 판정').first().json.stop) {
  return [{ json: { request_id: base.request_id, ticket: null, duplicate: false, dlq: false, alert: false, masked: base.masked, reason: $('중복 주인 판정').first().json.foreign ? 'request_id_conflict' : 'duplicate_unverified', retries: 0 } }];
}
if (judged && judged.outcome === 'ok') {
  return [{ json: { request_id: base.request_id, ticket: judged.ticket, duplicate: judged.ticket.duplicate, dlq: false, alert: urgentAlready || httpOk('긴급 알림'), masked: base.masked, retries: judged.try_no - 1 } }];
}
const fail = ran('시간 초과 처리') ? $('시간 초과 처리').first().json : judged;
return [{ json: { request_id: base.request_id, ticket: null, duplicate: false, dlq: httpOk('DLQ 저장'), alert: failAlertOk, masked: base.masked, reason: (fail && fail.reason) || 'ticket_failed', retries: fail ? fail.try_no - 1 : 0 } }];`, {
    role: '이관 결과를 계약 모양으로 만든다.',
    input: '앞 노드들의 실행 결과.',
    work: '실제로 성공한 호출만 true로 표시한다. 오류 출력으로 끝난 호출은 false다.',
    output: '{request_id, ticket|null, duplicate, dlq, alert, masked, reason?, retries}.',
  });
  f.respond('이관 결과 응답', '={{ $json }}', { role: '이관 결과를 돌려준다.', input: '이관 결과 조립.', output: 'HTTP 200 JSON. 티켓 실패도 200이다 (WF-04).' });

  f.chain('이관 요청 수신', '티켓 내용 조립', '티켓 시도 상태', '시간 남음?');
  f.link('시간 남음?', '티켓 생성', 0);
  f.link('시간 남음?', '시간 초과 처리', 1);
  f.both('티켓 생성', '티켓 판정');
  f.link('티켓 판정', '티켓 결과 분기');
  f.link('티켓 결과 분기', '중복 티켓?', 0);
  f.link('중복 티켓?', '중복 주인 조회', 0);
  f.link('중복 티켓?', '긴급 건?', 1);
  f.both('중복 주인 조회', '중복 주인 판정');
  f.link('중복 주인 판정', '남의 티켓?');
  f.link('남의 티켓?', '소유 기록 복구', 0);
  f.both('소유 기록 복구', '이관 결과 조립');
  f.link('남의 티켓?', '긴급 건?', 1);
  f.link('티켓 결과 분기', '티켓 재시도 대기', 1);
  f.link('티켓 결과 분기', 'DLQ 저장', 2);
  f.link('티켓 결과 분기', 'DLQ 저장', 3);
  f.link('티켓 재시도 대기', '티켓 시도 상태');
  f.link('시간 초과 처리', 'DLQ 저장');
  f.link('긴급 건?', '긴급 이력 조회', 0);
  f.link('긴급 건?', '이관 결과 조립', 1);
  f.both('긴급 이력 조회', '긴급 알림 필요?');
  f.link('긴급 알림 필요?', '긴급 알림', 0);
  f.link('긴급 알림 필요?', '이관 결과 조립', 1);
  f.link('긴급 알림', '긴급 알림 성공?', 0);
  f.link('긴급 알림 성공?', '긴급 이력 저장', 0);
  f.link('긴급 알림 성공?', '이관 결과 조립', 1);
  f.link('긴급 알림', '이관 결과 조립', 1);
  f.both('긴급 이력 저장', '이관 결과 조립');
  f.both('DLQ 저장', '알림 이력 조회');
  f.both('알림 이력 조회', '처음 실패?');
  f.link('처음 실패?', '장애 알림', 0);
  f.link('처음 실패?', '이관 결과 조립', 1);
  f.link('장애 알림', '장애 알림 성공?', 0);
  f.link('장애 알림 성공?', '알림 이력 저장', 0);
  f.link('장애 알림 성공?', '이관 결과 조립', 1);
  f.link('장애 알림', '이관 결과 조립', 1);
  f.both('알림 이력 저장', '이관 결과 조립');
  f.link('이관 결과 조립', '이관 결과 응답');
  return f;
}

export function buildErrors() {
  const f = new Flow({
    file: 'ticketmoa-errors', name: 'ticketmoa-errors', id: ERROR_WORKFLOW_ID, owner: 'D 연동·안정성 (심환석)',
    purpose: '예상 밖 실행 오류를 담당자에게 알린다. 고객 응답을 대신하지 않는다. 처리된 오류(재시도, DLQ)는 여기로 오지 않는다.',
    reference: 'Last3Mon/76/reference/lab02-example2-error-handler.json',
    scenarios: 'WF-10 보조, 운영 장애',
    isErrorWorkflow: true,
  });
  f.add('오류 수신', 'n8n-nodes-base.errorTrigger', 1, {}, {
    role: '다른 워크플로우의 실행이 실패하면 시작된다.',
    input: 'n8n이 넘기는 {workflow, execution, error}.',
    work: '모든 ticketmoa 워크플로우의 settings.errorWorkflow가 이 워크플로우의 고정 ID를 가리킨다.',
    output: '오류 정보 1건.',
  });
  f.code('알림 내용 조립', js`
const e = $json;
return [{ json: {
  workflow: e.workflow?.name ?? '?',
  node: e.execution?.lastNodeExecuted ?? e.execution?.error?.node?.name ?? '?',
  execution_id: e.execution?.id ?? '',
  at: new Date().toISOString(),
  severity: 'critical',
  reason: 'unexpected',
} }];`, {
    role: '알림에 넣을 값만 고른다.',
    input: '오류 정보.',
    work: '워크플로우 이름, 노드 이름, 실행 ID, 시각만 남긴다. 오류 메시지에 질문 원문이나 연락처가 들어갈 수 있어 넣지 않는다.',
    output: '{workflow, node, execution_id, at, severity, reason}.',
  });
  f.http('장애 알림 전송', { method: 'POST', url: DATA_API + '/alerts', body: '={{ JSON.stringify($json) }}', timeout: 3000, auth: 'data' }, {
    role: '담당자에게 알린다.',
    input: '알림 내용.',
    work: 'POST /alerts.',
    output: '{stored, count}.',
    fail: '알림도 실패하면 더 할 수 있는 일이 없다. 실행 기록에만 남는다. 자기 자신을 오류 처리기로 지정하지 않아 무한 반복은 없다.',
  });
  f.chain('오류 수신', '알림 내용 조립', '장애 알림 전송');
  return f;
}

export function buildOps() {
  const f = new Flow({
    file: 'ticketmoa-ops', name: 'ticketmoa-ops', id: 'ticketmoaOps00001', owner: 'D 심환석 (가산, 필수 통과 뒤에만)',
    purpose: '오늘 이관 비율, 가장 느린 구간, DLQ 건수를 숫자로 답한다. 읽기 전용이며 숫자는 규칙으로 계산한다.',
    reference: 'Last3Mon/77/reference/lab01-example2-report.json',
    scenarios: '가산',
  });
  f.webhook('운영 질문 수신', 'ticketmoa-ops', {
    role: '운영자의 지표 요청을 받는다.',
    input: '{from?, to?}. 날짜는 YYYY-MM-DD.',
    work: '팀 키가 있어야 호출할 수 있다.',
    output: '요청 항목 1개.',
  });
  f.code('기간 정리', js`
const b = $input.first().json.body || {};
const today = new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10);
const valid = d => { if (!/^\d{4}-\d{2}-\d{2}$/.test(String(d || ''))) return false; const t = new Date(d + 'T00:00:00Z'); return !isNaN(t) && t.getUTCFullYear() >= 2000 && t.toISOString().slice(0, 10) === d; };
const from = valid(b.from) ? b.from : today;
const to = valid(b.to) && (!valid(b.from) || b.from <= b.to) ? b.to : (valid(b.from) ? from : today);
// 기록의 started_at은 UTC라서 한국 날짜 d의 기록은 UTC 날짜 d-1 또는 d에 있다. 하루 넓게 읽고 계산 때 한국 날짜로 거른다.
const query_from = new Date(new Date(from + 'T00:00:00Z').getTime() - 86400000).toISOString().slice(0, 10);
return [{ json: { from, to, query_from } }];`, {
    role: '집계 기간을 정한다.',
    input: '{from?, to?}.',
    work: '값이 없거나 실제 달력 날짜가 아니면(2000년 이전 포함) 한국 시간 오늘로 한다. 잘못된 날짜로 예외가 나지 않아 항상 200으로 답한다. to가 from보다 앞이면 from과 같게 한다.',
    output: '{from, to, query_from}.',
  });
  f.http('실행 기록 읽기', {
    url: "=" + DATA_API + "/logs?source=live&from={{ $json.query_from }}&to={{ $json.to }}", timeout: 5000, auth: 'data',
  }, { role: '기간 안의 실시간 실행 기록을 읽는다.', input: '{from, to}.', work: 'GET /logs. 질문 원문과 연락처는 기록에 없다.', output: '{logs:[...]}.', fail: '실패는 지표 계산에서 partial로 표시한다. 0으로 위장하지 않는다.' });
  f.http('생성 티켓 읽기', { url: DATA_API + '/tickets-created', timeout: 5000, auth: 'data' }, { role: '만들어진 티켓 수를 읽는다.', work: 'GET /tickets-created.', output: '{count, tickets}.', fail: '실패는 partial로 표시한다.' });
  f.http('DLQ 읽기', { url: DATA_API + '/dlq', timeout: 5000, auth: 'data' }, { role: '실패 대기열 크기를 읽는다.', work: 'GET /dlq.', output: '{size, items}.', fail: '실패는 partial로 표시한다.' });
  f.code('지표 계산', READ_HTTP + js`
const read = n => { const a = $(n).all(0); return a.length ? readHttp(a[0].json) : { ok: false, body: {} }; };
const logsR = read('실행 기록 읽기');
const ticketsR = read('생성 티켓 읽기');
const dlqR = read('DLQ 읽기');
const partial = [['logs', logsR], ['tickets', ticketsR], ['dlq', dlqR]].filter(([, r]) => !r.ok).map(([n]) => n);
const period = $('기간 정리').first().json;
const logsOk = logsR.ok && Array.isArray(logsR.body.logs);
const kstDay = v => { const t = String(v || ''); const d = new Date(/Z|[+-]\d{2}:\d{2}$/.test(t) ? t : t + '+09:00'); return isNaN(d) ? '' : new Date(d.getTime() + 9 * 3600000).toISOString().slice(0, 10); };
const logs = logsOk ? logsR.body.logs.filter(l => { const k = kstDay(l.started_at); return k >= period.from && k <= period.to; }) : [];
const byRoute = {};
for (const l of logs) byRoute[l.route] = (byRoute[l.route] || 0) + 1;
const handoff = byRoute['담당자 이관'] || 0;
const steps = {};
for (const l of logs) for (const [k, v] of Object.entries(l.timings || {})) if (typeof v === 'number' && k !== 'total_ms') (steps[k] ||= []).push(v);
const pct = (vals, p) => { const s = [...vals].sort((a, b) => a - b); return s.length ? s[Math.min(s.length - 1, Math.ceil(p * s.length) - 1)] : null; };
const stepStats = Object.fromEntries(Object.entries(steps).map(([k, v]) => [k, { p50: pct(v, 0.5), p95: pct(v, 0.95), n: v.length }]));
const slowest = Object.entries(stepStats).sort((a, b) => (b[1].p95 || 0) - (a[1].p95 || 0))[0];
const handoffRate = logs.length ? Math.round((handoff / logs.length) * 1000) / 1000 : null;
const answer = !logsOk ? '실행 기록을 읽지 못해 이관 비율을 계산하지 못했습니다.' : logs.length
  ? '전체 ' + logs.length + '건 중 이관 ' + handoff + '건(' + Math.round(handoffRate * 100) + '%)입니다. 가장 느린 구간은 ' + (slowest ? slowest[0] + ' (p95 ' + slowest[1].p95 + 'ms)' : '측정값 없음') + '이고 DLQ는 ' + (dlqR.ok ? (dlqR.body.size ?? 0) + '건' : '확인 실패') + '입니다.'
  : '기록된 실행이 없습니다.';
return [{ json: { period, total: logsOk ? logs.length : null, by_route: logsOk ? byRoute : null, handoff_rate: handoffRate, steps: stepStats, dlq_size_now: dlqR.ok ? (dlqR.body.size ?? 0) : null, tickets_created_now: ticketsR.ok ? (ticketsR.body.count ?? 0) : null, partial, answer } }];`, {
    role: '이관 비율, 구간별 p50·p95, DLQ 건수를 계산한다.',
    input: '세 조회 결과.',
    work: '기록을 한국 날짜로 다시 거른다. 비율과 백분위는 코드로 계산한다. LLM을 쓰지 않아 숫자가 달라지지 않는다. 읽지 못한 값은 null로 두고 partial에 적는다.',
    output: '{period, total, by_route, handoff_rate, steps, dlq_size_now, tickets_created_now, partial, answer}. 뒤에 _now가 붙은 값은 기간과 무관한 현재 값이다.',
  });
  f.respond('운영 지표 응답', '={{ $json }}', { role: '지표를 돌려준다.', input: '지표 계산.', output: 'HTTP 200 JSON.' });
  f.chain('운영 질문 수신', '기간 정리', '실행 기록 읽기');
  f.both('실행 기록 읽기', '생성 티켓 읽기');
  f.both('생성 티켓 읽기', 'DLQ 읽기');
  f.both('DLQ 읽기', '지표 계산');
  f.link('지표 계산', '운영 지표 응답');
  return f;
}
