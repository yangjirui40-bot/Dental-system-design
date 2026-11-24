'use strict';
const APPID = 'wxf278ca432c9e7224';
const MAX_REQUEST = 262144;
class GatewayError extends Error {
  constructor(code, status = 400) { super(code); this.code = code; this.status = status; }
}
function envelope(event) {
  if (!event || typeof event !== 'object' || Array.isArray(event)) throw new GatewayError('invalid_envelope');
  const { path, method = 'GET', data, token = '', idempotencyKey = '' } = event;
  if (typeof path !== 'string' || path.length > 8192 || !path.startsWith('/') || path.startsWith('//') || /[\\\r\n\0#]/.test(path)) throw new GatewayError('invalid_path');
  if (path.split('?')[0].split('/').some(p => p === '.' || p === '..')) throw new GatewayError('invalid_path');
  let url, decoded;
  try { url = new URL(path, 'http://adc.internal'); decoded = decodeURIComponent(url.pathname); }
  catch { throw new GatewayError('invalid_path'); }
  if (url.origin !== 'http://adc.internal' || /[\\\r\n\0]/.test(decoded) || decoded.split('/').some(p => p === '.' || p === '..') || /(?:%2e|%2f|%5c)/i.test(path.split('?')[0])) throw new GatewayError('invalid_path');
  if (decoded !== '/healthz' && !/^\/api\/[a-zA-Z0-9_/-]+$/.test(decoded)) throw new GatewayError('path_not_allowed', 403);
  if (!['GET', 'POST'].includes(method)) throw new GatewayError('method_not_allowed', 405);
  if (method === 'GET' && data !== undefined) throw new GatewayError('unexpected_get_body');
  for (const [value, max] of [[token, 8192], [idempotencyKey, 200]]) {
    if (typeof value !== 'string' || value.length > max || /[\r\n\0]/.test(value)) throw new GatewayError('invalid_header');
  }
  let body;
  try { body = data === undefined ? '' : JSON.stringify(data); }
  catch { throw new GatewayError('invalid_json'); }
  if (typeof body !== 'string' || Buffer.byteLength(body) > MAX_REQUEST) throw new GatewayError('request_too_large', 413);
  return { path: url.pathname + url.search, method, body, diagnostics: event.diagnostics === true, headers: {
    Host: 'api.yjr-adc-demo.xyz', Accept: 'application/json', 'Content-Type': 'application/json', Connection: 'close', 'X-Forwarded-Proto': 'https',
    ...(body ? { 'Content-Length': Buffer.byteLength(body) } : {}),
    ...(token ? { Authorization: 'Bearer ' + token } : {}),
    ...(idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {})
  } };
}
function handler({ trustedAppId, forward }) {
  return async event => {
    try {
      if (await trustedAppId() !== APPID) throw new GatewayError('caller_not_allowed', 403);
      const request = envelope(event);
      return await forward(request);
    } catch (error) {
      const code = error instanceof GatewayError ? error.code : 'gateway_unavailable';
      const status = error instanceof GatewayError ? error.status : 502;
      // No event, password, bearer, WX context, SSH key, or upstream error text is logged/returned.
      const message = code === 'gateway_timeout' ? '服务响应超时。请刷新确认办理结果后再试。' : status === 502 ? '联调服务暂时无法连接，请稍后重试。' : '请求未通过联调入口校验。';
      return { statusCode: status, data: { error: code, message }, ...(error instanceof GatewayError && error.gatewayDiagnostics ? { gatewayDiagnostics: error.gatewayDiagnostics } : {}) };
    }
  };
}
module.exports = { APPID, GatewayError, envelope, handler };
