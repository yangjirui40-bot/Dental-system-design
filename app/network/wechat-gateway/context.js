'use strict';
// Mirrors only the APPID extraction in the official wx-server-sdk4.0.2
// getWXContext implementation. The SDK reads declared WX_CONTEXT_KEYS from
// the platform environment; event.APPID/openid are never authentication.
// No CloudBase DB/storage SDK is needed for this transport-only function.
function trustedAppId(environment = process.env) {
  const declared = String(environment.WX_CONTEXT_KEYS || '').split(',');
  if (declared.includes('WX_APPID')) return environment.WX_APPID || '';
  if (declared.includes('APPID')) return environment.APPID || '';
  return '';
}
module.exports = { trustedAppId };
