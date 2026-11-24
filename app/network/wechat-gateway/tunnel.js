'use strict';
const http = require('node:http');
const { timingSafeEqual } = require('node:crypto');
const { Client } = require('ssh2');
const { GatewayError } = require('./policy');
const MAX_RESPONSE = 4194304;
function verifyHost(expected, actual) {
  if (!/^[0-9a-f]{64}$/i.test(expected || '') || !/^[0-9a-f]{64}$/i.test(actual || '')) return false;
  return timingSafeEqual(Buffer.from(expected, 'hex'), Buffer.from(actual, 'hex'));
}
function createForward(config, ClientType = Client) {
  if (config.host !== '123.56.113.16' || config.username !== 'adc_wx_gateway' || !/^[0-9a-f]{64}$/i.test(config.hostKeySha256 || '') || !config.privateKey) throw new GatewayError('gateway_not_configured', 503);
  const timeout = Number(config.timeoutMs || 2600);
  if (!Number.isFinite(timeout) || timeout < 500 || timeout > 12000) throw new GatewayError('invalid_deadline', 503);
  return request => new Promise((resolve, reject) => {
    const started = Date.now(), phases = [{ phase: 'started', ms: 0 }];
    const phase = name => { if (request.diagnostics) phases.push({ phase: name, ms: Date.now() - started }); };
    const client = new ClientType();
    const agent = new http.Agent({ keepAlive: false, maxSockets: 1 });
    let req, finished = false;
    const finish = (error, result) => {
      if (finished) return;
      finished = true; clearTimeout(timer);
      if (request.diagnostics) {
        phase(error ? 'failed' : 'completed');
        if (error) error.gatewayDiagnostics = { phases }; else result.gatewayDiagnostics = { phases };
      }
      if (error && req) req.destroy();
      agent.destroy(); client.destroy();
      error ? reject(error) : resolve(result);
    };
    const timer = setTimeout(() => finish(new GatewayError('gateway_timeout', 504)), timeout);
    agent.createConnection = (_options, callback) => {
      client.forwardOut('127.0.0.1', 0, '127.0.0.1', 8080, (error, stream) => { if (!error) phase('channel_ready'); callback(error, stream); });
    };
    client.once('error', () => finish(new GatewayError('gateway_unavailable', 502)));
    client.once('close', () => { if (!finished) finish(new GatewayError('gateway_unavailable', 502)); });
    client.once('ready', () => {
      phase('ssh_ready');
      req = http.request({ hostname: '127.0.0.1', port: 8080, path: request.path, method: request.method, headers: request.headers, agent }, response => {
        phase('http_headers');
        const chunks = []; let size = 0;
        response.on('data', chunk => {
          size += chunk.length;
          if (size > MAX_RESPONSE) { response.destroy(); finish(new GatewayError('response_too_large', 502)); }
          else chunks.push(chunk);
        });
        response.once('error', () => finish(new GatewayError('gateway_unavailable', 502)));
        response.once('end', () => {
          if (finished) return;
          try { finish(null, { statusCode: response.statusCode, data: JSON.parse(Buffer.concat(chunks).toString('utf8')) }); }
          catch { finish(new GatewayError('invalid_upstream_response', 502)); }
        });
      });
      req.once('error', () => finish(new GatewayError('gateway_unavailable', 502)));
      req.end(request.body || undefined);
    });
    try { client.connect({ host: config.host, port: 22, username: config.username, privateKey: config.privateKey,
      hostHash: 'sha256', hostVerifier: actual => verifyHost(config.hostKeySha256, actual),
      algorithms: { serverHostKey: ['ssh-ed25519'] }, readyTimeout: Math.min(timeout, 1800), keepaliveInterval: 0 }); }
    catch { finish(new GatewayError('gateway_unavailable', 502)); }
  });
}
module.exports = { createForward, verifyHost };
