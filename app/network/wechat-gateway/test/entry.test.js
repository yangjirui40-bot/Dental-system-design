'use strict';
const test=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');const path=require('node:path');
const {handler}=require('../policy');const {trustedAppId}=require('../context');
function entry({brokenJson=false,brokenConfig=false}={}){
 const env={WX_CONTEXT_KEYS:'WX_APPID',WX_APPID:'wxf278ca432c9e7224'},calls=[],logs=[];let factories=0;
 const mocks={'node:fs':{readFileSync:()=>brokenJson?'invalid JSON':JSON.stringify({privateKey:'never disclose this private value'})},'node:path':path,'./policy':{handler},'./context':{trustedAppId:()=>trustedAppId(env)},'./tunnel':{createForward:()=>{factories++;if(brokenConfig)throw Error('never disclose this private value');return async request=>{calls.push(request);return{statusCode:200,data:{status:'ok',database:'test-boundary'}};};}}};
 const context={exports:{},require:id=>{assert.ok(id in mocks,'unexpected dependency '+id);return mocks[id];},__dirname:'/private-test-function',console:{info:(...x)=>logs.push(x)},Date};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../index.js'),'utf8'),context);
 return{main:context.exports.main,env,calls,logs,factories:()=>factories};
}
test('entry returns awaited response, disables idle-event waiting and loads only gateway dependencies',async()=>{
 const e=entry(),context={callbackWaitsForEmptyEventLoop:true};const response=await e.main({path:'/healthz',diagnostics:true},context);
 assert.equal(response.statusCode,200);assert.equal(context.callbackWaitsForEmptyEventLoop,false);assert.ok(response.gatewayDiagnostics.requestMs>=0);assert.equal(e.calls.length,1);assert.ok(!JSON.stringify(e.logs).includes('private value'));
});
test('cached forwarder rechecks platform identity for every invocation',async()=>{
 const e=entry();assert.equal((await e.main({path:'/healthz'},{})).statusCode,200);e.env.WX_APPID='another-app';assert.equal((await e.main({path:'/healthz',APPID:'wxf278ca432c9e7224'},{})).statusCode,403);assert.equal(e.factories(),1);assert.equal(e.calls.length,1);
});
test('missing or invalid private runtime configuration fails closed without disclosure',async()=>{
 for(const options of [{brokenJson:true},{brokenConfig:true}]){const e=entry(options),reply=await e.main({path:'/healthz'},{});assert.equal(reply.statusCode,503);assert.equal(reply.data.error,'gateway_not_configured');assert.equal(e.calls.length,0);assert.ok(!JSON.stringify(reply).includes('private value'));}
});
