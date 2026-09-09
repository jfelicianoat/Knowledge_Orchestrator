'use strict';

const fs = require('node:fs/promises');
const DIGEST = /^[a-f0-9]{64}$/;
const STATES = new Set(['PREPARED', 'APPLIED', 'CONFLICT', 'UNCERTAIN']);

class Journal {
  constructor(file) { this.file = file; this.records = new Map(); this.failed = false; }
  async load() {
    let handle;
    try { handle = await fs.open(this.file, 'r+'); }
    catch (error) {
      if (error.code !== 'ENOENT') throw error;
      try { handle = await fs.open(this.file, 'wx+'); }
      catch (created) {
        if (created.code !== 'EEXIST') throw created;
        handle = await fs.open(this.file, 'r+');
      }
    }
    try {
      if ((await handle.stat()).size > 16 * 1024 * 1024) throw new Error('Journal capacity');
      const data = await handle.readFile();
      const end = data.lastIndexOf(10) + 1;
      const lines = data.subarray(0, end).toString('utf8').split('\n').filter(Boolean);
      for (const line of lines) {
        const entry = JSON.parse(line);
        if (!DIGEST.test(entry.id) || !DIGEST.test(entry.fingerprint) || !STATES.has(entry.status)) {
          throw new Error('Invalid journal');
        }
        const previous = this.records.get(entry.id);
        if (previous && (previous.fingerprint !== entry.fingerprint
            || (previous.status !== 'PREPARED' && previous.status !== entry.status))) {
          throw new Error('Invalid journal transition');
        }
        this.records.set(entry.id, { fingerprint: entry.fingerprint, status: entry.status });
      }
      // An interrupted last append is not a receipt. Earlier PREPARED records
      // survive and force reconciliation instead of repeating an uncertain write.
      if (data.length !== end) await handle.truncate(end);
      await handle.sync();
    } finally { await handle.close(); }
    return this;
  }
  async get(id) {
    if (this.failed) throw new Error('Journal requires reload');
    return this.records.get(id);
  }
  async put(id, record) {
    if (this.failed || (!this.records.has(id) && this.records.size >= 10000)) throw new Error('Journal unavailable');
    try {
      const handle = await fs.open(this.file, 'a');
      try {
        await handle.writeFile(`${JSON.stringify({ id, ...record })}\n`);
        await handle.sync();
      } finally { await handle.close(); }
      this.records.set(id, { ...record });
    } catch (error) { this.failed = true; throw error; }
  }
}

module.exports = { Journal };
