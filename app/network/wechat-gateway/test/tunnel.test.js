'use strict';
const test=require('node:test');const assert=require('node:assert/strict');
const http=require('node:http');const net=require('node:net');const {EventEmitter}=require('node:events');
const {createForward}=require('../tunnel');const {envelope}=require('../policy');
const config={host:'123.56.113.16',username:'adc_wx_gateway',hostKeySha256:'a'.repeat(64),privateKey:'test-only-injected-key',timeoutMs:500};
async function upstream(responder,run){
 const server=http.createServer(responder);const sockets=new Set();
 server.on('connection',socket=>{sockets.add(socket);socket.once('close',()=>sockets.delete(socket));});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const instances=[];
 class Tunnel extends EventEmitter{
  constructor(){super();this.channels=[];this.destroyed=0;instances.push(this);}
  connect(options){this.options=options;queueMicrotask(()=>this.emit('ready'));}
  forwardOut(source,port,destination,target,callback){
   assert.equal(destination,'127.0.0.1');assert.equal(target,8080);
   const socket=net.connect(server.address().port,'127.0.0.1');this.channels.push(socket);
   socket.once('connect',()=>callback(null,socket));socket.once('error',error=>callback(error));
  }
  destroy(){this.destroyed++;for(const socket of this.channels)socket.destroy();}
 }
 try{await run(createForward(config,Tunnel),instances);}
 finally{for(const socket of sockets)socket.destroy();await new Promise(resolve=>server.close(resolve));}
}
test('actual HTTP stream preserves JSON, Unicode, status and request headers then closes the tunnel',async()=>{
 await upstream((req,res)=>{assert.equal(req.url,'/api/auth/login');assert.equal(req.headers.host,'api.yjr-adc-demo.xyz');assert.equal(req.headers['x-forwarded-proto'],'https');assert.equal(req.headers.authorization,'Bearer one');let body='';req.on('data',x=>body+=x);req.on('end',()=>{assert.equal(JSON.parse(body).login_name,'测试患者');res.writeHead(401,{'Content-Type':'application/json'});res.end(JSON.stringify({error:'invalid_credentials',message:'验证失败'}));});},async(forward,instances)=>{
  const reply=await forward(envelope({path:'/api/auth/login',method:'POST',data:{login_name:'测试患者'},token:'one'}));assert.equal(reply.statusCode,401);assert.equal(reply.data.message,'验证失败');assert.equal(instances[0].destroyed,1);assert.deepEqual(instances[0].options.algorithms.serverHostKey,['ssh-ed25519']);
 });
});
test('HTML or redirect responses are rejected and never followed',async()=>{
 await upstream((_req,res)=>{res.writeHead(302,{Location:'https://elsewhere.invalid/'});res.end('<html>not JSON</html>');},async(forward,instances)=>{await assert.rejects(forward(envelope({path:'/healthz'})),e=>e.code==='invalid_upstream_response');assert.equal(instances.length,1);assert.equal(instances[0].destroyed,1);});
});
test('oversized upstream response is bounded and destroys its socket',async()=>{
 await upstream((_req,res)=>res.end(Buffer.alloc(4194305,'x')),async(forward,instances)=>{await assert.rejects(forward(envelope({path:'/healthz'})),e=>e.code==='response_too_large');assert.equal(instances[0].destroyed,1);});
});
test('unresponsive upstream reaches deadline, closes tunnel and never retries POST',async()=>{
 await upstream(()=>{},async(forward,instances)=>{await assert.rejects(forward(envelope({path:'/api/appointments',method:'POST',data:{}})),e=>e.code==='gateway_timeout');assert.equal(instances.length,1);assert.equal(instances[0].destroyed,1);});
});
test('SSH ready timeout is bounded even if the library never emits ready or error',async()=>{
 let destroyed=0;
 class Silent extends EventEmitter{connect(){}destroy(){destroyed++;}}
 await assert.rejects(createForward(config,Silent)(envelope({path:'/healthz'})),e=>e.code==='gateway_timeout');assert.equal(destroyed,1);
});
test('synchronous SSH setup failure is sanitized and cleaned up',async()=>{
 let destroyed=0;
 class Broken extends EventEmitter{connect(){throw Error('private key details');}destroy(){destroyed++;}}
 await assert.rejects(createForward(config,Broken)(envelope({path:'/healthz'})),e=>e.code==='gateway_unavailable'&&!e.message.includes('private'));assert.equal(destroyed,1);
});
