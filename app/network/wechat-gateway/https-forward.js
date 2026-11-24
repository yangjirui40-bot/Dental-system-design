'use strict';
const https = require('node:https');
const { GatewayError } = require('./policy');

const API_HOST = 'api.yjr-adc-demo.xyz';
const MAX_RESPONSE_BYTES = 4 * 1024 * 1024;
// Leaves time for CloudBase to return the result within its 3-second limit.
const REQUEST_DEADLINE_MS = 2500;
const agent = new https.Agent({ keepAlive: true, maxSockets: 8, maxFreeSockets: 2 });

function forward(request, send = https.request) {
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const phases = [];
    const record = phase => {
      if (request.diagnostics) phases.push({ phase, ms: Date.now() - started });
    };
    let outgoing;
    let settled = false;
    const finish = (error, result) => {
      if (settled) return;
      settled = true;
      clearTimeout(deadline);
      record(error ? 'failed' : 'completed');
      if (request.diagnostics) (error || result).gatewayDiagnostics = { phases, transport: 'https' };
      if (error) {
        outgoing?.destroy();
        reject(error);
      } else resolve(result);
    };
    const deadline = setTimeout(() => finish(new GatewayError('gateway_timeout', 504)), REQUEST_DEADLINE_MS);
    const failTransport = () => finish(new GatewayError('gateway_unavailable', 502));
    const headers = { ...request.headers, Host: API_HOST, 'X-ADC-Surface': 'patient' };
    delete headers.Connection;
    delete headers['X-Forwarded-Proto'];
    try {
      record('started');
      outgoing = send({ hostname: API_HOST, port: 443, path: request.path, method: request.method, headers, agent }, response => {
        record('http_headers');
        const chunks = [];
        let size = 0;
        response.on('data', chunk => {
          size += chunk.length;
          if (size > MAX_RESPONSE_BYTES) {
            finish(new GatewayError('response_too_large', 502));
            return;
          }
          chunks.push(chunk);
        });
        response.once('error', failTransport);
        response.once('end', () => {
          if (settled) return;
          try {
            const data = JSON.parse(Buffer.concat(chunks).toString('utf8'));
            finish(null, { statusCode: response.statusCode, data });
          } catch {
            finish(new GatewayError('invalid_upstream_response', 502));
          }
        });
      });
      outgoing.once('error', failTransport);
      outgoing.end(request.body || undefined);
    } catch {
      failTransport();
    }
  });
}
module.exports = { forward };
