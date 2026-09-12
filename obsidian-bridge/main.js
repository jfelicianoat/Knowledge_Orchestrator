'use strict';

const { Plugin, PluginSettingTab, Setting, SecretComponent, TFile, Notice } = require('obsidian');
const path = require('node:path');
const fs = require('node:fs/promises');

module.exports = class KnowledgeOrchestratorBridge extends Plugin {
  async onload() {
    this.unloaded = false;
    this.generation = 0;
    this.status = 'Desactivado.';
    this.data = (await this.loadData()) || { secretName: '', port: 8767, enabled: false };
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

  setStatus(message) {
    this.status = message;
    this.statusSetting?.setDesc(message);
  }

  async restart() {
    const generation = ++this.generation;
    const previous = this.server;
    this.server = null;
    this.setStatus(this.data.enabled && !this.unloaded ? 'Iniciando conexión local…' : 'Desactivado.');
    if (previous) await new Promise((resolve) => previous.close(resolve));
    if (generation !== this.generation || !this.data.enabled || this.unloaded) return;
    try {
      await this.startListener(generation);
    } catch {
      if (generation !== this.generation || this.unloaded) return;
      this.server?.close();
      this.server = null;
      this.setStatus('No se pudo iniciar el puente. Comprueba el secreto, la carpeta de la bóveda y el puerto.');
      new Notice(this.status);
    }
  }

  async startListener(generation) {
    const secret = this.app.secretStorage.getSecret(this.data.secretName);
    if (typeof secret !== 'string' || secret.length < 32 || /[\r\n]/.test(secret)) {
      this.setStatus('Falta una clave válida: el VALOR del secreto debe tener al menos 32 caracteres, en una sola línea. El nombre es solo una etiqueta.');
      new Notice(this.status);
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
    const server = this.transport.makeServer({
      vaultId, dispatch, getSecret: () => this.app.secretStorage.getSecret(this.data.secretName),
    });
    this.server = server;
    const current = () => generation === this.generation && !this.unloaded && this.server === server;
    server.on('error', () => {
      if (!current()) return;
      this.setStatus('No se pudo abrir el puerto local. Comprueba si otra aplicación lo está usando.');
      new Notice(this.status);
    });
    server.once('listening', () => {
      if (!current()) return;
      const address = server.address();
      this.setStatus(`Escuchando en http://127.0.0.1:${address.port}. Falta comprobar la conexión desde el Orchestrator.`);
    });
    server.on('close', () => {
      if (current()) this.setStatus('La conexión local se ha cerrado. Pulsa Reintentar conexión.');
    });
    server.listen(this.data.port, '127.0.0.1');
  }

  onunload() {
    this.unloaded = true;
    this.generation++;
    this.server?.close();
    this.setStatus('Desactivado.');
  }
}

class BridgeSettings extends PluginSettingTab {
  constructor(app, plugin) { super(app, plugin); this.bridge = plugin; }
  display() {
    this.containerEl.empty();
    const plugin = this.bridge;
    plugin.statusSetting = new Setting(this.containerEl).setName('Estado del puente')
      .setDesc(plugin.status)
      .addButton((button) => button.setButtonText('Reintentar conexión').onClick(() => plugin.restart()));
    new Setting(this.containerEl).setName('Permitir propuestas del Orchestrator')
      .setDesc('Solo acepta cambios autenticados cuya base siga coincidiendo. Obsidian debe permanecer abierto.')
      .addToggle((toggle) => toggle.setValue(plugin.data.enabled).onChange(async (enabled) => {
        await plugin.serialized(async () => { plugin.data.enabled = enabled; await plugin.saveData(plugin.data); });
        await plugin.restart();
      }));
    new Setting(this.containerEl).setName('Credencial compartida')
      .setDesc('El nombre identifica el secreto. Su VALOR debe ser una clave de al menos 32 caracteres, distinta de la del Broker. Tras editarla en el Llavero, pulsa Reintentar conexión.')
      .addComponent((element) => new SecretComponent(this.app, element).setValue(plugin.data.secretName)
        .onChange(async (name) => {
          await plugin.serialized(async () => { plugin.data.secretName = name || ''; await plugin.saveData(plugin.data); });
          await plugin.restart();
        }));
    new Setting(this.containerEl).setName('Puerto local')
      .setDesc('Dirección: 127.0.0.1. Instalaciones nuevas: 8767. Usa un puerto distinto al de la API del Orchestrator.')
      .addText((input) => input.setValue(String(plugin.data.port)).onChange(async (value) => {
        const port = Number(value);
        if (!Number.isInteger(port) || port < 1024 || port > 65535) return;
        await plugin.serialized(async () => { plugin.data.port = port; await plugin.saveData(plugin.data); });
        await plugin.restart();
      }));
  }
}
