// Evaluate unchanged generated Code nodes with explicit fixture inputs.
// This never imports build.mjs or changes workflows/runtime API state.
import {readFileSync,writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
const dir=new URL('../../../workflows/',import.meta.url);
const names=['support','agents','refund','index','search','tech','payment','handoff','errors','ops'];
const flows=Object.fromEntries(names.map(n=>[n,JSON.parse(readFileSync(new URL(`ticketmoa-${n}.json`,dir)))]));
const out=[];const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
async function code(flow,name,input,refs={}){
 const node=flows[flow].nodes.find(n=>n.name===name);
 const $=n=>{if(!(n in refs))return {isExecuted:false};const j=refs[n];return{isExecuted:true,first:()=>({json:j}),last:()=>({json:j}),all:()=>[{json:j}]}};
 const $input={first:()=>({json:input}),all:()=>[{json:input}]};
 return (await new AsyncFunction('$json','$input','$',node.parameters.jsCode)(input,$input,$))[0].json;
}
const raw={user:'정민아',question:'제휴 카드 포인트1',attempt:1,context:{},request_id:'offline-only'};
const initial=await code('support','중복 판정',{statusCode:404,body:{}},{'규칙 차단 판정':raw});
const changed=await code('support','중복 판정',{statusCode:200,body:{value:{fp:initial.fp,response:{ticket:{id:'OFFLINE'}},replay_until:Date.now()+60000}}},{'규칙 차단 판정':{...raw,question:'제휴 카드 포인트',attempt:11}});
out.push({case:'ambiguous-concatenation',first:initial.fp,result:changed});
const collision=JSON.parse(readFileSync(new URL('reports/codex3-fingerprint-collision.json',import.meta.url)));
const a=await code('support','중복 판정',{statusCode:404,body:{}},{'규칙 차단 판정':{...raw,user:collision.userA,question:collision.questionA}});
const b=await code('support','중복 판정',{statusCode:200,body:{value:{fp:a.fp,response:{answer:'OWNER RECORD',ticket:{id:'OFFLINE'}},replay_until:Date.now()+60000}}},{'규칙 차단 판정':{...raw,user:collision.userB,question:collision.questionB}});
out.push({case:'cross-user-32bit-collision',input:collision,result:b});
const rec=JSON.parse(readFileSync(new URL('../../../data/records.json',import.meta.url)))['C-2003'];
const refunded=await code('refund','환불 금액 계산',{statusCode:200,body:{hits:[{doc:'refund-policy',section:'2',score:1,text:'규정'}]}},{'조회 결과 읽기':{record:rec,record_id:'C-2003',user:'이도윤'}});
out.push({case:'already-refunded-record',record:rec,result:refunded});
const falseQueue=await code('refund','이관 답',{}, {'이관 결과 읽기':{ticket:null,ho:{answer:'환불 요청이 접수됐고 상담원이 처리합니다.',sources:[],reason:'refund_confirmed'},handoff_reason:'handoff_unavailable'}});
out.push({case:'refund-unverified-queue-claim',result:falseQueue});
const staffFailed=await code('search','검색 결과 조립',{}, {'검색 준비':{scope:[],search_staff:true,top_k:3},'일반 결과 정리':{raw:[{doc:'venue-faq',section:'2',score:.9,text:'주차'}],failed:false},'스태프 결과 정리':{raw:[],failed:true}});
out.push({case:'staff-search-failure-ignored',result:staffFailed});
for(const q of ['공연 20분 후인데 QR 안 떠요','공연 20분 뒤인데 QR 안 떠요']){
 out.push({case:'late-entry-urgency',question:q,result:await code('agents','규칙 신호 추출',{body:{question:q,registry:{intents:[]}}})});
}
let total=0;const graph=[];
for(const [name,w] of Object.entries(flows)){
 const nodeMap=new Map(w.nodes.map(n=>[n.name,n]));const reachable=new Set();
 function walk(n){if(reachable.has(n))return;reachable.add(n);for(const links of w.connections[n]?.main||[])for(const l of links)walk(l.node)}
 for(const n of w.nodes.filter(n=>/webhook$|errorTrigger$/.test(n.type)))walk(n.name);
 const unresolved=[];
 for(const [n,kinds]of Object.entries(w.connections))for(const [kind,branches]of Object.entries(kinds))for(const branch of branches)for(const l of branch)if(!nodeMap.has(l.node))unresolved.push(l.node);
 for(const n of w.nodes.filter(n=>n.type.endsWith('.code'))){new AsyncFunction(n.parameters.jsCode);total++}
 graph.push({workflow:name,nodes:w.nodes.length,unreachableMain:w.nodes.filter(n=>!reachable.has(n.name)&& !/lmChatOpenAi$|embeddingsOpenAi$|documentDefaultDataLoader$/.test(n.type)).map(n=>n.name),unresolved,sha256:createHash('sha256').update(JSON.stringify(w)).digest('hex')});
}
out.push({case:'graph-and-code-parse',codeNodes:total,flows:graph});
writeFileSync(new URL('reports/codex3-node-evidence.json',import.meta.url),JSON.stringify(out,null,2));
for(const row of out)console.log(row.case,JSON.stringify(row.result||row.flows||{}).slice(0,1300));
