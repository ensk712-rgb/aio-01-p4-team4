// node drafts/n8n/build.mjs → 저장소 뿌리의 workflows/*.json 생성
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { ROOT } from './lib-build.mjs';
import { buildIndex, buildSearch, buildPayment, buildHandoff, buildErrors, buildOps } from './build-leaf.mjs';
import { buildAgents, buildTech, buildRefund, buildSupport } from './build-core.mjs';

const OUT = join(ROOT, 'workflows');
mkdirSync(OUT, { recursive: true });
const flows = [buildErrors, buildIndex, buildSearch, buildPayment, buildHandoff, buildAgents, buildTech, buildRefund, buildSupport, buildOps].map(b => b());
for (const flow of flows) {
  const json = flow.toJSON();
  writeFileSync(join(OUT, flow.file + '.json'), JSON.stringify(json, null, 2) + '\n');
  console.log(flow.file.padEnd(20), String(json.nodes.length).padStart(3), 'nodes');
}
console.log('total', flows.reduce((n, f) => n + f.nodes.length, 0));
