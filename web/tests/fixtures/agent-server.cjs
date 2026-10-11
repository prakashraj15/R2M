// Disposable UI contract fixture. No model, database, cloud or external network calls.
const http=require('node:http');
const agent='11111111-1111-4111-8111-111111111111', installation='22222222-2222-4222-8222-222222222222', customer='33333333-3333-4333-8333-333333333333', trace='44444444-4444-4444-8444-444444444444';
let email='ops@meridian.demo',approval=null,executed=false,count=0;
const service=()=>({service_key:'payments-api',deployment_version:executed?'v2.0':'v2.1',previous_version:'v2.0',replicas:3,cpu_pct:executed?32:78,memory_pct:66,error_rate_pct:executed?.4:7.8,p95_latency_ms:executed?180:920,health_status:executed?'healthy':'degraded'});
const roles={'ops@meridian.demo':'customer_ops','security@meridian.demo':'customer_security','dev@atlas.demo':'vendor_developer','release@atlas.demo':'vendor_release_manager'};
const perms=()=>['demo.use',...(email.startsWith('security')?['approval.decide','integration.configure']:[])];
const server=http.createServer(async(req,res)=>{const u=new URL(req.url,'http://localhost');let input='';for await(const c of req)input+=c;const body=input?JSON.parse(input):{};function out(data,status=200){res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(data));}
if(['POST','PUT','DELETE','PATCH'].includes(req.method)&&req.headers['x-r2m-csrf']!=='1')return out({code:'csrf_required',message:'CSRF missing'},403);
const p=u.pathname.replace('/api/v1','');
if(p==='/demo/identities')return out({identities:Object.entries(roles).map(([email,role])=>({email,role,display_name:email,organization:email.includes('meridian')?'Meridian Financial':'Atlas Applied AI'}))});
if(p==='/demo/session'){email=body.email || '';return out({ok:true});}
if(!email)return out({code:'unauthenticated',message:'Select a demo identity'},401);
if(p==='/me')return out({user:{id:email,email,display_name:email},organizations:[{id:customer,name:'Meridian Financial',kind:'customer',slug:'meridian',roles:[roles[email]],permissions:perms()}],demo_auth:true});
if(p==='/demo/agent/state')return out({agent_id:agent,installation_id:installation,customer_org_id:customer,services:[service()],scenarios:['healthy','degraded','approval','faulty'],recent_actions:[],approvals:approval?[approval]:[],last_execution:null,notice:'UI CONTRACT FIXTURE — synthetic service; no live provider calls.'});
if(p.includes('/scenarios/')){approval=null;executed=false;return out({scenario:p.split('/')[4],service:service()});}
if(p==='/demo/agent/message'){count++; if(body.message==='continue'&&approval?.status==='approved'){executed=true;approval.status='consumed';return out({reply:'Contract fixture: approved rollback completed.',mode:'simulated',model:'fixture',decision:'ALLOW',reasons:[],steps:['EXECUTE','VERIFY','REPORT'],trace_id:trace,execution_id:'exec-fixture',verified:true,service_after:service(),cost_label:'simulated',suggestions:[]});}
approval={id:'approval-fixture',kind:'runtime_action',status:'pending',tool_key:'rollback_deployment',arguments:{target_version:'v2.0'},arguments_hash:'fixture-only',trace_id:trace,execution_id:'exec-fixture',agent_id:agent,installation_id:installation,customer_org_id:customer,can_decide:email.startsWith('security')};
return out({reply:'Contract fixture: <b>plain text</b>. Rollback requires approval. Say continue after approval.',mode:'simulated',model:'fixture',decision:'REQUIRE_APPROVAL',reasons:['PRODUCTION_ROLLBACK_REQUIRES_APPROVAL'],steps:['RECEIVED','PROPOSE','POLICY_GATE','WAIT_APPROVAL','REPORT'],proposal:{tool:'rollback_deployment',arguments:{target_version:'v2.0'},source:'keewano',rationale:'Fixture rationale'},insight:{provider:'keewano',status:'ok',supported:true,label:'Fixture history only — no Keewano request',sample_count:112,candidates:[{remediation:'rollback',samples:57,successes:52}]},approval_id:approval.id,trace_id:trace,execution_id:'exec-fixture',build:{version:'safe-1.0',deployment_status:'deployed'},cost_label:'simulated',suggestions:['continue']});}
if(p==='/approvals')return out({approvals:approval?[{...approval,can_decide:email.startsWith('security')&&approval.status==='pending'}]:[]});
if(p.endsWith('/decision')){approval.status=body.decision==='approve'?'approved':'rejected';return out({status:approval.status});}
if(p==='/integrations/keewano')return out({platform_enabled:true,adapter_installed:true,organizations:[{organization_id:customer,name:'Meridian Financial',enabled:true,backlog:0,dead:0}]});
if(p.endsWith('/topology'))return out({nodes:[{id:'openai-llm',component_key:'openai-llm',kind:'model',label:'OpenAI model',status:'unknown',source:'Contract fixture — no telemetry',metrics:null}],edges:[]});
if(p===`/traces/${trace}`)return out({execution:{id:'exec-fixture',status:'completed',started_at:'2026-10-11T20:00:00Z'},spans:[{id:'span',name:'model:fixture',kind:'model',depth:0,started_at:'2026-10-11T20:00:00Z',duration_ms:500,status:'completed',attributes:{component:'openai-llm',prompt:'[vendor-private]'}}],redacted_for_customer:true,usage:[{cost_source:'simulated',amount_usd:0.001}],events:[],actions:[],decisions:[],grants:[],approvals:[],insights:[]});
if(p.endsWith('/traces'))return out({traces:[{trace_id:trace,execution_id:'exec-fixture',status:'completed',scenario:'approval'}],next_cursor:null});
if(p==='/fixture-count')return out({messages:count});
return out({code:'not_found',message:'Contract fixture endpoint not implemented'},404);
});server.listen(8000,'127.0.0.1',()=>console.log('UI contract fixture listening on loopback 8000. Stop with Ctrl+C.'));
