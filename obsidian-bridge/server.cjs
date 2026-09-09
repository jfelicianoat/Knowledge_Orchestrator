'use strict';

const http = require('node:http');
const { timingSafeEqual } = require('node:crypto');
const MAX_BODY = 24 * 1024 * 1024;

function authenticated(supplied, secret) {
  if (typeof secret !== 'string' || secret.length < 32 || typeof supplied !== 'string') return false;
  const expected = Buffer.from(`Bearer ${secret}`);
  const actual = Buffer.from(supplied);
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}

function makeServer({ getSecret, dispatch, vaultId }) {
  const server = http.createServer(async (request, response) => {
    const send = (status, data) => {
      response.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
      response.end(JSON.stringify(data));
    };
    try {
      if (request.headers.origin || request.headers.host !== `127.0.0.1:${request.socket.localPort}`
          || !authenticated(request.headers.authorization, getSecret())) {
        send(401, { code: 'AUTH_REQUIRED' });
        request.resume();
        return;
      }
      if (request.method === 'GET' && request.url === '/v1/status') {
        send(200, { protocol: 1, vault_id: vaultId });
        return;
      }
      if (request.method !== 'POST' || request.url !== '/v1/apply') {
        send(404, { code: 'NOT_FOUND' });
        request.resume();
        return;
      }
      if (request.headers['x-ko-vault-id'] !== vaultId) {
        send(409, { code: 'VAULT_MISMATCH' });
        request.resume();
        return;
      }
      if (request.headers['content-type']?.split(';')[0] !== 'application/json') {
        send(415, { code: 'JSON_REQUIRED' });
        request.resume();
        return;
      }
      let size = 0;
      const chunks = [];
      for await (const chunk of request) {
        size += chunk.length;
        if (size > MAX_BODY) {
          send(413, { code: 'REQUEST_TOO_LARGE' });
          return;
        }
        chunks.push(chunk);
      }
      let payload;
      try { payload = JSON.parse(Buffer.concat(chunks).toString('utf8')); }
      catch { send(400, { code: 'INVALID_JSON' }); return; }
      const result = await dispatch(payload);
      send(200, result);
    } catch (error) {
      // No raw error, token, document body or path is reflected into responses/logs.
      const allowed = new Set(['INVALID_REQUEST', 'IDEMPOTENCY_CONFLICT', 'NOTE_NOT_FOUND',
        'NOTE_CHANGED', 'REVIEW_REQUIRED', 'JOURNAL_INVALID']);
      send(allowed.has(error?.code) ? error.status : 503,
        { code: allowed.has(error?.code) ? error.code : 'BRIDGE_UNAVAILABLE' });
    }
  });
  server.requestTimeout = 15000;
  server.headersTimeout = 10000;
  return server;
}

module.exports = { authenticated, makeServer };
