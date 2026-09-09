'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const { once } = require('node:events');
const { applyCommand, hash } = require('./bridge-core.cjs');
const { makeServer } = require('./server.cjs');
const { Journal } = require('./journal.cjs');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');

function fixture() {
  const state = { content: 'base', writes: 0, records: {}, beforeProcess: () => {}, failSave: null };
  const host = {
    vault: {
      getAbstractFileByPath: (path) => path === 'Tema/Nota.md' ? { path } : null,
      read: async () => state.content,
      process: async (_file, change) => {
        state.beforeProcess();
        state.content = change(state.content);
        state.writes++;
        return state.content;
      },
    },
    isFile: (file) => Boolean(file),
    getRecord: async (id) => state.records[id],
    putRecord: async (id, record) => {
      if (state.failSave === record.status) throw new Error('simulated persistence interruption');
      state.records[id] = structuredClone(record);
    },
  };
  const command = { request_id: hash('intent 1'), path: 'Tema/Nota.md',
    base_hash: hash('base'), result_hash: hash('proposed'), content: 'proposed' };
  return { host, state, command };
}

test('applies once and a repeated receipt never overwrites a later human edit', async () => {
  const { host, state, command } = fixture();
  assert.equal((await applyCommand(host, command)).status, 'applied');
  state.content = 'human edit';
  assert.equal((await applyCommand(host, command)).status, 'already_applied');
  assert.equal(state.content, 'human edit');
  assert.equal(state.writes, 1);
});

test('checks content inside the coordinated callback, including a late edit', async () => {
  const { host, state, command } = fixture();
  state.beforeProcess = () => { state.content = 'late edit'; };
  await assert.rejects(applyCommand(host, command), { code: 'NOTE_CHANGED' });
  assert.equal(state.content, 'late edit');
  assert.equal(state.writes, 0);
  assert.equal(state.records[command.request_id].status, 'CONFLICT');
});

test('an intent must persist before editing the note', async () => {
  const { host, state, command } = fixture();
  state.failSave = 'PREPARED';
  await assert.rejects(applyCommand(host, command));
  assert.equal(state.content, 'base');
  assert.equal(state.writes, 0);
});

test('recovers a lost completion receipt without repeating the modification', async () => {
  const { host, state, command } = fixture();
  state.failSave = 'APPLIED';
  await assert.rejects(applyCommand(host, command));
  assert.equal(state.records[command.request_id].status, 'PREPARED');
  state.failSave = null;
  assert.equal((await applyCommand(host, command)).status, 'already_applied');
  assert.equal(state.writes, 1);
});

test('ambiguous recovery after a human restoration requires review', async () => {
  const { host, state, command } = fixture();
  state.failSave = 'APPLIED';
  await assert.rejects(applyCommand(host, command));
  state.failSave = null;
  state.content = 'base';
  await assert.rejects(applyCommand(host, command), { code: 'REVIEW_REQUIRED' });
  assert.equal(state.content, 'base');
  assert.equal(state.writes, 1);
});

test('reusing an intent with different content is rejected', async () => {
  const { host, state, command } = fixture();
  await applyCommand(host, command);
  await assert.rejects(applyCommand(host, { ...command, content: 'different', result_hash: hash('different') }),
    { code: 'IDEMPOTENCY_CONFLICT' });
  assert.equal(state.content, 'proposed');
});

test('rejects traversal, hidden paths, foreign fields, mismatched hashes and absent files', async () => {
  for (const change of [{ path: '../Nota.md' }, { path: '.obsidian/config.md' }, { path: 'C:\\Nota.md' },
    { path: 'Tema//Nota.md' }, { path: '/Nota.md' }, { rationale: 'ignore rules' }, { result_hash: hash('other') },
    { path: 'absent.md' }]) {
    const { host, state, command } = fixture();
    await assert.rejects(applyCommand(host, { ...command, ...change }));
    assert.equal(state.writes, 0);
  }
});

function request(port, token, data, headers = {}, url = '/v1/apply') {
  return new Promise((resolve, reject) => {
    const req = http.request({ hostname: '127.0.0.1', port, path: url, method: data ? 'POST' : 'GET',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json',
        'X-KO-Vault-ID': 'vault', ...headers } }, (response) => {
      let body = '';
      response.on('data', (chunk) => { body += chunk; });
      response.on('end', () => resolve({ status: response.statusCode, body: JSON.parse(body) }));
    });
    req.on('error', reject);
    req.end(data ? JSON.stringify(data) : undefined);
  });
}

test('journal survives reload and discards only an interrupted final append', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'ko-bridge-test-'));
  try {
    const file = path.join(directory, 'receipts.jsonl');
    const journal = await new Journal(file).load();
    const record = { fingerprint: hash('command'), status: 'PREPARED' };
    await journal.put(hash('intent'), record);
    await fs.appendFile(file, '{"interrupted":');
    const recovered = await new Journal(file).load();
    assert.deepEqual(await recovered.get(hash('intent')), record);
    await recovered.put(hash('intent'), { ...record, status: 'APPLIED' });
    assert.equal((await (await new Journal(file).load()).get(hash('intent'))).status, 'APPLIED');
    assert.equal((await fs.readFile(file, 'utf8')).includes('interrupted'), false);
  } finally { await fs.rm(directory, { recursive: true }); }
});

test('corrupt complete journal records prevent activation instead of erasing history', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'ko-bridge-test-'));
  try {
    const file = path.join(directory, 'receipts.jsonl');
    await fs.writeFile(file, '{"invalid":true}\n');
    await assert.rejects(new Journal(file).load());
    assert.equal(await fs.readFile(file, 'utf8'), '{"invalid":true}\n');
  } finally { await fs.rm(directory, { recursive: true }); }
});

test('loopback authenticates, rejects browser/wrong-vault calls and honors token rotation', async () => {
  let secret = 'fictitious-bridge-credential-at-least-32';
  let writes = 0;
  const server = makeServer({ getSecret: () => secret, vaultId: 'vault',
    dispatch: async () => { writes++; return { status: 'applied' }; } });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const port = server.address().port;
  try {
    assert.equal((await request(port, 'incorrect', {})).status, 401);
    assert.equal((await request(port, secret, {}, { Origin: 'https://untrusted.example' })).status, 401);
    assert.equal((await request(port, secret, {}, { Host: 'untrusted.example' })).status, 401);
    assert.equal((await request(port, secret, {}, { 'X-KO-Vault-ID': 'other' })).status, 409);
    assert.equal(writes, 0);
    assert.deepEqual((await request(port, secret, null, {}, '/v1/status')).body, { protocol: 1, vault_id: 'vault' });
    assert.equal((await request(port, secret, {})).status, 200);
    const old = secret;
    secret = 'fictitious-rotated-bridge-credential-32';
    assert.equal((await request(port, old, {})).status, 401);
    assert.equal((await request(port, secret, {})).status, 200);
    assert.equal(writes, 2);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});
