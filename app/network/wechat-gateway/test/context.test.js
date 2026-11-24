'use strict';
const test=require('node:test');const assert=require('node:assert/strict');const {trustedAppId}=require('../context');
test('accepts only AppID declared by the platform context keys, never unlisted lookalikes',()=>{
 assert.equal(trustedAppId({WX_CONTEXT_KEYS:'WX_APPID,WX_OPENID',WX_APPID:'wxf278ca432c9e7224'}),'wxf278ca432c9e7224');
 assert.equal(trustedAppId({WX_CONTEXT_KEYS:'APPID',APPID:'wxf278ca432c9e7224'}),'wxf278ca432c9e7224');
 for(const env of [{},{WX_APPID:'wxf278ca432c9e7224'},{WX_CONTEXT_KEYS:'WX_OPENID',APPID:'wxf278ca432c9e7224'},{WX_CONTEXT_KEYS:'WX_APPID_COPY',WX_APPID:'wxf278ca432c9e7224'}])assert.equal(trustedAppId(env),'');
});
