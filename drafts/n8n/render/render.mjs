// node drafts/n8n/render/render.mjs → drafts/n8n/ticketmoa-workflows.html
import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const WF = join(HERE, '..', '..', '..', 'workflows');
const REPORTS = join(HERE, '..', 'verify', 'reports');
const ORDER = ['support', 'agents', 'search', 'tech', 'payment', 'refund', 'handoff', 'index', 'errors', 'ops'];
const flows = ORDER.map(n => JSON.parse(readFileSync(join(WF, 'ticketmoa-' + n + '.json'), 'utf8')));

const latest = prefix => {
  const f = readdirSync(REPORTS).filter(x => x.startsWith(prefix + '-') && x.endsWith('.json')).sort().pop();
  return f ? { file: f, ...JSON.parse(readFileSync(join(REPORTS, f), 'utf8')) } : null;
};
const slim = rep => rep && ({ file: rep.file, passed: rep.passed, total: rep.total, results: rep.results.map(r => {
  const res = r.response && typeof r.response === 'object' ? r.response : {};
  return { c: r.case, run: r.run, ok: r.passed, sec: r.seconds, st: r.status, route: res.route ?? (res.error ? 'HTTP ' + r.status : ''), ticket: res.ticket?.id ?? null, dup: res.ticket?.duplicate ?? null, pri: res.ticket?.priority ?? null, llm: res.agents?.llm_calls ?? null, src: (res.sources || []).map(s => s.doc), reason: res.reason ?? '', blocked: res.security?.blocked_by ?? '', masked: res.security?.masked ?? null, q: r.request?.question ?? '', a: res.answer ?? (res.codes ? 'codes: ' + res.codes.join(', ') : ''), err: [...(r.ordinary_errors || []), ...(r.strict_errors || [])] };
}) });
const reports = { common: slim(latest('common')), team: slim(latest('team')), adversarial: slim(latest('adversarial')) };
const findings = JSON.parse(readFileSync(join(HERE, 'findings.json'), 'utf8'));

const data = { flows: flows.map(f => ({ raw: JSON.stringify(f, null, 2), id: f.id, name: f.name, meta: f.meta, settings: f.settings, connections: f.connections, nodes: f.nodes.map(n => ({ name: n.name, type: n.type, v: n.typeVersion, pos: n.position, notes: n.notes, params: n.parameters, onError: n.onError || null, cred: n.credentials ? Object.values(n.credentials)[0].name : null })) })), reports, findings };
const page = readFileSync(join(HERE, 'template.html'), 'utf8').replace('/*__DATA__*/null', () => JSON.stringify(data).replace(/</g, '\\u003c'));
const out = join(HERE, '..', 'ticketmoa-workflows.html');
writeFileSync(out, page);
console.log(out, Math.round(page.length / 1024) + 'KB');
