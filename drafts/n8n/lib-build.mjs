// 워크플로우 JSON 생성 도구. 노드 모양(type, typeVersion, 파라미터 구조)은 Last3Mon reference에서 가져왔다.
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
export const ROOT = join(HERE, '..', '..');
export const DATA_API = 'http://data-api:8800';
export const N8N_SELF = 'http://localhost:5678/webhook';
export const CRED = {
  openai: { openAiApi: { id: 'ticketmoaOpenAi01', name: 'OpenAI' } },
  data: { httpHeaderAuth: { id: 'ticketmoaDataApi1', name: 'ticketmoa-data-api' } },
  team: { httpHeaderAuth: { id: 'ticketmoaTeamKey1', name: 'ticketmoa-team-key' } },
};
export const ERROR_WORKFLOW_ID = 'ticketmoaErrors01';

const common = readFileSync(join(ROOT, 'lib', 'common.js'), 'utf8');

/** lib/common.js에서 함수·상수 원문을 그대로 잘라 온다. 노드 안에서 새로 짜지 않기 위한 장치다. */
export function lib(...names) {
  const parts = names.map(name => {
    const start = common.search(new RegExp('^(?:function|const) ' + name + '\\b', 'm'));
    if (start < 0) throw new Error('lib/common.js에 없음: ' + name);
    if (common.slice(start).startsWith('const')) {
      const line = common.slice(start, common.indexOf('\n', start));
      const closer = /=\s*\{\s*$/.test(line) ? '\n};' : (/=\s*\[\s*$/.test(line) ? '\n];' : ';');
      const stop = common.indexOf(closer, start) + closer.length;
      return common.slice(start, stop);
    }
    let depth = 0;
    let seen = false;
    for (let i = common.indexOf('{', common.indexOf(')', start)); i < common.length; i++) {
      if (common[i] === '{') { depth++; seen = true; }
      if (common[i] === '}') depth--;
      if (seen && depth === 0) return common.slice(start, i + 1);
    }
    throw new Error('함수 끝을 찾지 못함: ' + name);
  });
  return '// ↓ lib/common.js 원문 복사\n' + parts.join('\n') + '\n// ↑ lib/common.js 원문 복사 끝\n';
}

export function note({ role, input, work, output, fail }) {
  const lines = ['【역할】 ' + role];
  if (input) lines.push('【입력】 ' + input);
  if (work) lines.push('【처리】 ' + work);
  if (output) lines.push('【출력】 ' + output);
  if (fail) lines.push('【실패 시】 ' + fail);
  return lines.join('\n');
}

export class Flow {
  constructor({ file, name, id, owner, purpose, reference, scenarios, isErrorWorkflow = false }) {
    Object.assign(this, { file, name, owner, purpose, reference, scenarios });
    this.id = id;
    this.nodes = [];
    this.connections = {};
    this.isErrorWorkflow = isErrorWorkflow;
  }

  add(name, type, typeVersion, parameters, doc, extra = {}) {
    if (this.nodes.some(n => n.name === name)) throw new Error(this.file + ': 노드 이름 중복 ' + name);
    if (!doc || !doc.role) throw new Error(this.file + ': 설명 없음 ' + name);
    const hash = createHash('sha1').update(this.file + '/' + name).digest('hex');
    const nodeId = [hash.slice(0, 8), hash.slice(8, 12), hash.slice(12, 16), hash.slice(16, 20), hash.slice(20, 32)].join('-');
    this.nodes.push({ id: nodeId, name, type, typeVersion, position: [0, 0], parameters, notes: note(doc), notesInFlow: false, ...extra });
    return name;
  }

  code(name, jsCode, doc) {
    return this.add(name, 'n8n-nodes-base.code', 2, { jsCode }, doc);
  }

  webhook(name, path, doc) {
    const hash = createHash('sha1').update('webhook/' + path).digest('hex');
    const webhookId = [hash.slice(0, 8), hash.slice(8, 12), hash.slice(12, 16), hash.slice(16, 20), hash.slice(20, 32)].join('-');
    return this.add(name, 'n8n-nodes-base.webhook', 2,
      { httpMethod: 'POST', path, authentication: 'headerAuth', responseMode: 'responseNode', options: {} },
      doc, { webhookId, credentials: CRED.team });
  }

  respond(name, bodyExpression, doc, responseCode) {
    const options = responseCode ? { responseCode } : {};
    return this.add(name, 'n8n-nodes-base.respondToWebhook', 1.1,
      { respondWith: 'json', responseBody: bodyExpression, options }, doc);
  }

  /** 데이터 API·하위 웹훅 호출. 상태 코드를 직접 읽으려고 fullResponse + neverError, 연결 실패·timeout은 오류 출력으로 받는다. */
  http(name, { method = 'GET', url, body, timeout, auth }, doc) {
    const parameters = { url, options: { timeout, response: { response: { fullResponse: true, neverError: true } } } };
    if (method !== 'GET') parameters.method = method;
    if (body) Object.assign(parameters, { sendBody: true, specifyBody: 'json', jsonBody: body });
    parameters.authentication = 'genericCredentialType';
    parameters.genericAuthType = 'httpHeaderAuth';
    return this.add(name, 'n8n-nodes-base.httpRequest', 4.2, parameters, doc,
      { onError: 'continueErrorOutput', credentials: CRED[auth] });
  }

  iff(name, expression, doc) {
    return this.add(name, 'n8n-nodes-base.if', 2.2, {
      conditions: {
        options: { caseSensitive: true, leftValue: '', typeValidation: 'loose', version: 2 },
        conditions: [{ id: 'c1', leftValue: expression, rightValue: '', operator: { type: 'boolean', operation: 'true', singleValue: true } }],
        combinator: 'and',
      },
      options: {},
    }, doc);
  }

  /** 값이 어느 칸에도 안 맞으면 마지막(extra) 출력으로 간다. 멈춘 채 응답이 안 나가는 일을 막기 위해서다. */
  switchOn(name, expression, keys, doc) {
    return this.add(name, 'n8n-nodes-base.switch', 3.2, {
      rules: {
        values: keys.map(key => ({
          conditions: {
            options: { caseSensitive: true, leftValue: '', typeValidation: 'strict', version: 2 },
            conditions: [{ leftValue: expression, rightValue: key, operator: { type: 'string', operation: 'equals' } }],
            combinator: 'and',
          },
          renameOutput: true,
          outputKey: key,
        })),
      },
      options: { fallbackOutput: 'extra', renameFallbackOutput: '예상 밖' },
    }, doc);
  }

  merge(name, doc) {
    return this.add(name, 'n8n-nodes-base.merge', 3, { numberInputs: 2 }, doc);
  }

  agent(name, { system, text, modelName, timeout, modelDoc }, doc) {
    this.add(name, '@n8n/n8n-nodes-langchain.agent', 3.1,
      { promptType: 'define', text, options: { systemMessage: system, maxIterations: 1 } },
      doc, { onError: 'continueErrorOutput' });
    this.add(modelName, '@n8n/n8n-nodes-langchain.lmChatOpenAi', 1.2,
      { model: { __rl: true, mode: 'id', value: 'gpt-4.1-mini' }, options: { temperature: 0, timeout, maxRetries: 1 } },
      modelDoc, { credentials: CRED.openai });
    this.link(modelName, name, 0, 0, 'ai_languageModel');
    return name;
  }

  /** from의 출력 fromIndex를 to의 입력 toIndex에 잇는다 */
  link(from, to, fromIndex = 0, toIndex = 0, type = 'main') {
    for (const n of [from, to]) if (!this.nodes.some(x => x.name === n)) throw new Error(this.file + ': 없는 노드 연결 ' + n);
    const c = (this.connections[from] ||= {});
    const outs = (c[type] ||= []);
    while (outs.length <= fromIndex) outs.push([]);
    outs[fromIndex].push({ node: to, type, index: toIndex });
  }

  chain(...names) {
    for (let i = 0; i + 1 < names.length; i++) this.link(names[i], names[i + 1]);
  }

  /** HTTP 노드의 성공·실패 출력을 같은 읽기 노드로 모은다 */
  both(from, to, toIndex = 0) {
    this.link(from, to, 0, toIndex);
    this.link(from, to, 1, toIndex);
  }

  layout() {
    const main = {};
    for (const [from, kinds] of Object.entries(this.connections)) {
      for (const branch of kinds.main || []) for (const l of branch) (main[from] ||= []).push(l.node);
    }
    const incoming = {};
    for (const [f, ts] of Object.entries(main)) for (const t of ts) (incoming[t] ||= []).push(f);
    const starts = this.nodes.filter(n => /webhook$|errorTrigger$/.test(n.type)).map(n => n.name);
    const column = {};
    // 깊이 우선으로 경로를 따라 column을 정한다. 되돌아가는 연결(재시도 루프)은 무시한다.
    const visit = (name, depth, trail) => {
      if ((column[name] ?? -1) >= depth) return;
      column[name] = depth;
      for (const t of main[name] || []) if (!trail.has(t)) visit(t, depth + 1, new Set([...trail, t]));
    };
    starts.forEach((s, i) => visit(s, 0, new Set([s])));
    // 같은 칸 안의 순서는 연결된 노드의 평균 위치로 맞춘다 (선 교차를 줄인다).
    const X = 300;
    const Y = 150;
    const byCol = {};
    for (const node of this.nodes) if (column[node.name] !== undefined) (byCol[column[node.name]] ||= []).push(node.name);
    const cols = Object.keys(byCol).map(Number).sort((a, b) => a - b);
    const order = {};
    const place = () => cols.forEach(c => byCol[c].forEach((n, i) => { order[n] = i - (byCol[c].length - 1) / 2; }));
    place();
    for (let sweep = 0; sweep < 8; sweep++) {
      const list = sweep % 2 ? [...cols].reverse() : cols;
      for (const c of list) {
        const neighbours = sweep % 2 ? main : incoming;
        const score = n => { const a = (neighbours[n] || []).filter(x => column[x] !== c); return a.length ? a.reduce((t, x) => t + order[x], 0) / a.length : order[n]; };
        byCol[c] = byCol[c].map(n => [n, score(n)]).sort((a, b) => a[1] - b[1]).map(x => x[0]);
        place();
      }
    }
    for (const node of this.nodes) {
      if (column[node.name] === undefined) continue;
      node.position = [column[node.name] * X, Math.round(order[node.name] * Y)];
    }
    // 모델·임베딩 같은 보조 노드는 붙는 노드 바로 아래 칸에 둔다.
    for (const node of this.nodes) {
      if (column[node.name] !== undefined) continue;
      const kinds = this.connections[node.name] || {};
      const link = Object.values(kinds).flat(2)[0];
      const parent = this.nodes.find(n => n.name === link?.node);
      const siblings = this.nodes.filter(n => n !== node && column[n.name] === undefined && n.position[0] === parent?.position[0] && n.position[1] !== 0);
      const colMax = Math.max(...this.nodes.filter(n => n !== node && n.position[0] === parent?.position[0]).map(n => n.position[1]), parent?.position[1] ?? 0);
      node.position = [parent?.position[0] ?? 0, colMax + Y];
    }
  }

  toJSON() {
    this.layout();
    const settings = { executionOrder: 'v1', callerPolicy: 'workflowsFromSameOwner' };
    if (!this.isErrorWorkflow) settings.errorWorkflow = ERROR_WORKFLOW_ID;
    return { id: this.id, name: this.name, nodes: this.nodes, connections: this.connections, settings, active: false, meta: { owner: this.owner, purpose: this.purpose, reference: this.reference, scenarios: this.scenarios } };
  }
}

/** HTTP 응답(fullResponse) 또는 오류 출력 항목을 한 모양으로 읽는 Code 조각. 모든 읽기 노드가 같이 쓴다. */
export const READ_HTTP = [
  'function readHttp(j) {',
  '  if (j && typeof j.statusCode === "number") {',
  '    const body = j.body && typeof j.body === "object" ? j.body : {};',
  '    return { ok: j.statusCode >= 200 && j.statusCode < 300 && !body.error, status: j.statusCode, body, errorCode: "" };',
  '  }',
  '  const text = j && j.error ? (typeof j.error === "string" ? j.error : JSON.stringify(j.error)) : "no_response";',
  '  return { ok: false, status: null, body: {}, errorCode: text.slice(0, 300) };',
  '}',
].join('\n');
