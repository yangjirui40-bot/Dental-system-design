'use strict';
const { handler } = require('./policy');
const { forward } = require('./https-forward');
const { trustedAppId } = require('./context');

const handle = handler({
  trustedAppId,
  forward(request) {
    // Even a previous patient client which omitted the entry marker uses
    // the same patient boundary. A request cannot select the staff surface.
    if (request.path.split('?')[0] === '/api/auth/login' && request.method === 'POST') {
      const body = JSON.parse(request.body || '{}');
      if (body && typeof body === 'object' && !Array.isArray(body)) {
        request.body = JSON.stringify({ ...body, client_surface: 'patient' });
        request.headers['Content-Length'] = Buffer.byteLength(request.body);
      }
    }
    return forward(request);
  }
});

exports.main = async (event, context) => {
  if (context) context.callbackWaitsForEmptyEventLoop = false;
  return handle(event);
};
