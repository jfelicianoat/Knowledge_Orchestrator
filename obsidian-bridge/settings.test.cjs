'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const http = require('node:http');
const { once } = require('node:events');
const { hash } = require('./bridge-core.cjs');
const { makeServer } = require('./server.cjs');

// The Obsidian host is replaced; the plugin's startup and loopback listener are real.
async function fixture(t) {
  const folder = await fs.mkdtemp(path.join(os.tmpdir(), 'ko-bridge-settings-'));
  const notices = [];
  const context = { module: { exports: {} }, require(name) {
    if (name === 'obsidian') return {
      Plugin: class {}, PluginSettingTab: class {}, Setting: class {},
      SecretComponent: class {}, TFile: class {}, Notice: class {
        constructor(message) { notices.push(message); }
      },
    };
    return require(name);
  } };
  vm.runInNewContext(await fs.readFile(path.join(__dirname, 'main.js'), 'utf8'), context);
  const plugin = new context.module.exports();
  let value = null;
  Object.assign(plugin, {
    app: { vault: { adapter: { getBasePath: () => folder } }, secretStorage: { getSecret: () => value } },
    data: { enabled: true, port: 0, secretName: 'fictitious-label' },
    generation: 0, unloaded: false, queue: Promise.resolve(),
    core: { hash }, transport: { makeServer },
  });
  const rendered = [];
  plugin.statusSetting = { setDesc: (message) => rendered.push(message) };
  t.after(async () => {
    plugin.onunload();
    if (plugin.server) await new Promise(resolve => plugin.server.close(resolve));
    await fs.rm(folder, { recursive: true, force: true });
  });
  return { plugin, notices, rendered, setSecret: (secret) => { value = secret; } };
}

test('a selected name with an absent, short or multiline value never claims to listen', async t => {
  const { plugin, notices, rendered, setSecret } = await fixture(t);
  for (const value of [null, 'short-private-value', 'x'.repeat(32) + '\n']) {
    setSecret(value);
    await plugin.restart();
    assert.equal(plugin.server, null);
    assert.match(plugin.status, /VALOR.*32/);
    assert.equal(rendered.at(-1), plugin.status);
  }
  assert.ok(notices.every(message => !message.includes('short-private-value')));
  assert.ok(notices.every(message => !message.includes(plugin.data.secretName)));
});

test('rereads an edited secret and reports a real listener only after the listening event', async t => {
  const { plugin, rendered, setSecret } = await fixture(t);
  await plugin.restart();
  setSecret('fictitious-bridge-credential-1234567890');
  await plugin.restart();
  const server = plugin.server;
  if (!server.listening) await once(server, 'listening');
  assert.match(plugin.status, /Escuchando/);
  const address = server.address();
  const status = await new Promise((resolve, reject) => {
    http.get(`http://127.0.0.1:${address.port}/v1/status`, response => {
      response.resume();
      resolve(response.statusCode);
    }).on('error', reject);
  });
  assert.equal(status, 401);
  assert.equal(rendered.at(-1), plugin.status);
  plugin.data.enabled = false;
  await plugin.restart();
  assert.equal(server.listening, false);
  assert.equal(plugin.status, 'Desactivado.');
});

test('an occupied port and secret-store exceptions remain visible without private error details', async t => {
  const { plugin, setSecret, notices } = await fixture(t);
  const busy = http.createServer();
  busy.listen(0, '127.0.0.1');
  await once(busy, 'listening');
  t.after(() => new Promise(resolve => busy.close(resolve)));
  setSecret('fictitious-bridge-credential-1234567890');
  plugin.data.port = busy.address().port;
  await plugin.restart();
  if (plugin.server.listening) assert.fail('Unexpected listener on occupied port');
  await once(plugin.server, 'error');
  assert.match(plugin.status, /No se pudo abrir el puerto/);
  plugin.app.secretStorage.getSecret = () => { throw new Error('PRIVATE-STORE-DETAIL'); };
  await plugin.restart();
  assert.match(plugin.status, /No se pudo iniciar/);
  assert.ok(notices.every(message => !message.includes('PRIVATE-STORE-DETAIL')));
});

test('an obsolete server cannot overwrite the status after retry or unload', async t => {
  const { plugin, setSecret } = await fixture(t);
  setSecret('fictitious-bridge-credential-1234567890');
  await plugin.restart();
  const old = plugin.server;
  if (!old.listening) await once(old, 'listening');
  plugin.data.port = old.address().port;
  await Promise.all([plugin.restart(), plugin.restart()]);
  const current = plugin.server;
  if (!current.listening) await once(current, 'listening');
  const ready = plugin.status;
  old.emit('error', new Error('obsolete'));
  assert.equal(plugin.status, ready);
  plugin.onunload();
  current.emit('listening');
  assert.equal(plugin.status, 'Desactivado.');
});
