// Run the actual TypeScript API module with platform I/O boundaries controlled.
const fs=require('node:fs');const vm=require('node:vm');const assert=require('node:assert/strict');
const ts=require('typescript');const test=require('node:test');const path=require('node:path');
function client({platform='MP-WEIXIN',transport='wechat-cloud',cloudReply={statusCode:200,data:{status:'ok'}},cloudError=false,env='dental-d8gj2dy3mb506dfdc',cloudAvailable=true,directReply={statusCode:200,data:{source:'direct'}}}={}){
 let source=fs.readFileSync(path.join(__dirname,'../src/api.ts'),'utf8');
 if(platform!=='MP-WEIXIN')source=source.replace(/\/\/ #ifdef MP-WEIXIN[\s\S]*?\/\/ #endif/g,'');
 source=source.replace(/import\.meta\.env/g,'__env');
 const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
 const calls=[],storage=new Map([['adc-patient-token','existing-bearer'],['adc-staff-token','existing-bearer']]),events=[];
 const uni={getStorageSync:k=>storage.get(k),setStorageSync:(k,v)=>storage.set(k,v),removeStorageSync:k=>storage.delete(k),$emit:e=>events.push(e),request:options=>{calls.push({type:'direct',options});queueMicrotask(()=>options.success(directReply));}};
 const cloud={init:options=>calls.push({type:'init',options}),callFunction:options=>{calls.push({type:'cloud',options});queueMicrotask(()=>cloudError?options.fail({errMsg:'private runtime detail'}):options.success({result:cloudReply}));}};
 const context={exports:{},require:name=>{assert.equal(name,'vue');return{reactive:v=>v};},uni,wx:cloudAvailable?{cloud}:undefined,__env:{VITE_NETWORK_TRANSPORT:transport,VITE_WECHAT_CLOUD_ENV:env,VITE_API_BASE:'https://api.yjr-adc-demo.xyz'},queueMicrotask};
 vm.runInNewContext(code,context);
 return{api:context.exports,calls,storage,events};
}
test('native cloud requests preserve actual method, scope token and idempotency key',async()=>{
 const c=client();await c.api.request('/api/appointments/slots?date=2026-11-14');await c.api.request('/api/appointments',{slot:'x'},'one-action');
 assert.equal(c.calls.filter(x=>x.type==='init').length,1);assert.equal(c.calls.filter(x=>x.type==='direct').length,0);
 const [first,second]=c.calls.filter(x=>x.type==='cloud').map(x=>x.options);assert.equal(first.name,'adcNetworkGateway');assert.equal(first.data.method,'GET');assert.equal(first.data.token,'existing-bearer');assert.equal('data' in first.data,false);assert.equal(second.data.method,'POST');assert.equal(second.data.idempotencyKey,'one-action');assert.equal(second.data.data.slot,'x');
});
test('cloud 401 and scope_revoked remove stale identity and notify UI',async()=>{
 for(const result of [{statusCode:401,data:{message:'登录已过期'}},{statusCode:403,data:{error:'scope_revoked',message:'授权已撤销'}}]){
  const c=client({cloudReply:result});await assert.rejects(c.api.request('/api/workspace'),e=>e.status===result.statusCode);assert.equal(c.api.session.token,'');assert.equal(c.storage.has('adc-patient-token'),false);assert.deepEqual(c.events,['adc:authentication-lost']);
 }
});
test('ordinary 403 preserves identity while 409 and 429 remain backend errors',async()=>{
 for(const status of [403,409,429]){const c=client({cloudReply:{statusCode:status,data:{message:'业务拒绝'}}});await assert.rejects(c.api.request('/api/appointments',{slot:'occupied'},'same-key'),e=>e.status===status&&e.message==='业务拒绝');assert.equal(c.api.session.token,'existing-bearer');assert.equal(c.calls.filter(x=>x.type==='cloud').length,1);}
});
test('cloud failure cannot cause silent direct fallback or duplicate submission',async()=>{
 const c=client({cloudError:true});await assert.rejects(c.api.request('/api/appointments',{slot:'x'},'same-key'),e=>e.status===0&&!e.message.includes('private'));assert.equal(c.calls.filter(x=>x.type==='cloud').length,1);assert.equal(c.calls.filter(x=>x.type==='direct').length,0);
});
test('missing API or wrong environment fails closed before any network call',async()=>{
 for(const options of [{cloudAvailable:false},{env:'unrelated-environment'}]){const c=client(options);await assert.rejects(c.api.request('/healthz'));assert.equal(c.calls.length,0);}
});
test('malformed cloud envelope does not become a successful connection',async()=>{
 for(const cloudReply of [{},null,{statusCode:'200',data:{}},{statusCode:200}]){const c=client({cloudReply});await assert.rejects(c.api.request('/healthz'),e=>e.status===502);}
});
test('H5 and native direct builds keep their existing HTTPS request path',async()=>{
 for(const options of [{platform:'H5'},{transport:''}]){const c=client(options);assert.equal((await c.api.request('/api/workspace')).source,'direct');assert.equal(c.calls.length,1);assert.equal(c.calls[0].options.url,'https://api.yjr-adc-demo.xyz/api/workspace');assert.equal(c.calls[0].options.header.Authorization,'Bearer existing-bearer');}
});
test('late rejection for an older token cannot erase a newer login',async()=>{
 const c=client({cloudReply:{statusCode:401,data:{message:'old session expired'}}});const pending=c.api.request('/api/workspace');c.api.saveToken('newer-login-token');await assert.rejects(pending);assert.equal(c.api.session.token,'newer-login-token');assert.equal(c.storage.get('adc-patient-token'),'newer-login-token');assert.deepEqual(c.events,[]);
});
test('invalid public login or recovery proof does not revoke an existing session',async()=>{
 for(const path of ['/api/auth/login','/api/auth/wechat','/api/auth/wechat/select','/api/auth/recovery','/api/auth/reset-password']){const c=client({cloudReply:{statusCode:401,data:{message:'form proof invalid'}}});await assert.rejects(c.api.request(path,{code:'invalid-form-proof'}));assert.equal(c.api.session.token,'existing-bearer');assert.deepEqual(c.events,[]);assert.equal(c.calls.find(x=>x.type==='cloud').options.data.token,'');}
});
test('simultaneous rejection emits one expiry notice for the current identity',async()=>{
 const c=client({cloudReply:{statusCode:401,data:{message:'expired'}}});const requests=[c.api.request('/api/workspace'),c.api.request('/api/records?resource=appointments')];await Promise.allSettled(requests);assert.equal(c.api.session.token,'');assert.deepEqual(c.events,['adc:authentication-lost']);
});
test('patient native and staff web password login declare their own entry',async()=>{
 for(const [platform,surface] of [['MP-WEIXIN','patient'],['H5','staff']]){
  const c=client({platform});const data={login_name:'example',password:'ephemeral-test-password'};
  await c.api.request('/api/auth/login',data);
  const sent=c.calls.find(x=>x.type===(platform==='H5'?'direct':'cloud')).options;
  assert.equal((platform==='H5'?sent.data:sent.data.data).client_surface,surface);
  assert.equal(data.client_surface,undefined);
  if(platform==='H5'){assert.equal(sent.header['X-ADC-Surface'],'staff');assert.equal(sent.header.Authorization,undefined);}
  else assert.equal(sent.data.token,'');
 }
});
test('patient and staff tokens use independent local stores',()=>{
 const c=client();c.api.saveToken('patient-only-new-token');assert.equal(c.storage.get('adc-patient-token'),'patient-only-new-token');assert.equal(c.storage.get('adc-staff-token'),'existing-bearer');
 c.api.clearToken();assert.equal(c.storage.has('adc-patient-token'),false);assert.equal(c.storage.get('adc-staff-token'),'existing-bearer');
});
