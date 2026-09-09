"""Explicit editor double for domain tests; no production filesystem fallback."""
import hashlib
import json
from pathlib import Path

import httpx

from knowledge_orchestrator.integrations.obsidian_bridge import ObsidianBridgeClient


class FakeNoteEditor(ObsidianBridgeClient):
    def __init__(self, vault: Path):
        self.receipts = {}
        self.requests = []
        super().__init__(vault, 'test-editor-only-' * 3, transport=httpx.MockTransport(self.handle))

    def handle(self, request):
        if request.method == 'GET':
            return httpx.Response(200, json={'protocol': 1, 'vault_id': self.vault_id})
        command = json.loads(request.content)
        self.requests.append(command)
        identifier = command['request_id']
        if identifier in self.receipts:
            if self.receipts[identifier] != command:
                return httpx.Response(409)
            status = 'already_applied'
        else:
            path = self.vault / command['path']
            if hashlib.sha256(path.read_bytes()).hexdigest() != command['base_hash']:
                return httpx.Response(409)
            path.write_bytes(command['content'].encode('utf-8'))
            self.receipts[identifier] = command
            status = 'applied'
        return httpx.Response(200, json={'request_id': identifier, 'status': status,
                                        'result_hash': command['result_hash']})
