'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { APPID, envelope, handler } = require('../policy');
const { verifyHost } = require('../tunnel');
test('forwards actual endpoint, JSON values, bearer and idempotency without changing identity', () => {
  const result = envelope({ path: '/api/appointments/12', method: 'POST', data: { patient_id: 7, remark: '阶段复诊' }, token: 'signed-session', idempotencyKey: 'UC03:123' });
  assert.equal(result.path, '/api/appointments/12'); assert.deepEqual(JSON.parse(result.body), { patient_id: 7, remark: '阶段复诊' });
  assert.equal(result.headers.Authorization, 'Bearer signed-session'); assert.equal(result.headers['Idempotency-Key'], 'UC03:123');
  assert.equal(result.headers.Host, 'api.yjr-adc-demo.xyz');
  assert.equal(result.headers['X-Forwarded-Proto'], 'https');
});
test('preserves encoded slot and audit query parameters', () => {
  const path = '/api/slots?clinic_id=1&day=2026-11-20&kind=checkup'; assert.equal(envelope({ path }).path, path);
});
test('rejects alternate destinations, web assets, ambiguous paths and header injection', () => {
  for (const path of ['https://other.invalid/api/auth/login', '//other.invalid/api/x', '/static/a.jpg', '/api/%2e%2e/healthz', '/api/%2fadmin', '/api/x\\y', '/api/x#fragment']) assert.throws(() => envelope({ path }));
  assert.throws(() => envelope({ path: '/api/workspace', token: 'x\r\nHost: other' }));
});
test('rejects unimplemented methods and oversized input before forwarding', () => {
  assert.throws(() => envelope({ path: '/api/workspace', method: 'DELETE' }));
  assert.throws(() => envelope({ path: '/api/workspace', method: 'GET', data: {} }));
  assert.throws(() => envelope({ path: '/api/auth/register', method: 'POST', data: { name: 'x'.repeat(262144) } }));
});
test('rejects missing or foreign verified caller even if event claims the correct appid', async () => {
  let calls = 0;
  for (const trusted of [undefined, 'foreign']) {
    const invoke = handler({ trustedAppId: () => trusted, forward: async () => { calls++; } });
    assert.equal((await invoke({ path: '/healthz', appid: APPID })).statusCode, 403);
  }
  assert.equal(calls, 0);
});
test('preserves backend denial, revocation and conflict responses', async () => {
  for (const statusCode of [401, 403, 409, 429]) {
    const result = { statusCode, data: { error: 'scope_revoked', message: '原业务拒绝' } };
    const invoke = handler({ trustedAppId: () => APPID, forward: async () => result });
    assert.deepEqual(await invoke({ path: '/api/workspace' }), result);
  }
});
test('does not retry a mutating command or disclose private transport errors', async () => {
  let calls = 0; const privateMarker = 'private-key-and-password-must-not-leak';
  const invoke = handler({ trustedAppId: () => APPID, forward: async () => { calls++; throw new Error(privateMarker); } });
  const result = await invoke({ path: '/api/auth/login', method: 'POST', data: { password: privateMarker } });
  assert.equal(calls, 1); assert.equal(result.statusCode, 502); assert.ok(!JSON.stringify(result).includes(privateMarker));
});
test('requires exact pinned host key, including when caller supplies no or malformed pin', () => {
  const pin = 'ab'.repeat(32); assert.equal(verifyHost(pin, pin), true); assert.equal(verifyHost(pin, 'cd'.repeat(32)), false);
  assert.equal(verifyHost('', pin), false); assert.equal(verifyHost(pin, 'not-a-host-key'), false);
});
