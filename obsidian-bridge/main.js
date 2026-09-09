'use strict';

const { Plugin, PluginSettingTab, Setting, SecretComponent, TFile, Notice } = require('obsidian');
const path = require('node:path');
const fs = require('node:fs/promises');

module.exports = class KnowledgeOrchestratorBridge extends Plugin {
  async onload() {
    this.unloaded = false;
    this.generation = 0;
    this.data = (await this.loadData()) || { secretName: '', port: 8766, enabled: false };
    this.queue = Promise.resolve();
    const folder = path.join(this.app.vault.adapter.getBasePath(), this.manifest.dir);
    this.core = require(path.join(folder, 'bridge-core.cjs'));
    this.transport = require(path.join(folder, 'server.cjs'));
    const { Journal } = require(path.join(folder, 'journal.cjs'));
    this.journal = await new Journal(path.join(folder, 'receipts.jsonl')).load();
    this.addSettingTab(new BridgeSettings(this.app, this));
    this.app.workspace.onLayoutReady(() => this.restart());
  }

  serialized(action) {
    const next = this.queue.catch(() => {}).then(action);
    this.queue = next;
    return next;
  }

  async restart() {
    const generation = ++this.generation;
    if (this.server) { this.server.close(); this.server = null; }
    if (!this.data.enabled || this.unloaded) return;
    const secret = this.app.secretStorage.getSecret(this.data.secretName);
    if (!secret || secret.length < 32) {
      new Notice('El puente necesita una credencial de al menos 32 caracteres.');
      return;
    }
    const root = await fs.realpath(this.app.vault.adapter.getBasePath());
    if (generation !== this.generation || this.unloaded) return;
    const vaultId = this.core.hash(root.replaceAll('\\', '/').toLowerCase());
    const dispatch = (command) => this.serialized(async () => {
      if (!this.data.enabled || this.unloaded) throw new Error('Bridge stopped');
      this.core.validate(command);
      const filePath = await fs.realpath(path.join(root, command.path));
      const relative = path.relative(root, filePath);
      if (relative.startsWith('..') || path.isAbsolute(relative)) {
        throw new this.core.BridgeError('INVALID_REQUEST', 400);
      }
      return this.core.applyCommand({
        vault: this.app.vault,
        isFile: (file) => file instanceof TFile,
        getRecord: (id) => this.journal.get(id),
        putRecord: (id, record) => this.journal.put(id, record),
      }, command);
    });
    this.server = this.transport.makeServer({
      vaultId, dispatch, getSecret: () => this.app.secretStorage.getSecret(this.data.secretName),
    });
    this.server.on('error', () => new Notice('No se pudo abrir el puente local. Compruebe el puerto.'));
    this.server.listen(this.data.port, '127.0.0.1');
  }

  onunload() { this.unloaded = true; this.server?.close(); }
}

class BridgeSettings extends PluginSettingTab {
  constructor(app, plugin) { super(app, plugin); this.bridge = plugin; }
  display() {
    this.containerEl.empty();
    const plugin = this.bridge;
    new Setting(this.containerEl).setName('Permitir propuestas del Orchestrator')
      .setDesc('Solo acepta cambios autenticados cuya base siga coincidiendo. Obsidian debe permanecer abierto.')
      .addToggle((toggle) => toggle.setValue(plugin.data.enabled).onChange(async (enabled) => {
        await plugin.serialized(async () => { plugin.data.enabled = enabled; await plugin.saveData(plugin.data); });
        await plugin.restart();
      }));
    new Setting(this.containerEl).setName('Credencial compartida')
      .setDesc('Seleccione una credencial exclusiva del puente; no use la del Broker.')
      .addComponent((element) => new SecretComponent(this.app, element).setValue(plugin.data.secretName)
        .onChange(async (name) => {
          await plugin.serialized(async () => { plugin.data.secretName = name || ''; await plugin.saveData(plugin.data); });
          await plugin.restart();
        }));
    new Setting(this.containerEl).setName('Puerto local').setDesc('Dirección: 127.0.0.1. Por defecto, 8766.')
      .addText((input) => input.setValue(String(plugin.data.port)).onChange(async (value) => {
        const port = Number(value);
        if (!Number.isInteger(port) || port < 1024 || port > 65535) return;
        await plugin.serialized(async () => { plugin.data.port = port; await plugin.saveData(plugin.data); });
        await plugin.restart();
      }));
  }
}
