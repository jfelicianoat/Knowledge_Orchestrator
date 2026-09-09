'use strict';

const { createHash } = require('node:crypto');
const hash = (text) => createHash('sha256').update(text, 'utf8').digest('hex');
const digest = /^[a-f0-9]{64}$/;

class BridgeError extends Error {
  constructor(code, status = 409) {
    super(code);
    this.code = code;
    this.status = status;
  }
}

function validate(command) {
  const keys = ['request_id', 'path', 'base_hash', 'result_hash', 'content'];
  if (!command || typeof command !== 'object' || Array.isArray(command)
      || Object.keys(command).sort().join() !== [...keys].sort().join()
      || !keys.every((key) => typeof command[key] === 'string')
      || !digest.test(command.request_id) || !digest.test(command.base_hash)
      || !digest.test(command.result_hash) || hash(command.content) !== command.result_hash
      || command.content.includes('\0') || Buffer.byteLength(command.content, 'utf8') > 20 * 1024 * 1024
      || !command.path.endsWith('.md') || /[\\:\x00-\x1f]/.test(command.path)
      || command.path.split('/').some((part) => !part || part.startsWith('.') || part.endsWith(' '))) {
    throw new BridgeError('INVALID_REQUEST', 400);
  }
  return hash(JSON.stringify(keys.map((key) => command[key])));
}

// The host serializes calls and persists journal records before acknowledging writes.
async function applyCommand(host, command) {
  const fingerprint = validate(command);
  const prior = await host.getRecord(command.request_id);
  if (prior && prior.fingerprint !== fingerprint) throw new BridgeError('IDEMPOTENCY_CONFLICT');
  const file = host.vault.getAbstractFileByPath(command.path);
  if (!host.isFile(file)) throw new BridgeError('NOTE_NOT_FOUND', 404);
  if (prior) {
    if (prior.status === 'CONFLICT') throw new BridgeError('NOTE_CHANGED');
    if (prior.status === 'UNCERTAIN') throw new BridgeError('REVIEW_REQUIRED');
    if (prior.status === 'PREPARED') {
      // The process may have stopped immediately before OR after writing. Do not
      // reapply when the old content has returned: a human might have restored it.
      if (hash(await host.vault.read(file)) !== command.result_hash) {
        await host.putRecord(command.request_id, { fingerprint, status: 'UNCERTAIN' });
        throw new BridgeError('REVIEW_REQUIRED');
      }
      await host.putRecord(command.request_id, { fingerprint, status: 'APPLIED' });
    } else if (prior.status !== 'APPLIED') {
      throw new BridgeError('JOURNAL_INVALID', 503);
    }
    return { request_id: command.request_id, status: 'already_applied', result_hash: command.result_hash };
  }
  await host.putRecord(command.request_id, { fingerprint, status: 'PREPARED' });
  let completed;
  try {
    completed = await host.vault.process(file, (current) => {
      if (hash(current) !== command.base_hash) throw new BridgeError('NOTE_CHANGED');
      return command.content;
    });
  } catch (error) {
    const conflict = error instanceof BridgeError && error.code === 'NOTE_CHANGED';
    await host.putRecord(command.request_id, { fingerprint, status: conflict ? 'CONFLICT' : 'UNCERTAIN' });
    throw new BridgeError(conflict ? 'NOTE_CHANGED' : 'REVIEW_REQUIRED');
  }
  if (hash(completed) !== command.result_hash) throw new BridgeError('REVIEW_REQUIRED');
  await host.putRecord(command.request_id, { fingerprint, status: 'APPLIED' });
  return { request_id: command.request_id, status: 'applied', result_hash: command.result_hash };
}

module.exports = { applyCommand, BridgeError, hash, validate };
