import {readFileSync,writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
const root=new URL('../../../workflows/',import.meta.url);
const names=['support','agents','refund','index','search','tech','payment','handoff','errors','ops'];
const flows=Object.fromEntries(names.map(n=>[n,JSON.parse(readFileSync(new URL(`ticketmoa-${n}.json`,root)))]));
const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
const results=[];
async function run(flow,name,input,refs={}){
 const node=flows[flow].nodes.find(n=>n.name===name);
 const items=Array.isArray(input)?input.map(json=>({json})):[{json:input}];
 const $=name=>({isExecuted:name in refs,first:()=>({json:refs[name]}),last:()=>({json:refs[name]}),all:()=>name in refs?[{json:refs[name]}]:[]});
 return (await new AsyncFunction('$json','$input','$',node.parameters.jsCode)(items[0].json,{first:()=>items[0],all:()=>items},$))[0].json;
}
const ticket={id:'T-2001',key:'original-confirm',category:'refund'};
const existing={ticket,sources:[],status:'confirmed',record_id:'C-2005',booking_id:'T20261104-0412'};
for(const branch of ['quote','confirm'])for(const present of [true,false]){
 const prev={from:branch,existing};
 const refs=branch==='quote'?{'기존 확정 판정':prev}:{'확인 자격 판정':prev};
 const result=await run('refund','확정 유효 판정',{statusCode:200,body:{tickets:present?[{ticket_id:ticket.id}]:[]}},refs);
 const expected=present?'existing':branch==='quote'?'quote':'none';
 results.push({case:'existing-'+branch+'-'+present,expected,pass:result.next_step===expected,result});
}
for(const ran of [false,true]){
 const result=await run('tech','시간 부족 결과',{},ran?{'작성 결과 검사':{}}:{});
 results.push({case:'budget-'+ran,pass:result.route==='담당자 이관'&&result.llm_calls===(ran?1:0)&&result.answer==='',result});
}
for(const [label,state] of Object.entries({transport:{ticket:null,handoff_ok:false,dlq:false},queue:{ticket:null,handoff_ok:true,dlq:true},failed:{ticket:null,handoff_ok:true,dlq:false}})){
 const result=await run('refund','이관 답',{}, {'이관 결과 읽기':{...state,ho:{answer:'상담원 확인이 필요합니다.',reason:'check',sources:[]}}});
 results.push({case:'refund-wording-'+label,pass:!result.answer.includes('접수했습니다')&&(label==='queue'||!result.answer.includes('보관했습니다')),result});
}
const search=await run('search','검색 결과 조립',{}, {'검색 준비':{scope:[],search_staff:true,top_k:3},'일반 결과 정리':{failed:false,raw:[{doc:'venue-faq',section:'주차',score:1,text:'주차'}]},'스태프 결과 정리':{failed:true,raw:[]}});
results.push({case:'staff-failure',pass:search.error==='staff_search_failed'&&search.staff_indexed===false,result:search});
const doc=readFileSync(new URL('../../../knowledge/venue-faq.md',import.meta.url),'utf8');
const quality=await run('index','문서 품질 검사',[{statusCode:200,body:{name:'venue-faq',title:'FAQ',text:doc}}]);
const rejected=await run('index','색인 실패 정리',quality);
results.push({case:'one-access-group',pass:quality.no_chunks&&rejected.error==='access_group_empty',result:rejected});
const ops=await run('ops','지표 계산',{}, {'기간 정리':{from:'2026-11-02',to:'2026-11-02'},'실행 기록 읽기':{statusCode:500,body:{}},'생성 티켓 읽기':{statusCode:200,body:{count:0}},'DLQ 읽기':{statusCode:200,body:{size:0}}});
results.push({case:'ops-failed-logs',pass:ops.total===null&&ops.by_route===null&&ops.partial.includes('logs'),result:ops});
const dupCode=flows.support.nodes.find(n=>n.name==='중복 판정').parameters.jsCode;
const hash=new Function(dupCode.slice(0,dupCode.indexOf("const j ="))+';return sha256;')();
for(const text of ['','abc','한글 😀'])results.push({case:'sha256-'+text,pass:hash(text)===createHash('sha256').update(text).digest('hex'),actual:hash(text)});
try{hash('\ud800');results.push({case:'sha256-surrogate',threw:false})}catch(e){results.push({case:'sha256-surrogate',threw:true,error:String(e)})}
const urgent=flows.handoff.nodes.find(n=>n.name==='긴급 알림');
results.push({case:'alert-http-error-branch',neverError:urgent.parameters.options.response.response.neverError,connections:flows.handoff.connections['긴급 알림']});
const graph=[];
for(const [name,w] of Object.entries(flows)){
 let codes=0;for(const n of w.nodes)if(n.type.endsWith('.code')){new AsyncFunction(n.parameters.jsCode);codes++}
 const all=new Set(w.nodes.map(n=>n.name));const missing=[];const switchMismatch=[];
 for(const [from,kinds] of Object.entries(w.connections))for(const branches of Object.values(kinds))for(const links of branches)for(const link of links)if(!all.has(link.node))missing.push([from,link.node]);
 for(const n of w.nodes.filter(n=>n.type.endsWith('.switch'))){const expected=n.parameters.rules.values.length+1;if((w.connections[n.name]?.main?.length||0)!==expected)switchMismatch.push(n.name)}
 graph.push({workflow:name,nodes:w.nodes.length,codes,missing,switchMismatch,sha256:createHash('sha256').update(JSON.stringify(w)).digest('hex')});
}
results.push({case:'graph',result:graph});
writeFileSync(new URL('reports/codex4-node-evidence.json',import.meta.url),JSON.stringify(results,null,2));
for(const r of results)console.log(r.case,r.pass??r.threw??'',JSON.stringify(r.result??r.connections??r.error??'').slice(0,280));
if(results.some(r=>r.pass===false))process.exitCode=1;
