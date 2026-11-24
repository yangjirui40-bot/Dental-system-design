// Explicit live read/login checks; not included in npm test or deployment.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {Client} = require('ssh2');
const {createForward} = require('../tunnel');
const {envelope} = require('../policy');
const root=path.resolve(__dirname,'../../..');
const config=JSON.parse(fs.readFileSync(path.join(root,'backups/wechat-network-gateway/runtime-config.json')));
const access=JSON.parse(fs.readFileSync(path.join(root,'backups/cloud-teaching-access.json')));
const checks=[];
const record=(name,details={})=>{checks.push({name,passed:true,...details});console.log('PASS',name);};
async function restricted(action) {
  return new Promise((resolve,reject)=>{
    const client=new Client();const timer=setTimeout(()=>{client.destroy();reject(new Error('restriction test timeout'));},5000);
    const finish=(ok)=>{clearTimeout(timer);client.destroy();ok?resolve():reject(new Error('restriction not enforced'));};
    client.once('error',()=>finish(false));
    client.once('ready',()=>action(client,finish));
    client.connect({host:config.host,port:22,username:config.username,privateKey:config.privateKey,readyTimeout:3500,hostHash:'sha256',hostVerifier:h=>h===config.hostKeySha256,algorithms:{serverHostKey:['ssh-ed25519']}});
  });
}
(async()=>{
 const forward=createForward(config);
 let start=Date.now();let result=await forward(envelope({path:'/healthz'}));
 assert.equal(result.statusCode,200);assert.equal(result.data.status,'ok');assert.match(result.data.database,/18\.3/);
 record('real original Docker/PostgreSQL health',{elapsed_ms:Date.now()-start});
 result=await forward(envelope({path:'/api/workspace'}));assert.equal(result.statusCode,401);record('unauthenticated workspace rejected by original backend');
 for(const account of access.accounts){
  const login=await forward(envelope({path:'/api/auth/login',method:'POST',data:{login_name:account,password:access.password}}));
  assert.equal(login.statusCode,200,account+' login');assert.ok(login.data.token);
  const workspace=await forward(envelope({path:'/api/workspace',token:login.data.token}));
  assert.equal(workspace.statusCode,200,account+' workspace');assert.ok(workspace.data&&typeof workspace.data==='object');record(account+' real login + scoped workspace');
 }
 await restricted((client,finish)=>client.exec('id',err=>finish(!!err)));record('SSH shell/exec denied');
 await restricted((client,finish)=>client.forwardOut('127.0.0.1',0,'127.0.0.1',5432,err=>finish(!!err)));record('SSH database forwarding denied');
 await assert.rejects(createForward({...config,hostKeySha256:crypto.randomBytes(32).toString('hex')})(envelope({path:'/healthz'})));record('incorrect server host pin rejected');
 fs.writeFileSync(path.join(root,'artifacts/wechat-gateway-live-integration.json'),JSON.stringify({checked_at:new Date().toISOString(),scope:'real dedicated SSH -> original Docker backend; cloud function/phone acceptance separate',checks},null,2)+'\n');
 console.log('LIVE_GATEWAY_CHECKS',checks.length);
})().catch(error=>{console.error('LIVE_GATEWAY_FAILED',error.code||error.message);process.exitCode=1;});
