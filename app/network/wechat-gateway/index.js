'use strict';
const moduleStarted = Date.now();
const fs = require('node:fs');
const path = require('node:path');
const { handler } = require('./policy');
const { createForward } = require('./tunnel');
const { trustedAppId } = require('./context');
const moduleLoadMs = Date.now() - moduleStarted;
let configured;
exports.main = async (event, context) => {
  // SCF may otherwise wait on SDK housekeeping sockets after our awaited
  // request has completed. No business work is left running in the background.
  if (context) context.callbackWaitsForEmptyEventLoop = false;
  const started = Date.now();
  const healthCheck = event && event.path === '/healthz';
  if (healthCheck) console.info('ADC_GATEWAY_HEALTH', 'entered');
  if (!configured) {
    // This server-only file is generated into a private deployment directory.
    // It is never stored alongside the public source or client build.
    let config;
    try { config = JSON.parse(fs.readFileSync(path.join(__dirname, 'runtime-config.json'), 'utf8')); }
    catch { return { statusCode: 503, data: { error: 'gateway_not_configured', message: '联调入口尚未完成配置。' } }; }
    try { configured = handler({ trustedAppId, forward: createForward(config) }); }
    catch { return { statusCode: 503, data: { error: 'gateway_not_configured', message: '联调入口尚未完成配置。' } }; }
  }
  const result = await configured(event);
  if (healthCheck) console.info('ADC_GATEWAY_HEALTH', 'completed', Date.now() - started, result.statusCode);
  if (event && event.diagnostics === true) result.gatewayDiagnostics = { ...result.gatewayDiagnostics, moduleLoadMs, requestMs: Date.now() - started };
  return result;
};
