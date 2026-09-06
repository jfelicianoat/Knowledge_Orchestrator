from __future__ import annotations

import socket
import sqlite3
import tempfile
import threading
import time
import tkinter as tk
import unittest
from contextlib import closing
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import Mock, patch

import httpx

from knowledge_orchestrator.api.application import KnowledgeApi
from knowledge_orchestrator.api.auth import ApiAuth
from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.domain.knowledge import KnowledgeConflict
from knowledge_orchestrator.domain.monitoring import FetchResult, SourceConfig, SourceError, SourceItem
from knowledge_orchestrator.integrations.source_connectors import RssConnector, WebConnector, html_text
from knowledge_orchestrator.integrations.source_http import SourceHttpClient, SourceResponse, public_addresses
from knowledge_orchestrator.runtime import build_runtime
from knowledge_orchestrator.services.file_stability import FileStabilityChecker
from knowledge_orchestrator.services.source_monitoring import SourceMonitoringService
from knowledge_orchestrator.ui.dashboard import OrchestratorDashboard


class StaticHttp:
    def __init__(self, body: str, content_type='text/html'):
        self.response = SourceResponse(200, body.encode(), {'content-type': content_type}, 'https://example.org/feed')
        self.calls = []

    def fetch(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runtime = build_runtime(PipelinePaths.under(Path(self.temp.name)))
        self.repo = self.runtime.sources.repository
        self.config = SourceConfig('Documentación', 'web', 'https://example.org/docs')

    def create(self, **kwargs):
        return self.repo.create(replace(self.config, **kwargs), actor='tester', key=str(len(self.repo.list_sources())))

    def finish(self, content='Versión 1', *, now=1000):
        job = self.repo.lease_due(now=now)[0]
        result = FetchResult((SourceItem('stable', 'Release', content, self.config.location),), etag='"v1"')
        self.assertTrue(self.repo.finish(job, result, now=now + 1))
        return job

    def count(self, table):
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            return connection.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]

    def test_default_review_dedup_and_return_to_earlier_content(self):
        source = self.create()
        self.finish(now=1000)
        self.finish(now=5000)
        self.assertEqual(self.count('source_changes'), 1)
        self.assertEqual(self.repo.history(source['source_id'])[0]['status'], 'UNCHANGED')
        self.finish('Versión 2', now=9000)
        self.finish('Versión 1', now=13000)
        changes = self.repo.changes()
        self.assertEqual(len(changes), 3)
        self.assertEqual(changes[0]['content_hash'], changes[2]['content_hash'])
        self.assertNotEqual(changes[0]['change_id'], changes[2]['change_id'])
        self.assertEqual(changes[0]['previous_hash'], changes[1]['content_hash'])
        self.assertEqual({row['status'] for row in changes}, {'REVIEW'})
        self.assertEqual(self.runtime.sources.deliver_ready(), 0)
        self.assertEqual(self.count('api_ingestions'), 0)
        self.assertEqual(self.count('knowledge_claims'), 0)

    def test_idempotent_creation_versioning_and_stale_result(self):
        source = self.repo.create(self.config, actor='ui', key='one')
        self.assertEqual(source['source_id'], self.repo.create(self.config, actor='ui', key='one')['source_id'])
        with self.assertRaises(KnowledgeConflict):
            self.repo.create(replace(self.config, name='different'), actor='ui', key='one')
        job = self.repo.lease_due(now=100)[0]
        changed = self.repo.update(source['source_id'], replace(self.config, enabled=False),
                                   expected_revision=1, actor='ui')
        self.assertEqual(changed['revision'], 2)
        self.assertFalse(self.repo.finish(job, FetchResult(), now=101))
        self.assertEqual(self.repo.history(source['source_id'])[0]['status'], 'SUPERSEDED')
        self.assertEqual(self.repo.lease_due(now=200), [])
        with self.assertRaises(KnowledgeConflict):
            self.repo.update(source['source_id'], self.config, expected_revision=1, actor='ui')
        with self.runtime.database.transaction() as connection, self.assertRaises(sqlite3.IntegrityError):
            connection.execute("UPDATE source_revisions SET actor='forged'")

    def test_lease_recovery_does_not_accept_late_worker_or_duplicate_check(self):
        self.create()
        original = self.repo.lease_due(now=100)[0]
        self.assertEqual(self.repo.lease_due(now=120), [])
        restarted = build_runtime(self.runtime.paths)
        newer = restarted.sources.repository.lease_due(now=191)[0]
        self.assertNotEqual(original['check_id'], newer['check_id'])
        self.assertFalse(self.repo.finish(original, FetchResult(), now=192))
        self.assertTrue(self.repo.finish(newer, FetchResult(), now=192))
        self.assertFalse(self.repo.finish(newer, FetchResult(), now=193))
        self.assertEqual(self.count('source_checks'), 2)

    def test_backoff_one_error_does_not_block_other_source(self):
        failing = self.create()
        healthy = self.create(location='https://example.org/good')
        client = StaticHttp('<p>Documentación útil</p>')

        class SelectiveConnector(WebConnector):
            def fetch(self, config, **kwargs):
                if config.location.endswith('/docs'):
                    raise SourceError('HTTP_503')
                return super().fetch(config, **kwargs)

        service = SourceMonitoringService(self.repo, self.runtime.api_ingestion,
                                          {'web': SelectiveConnector(client)})
        now = time.time()
        for job in self.repo.lease_due(now=now):
            service.check(job)
        row = self.repo.get(failing['source_id'])
        self.assertEqual(row['failures'], 1)
        self.assertEqual(row['last_error_code'], 'HTTP_503')
        self.assertGreaterEqual(row['next_check_at'], now + 60)
        self.assertEqual(self.repo.history(healthy['source_id'])[0]['status'], 'CHANGED')
        later = row['next_check_at'] + 1
        job = self.repo.lease_due(now=later)[0]
        self.repo.finish(job, None, now=later + 1, error='HTTP_503')
        self.assertEqual(self.repo.get(failing['source_id'])['next_check_at'], later + 121)

    def test_304_preserves_hash_and_conditional_headers(self):
        source = self.create()
        self.finish()
        before = self.repo.get(source['source_id'])
        job = self.repo.lease_due(now=5000)[0]
        self.repo.finish(job, FetchResult(not_modified=True), now=5001)
        after = self.repo.get(source['source_id'])
        self.assertEqual(before['last_known_hash'], after['last_known_hash'])
        self.assertEqual(after['etag'], '"v1"')
        self.assertEqual(self.count('source_changes'), 1)

    def test_delivery_recovers_crash_between_receipt_and_link_with_provenance(self):
        self.create(ingestion_policy='ingest', trust_level=90, source_role='official_documentation')
        self.finish()
        with patch.object(self.repo, 'delivered', side_effect=RuntimeError('crash')), self.assertRaises(RuntimeError):
            self.runtime.sources.deliver_ready()
        self.assertEqual(self.count('api_ingestions'), 1)
        restarted = build_runtime(self.runtime.paths)
        self.assertEqual(restarted.sources.deliver_ready(), 1)
        restarted.api_ingestion.deliver_pending()
        self.assertEqual(self.count('api_ingestions'), 1)
        self.assertEqual(len(list(self.runtime.paths.inbox.glob('*.md'))), 1)
        change = self.repo.change(self.repo.changes()[0]['change_id'])
        self.assertEqual(change['status'], 'DELIVERED')
        self.assertEqual(change['provenance']['trust_level'], 90)
        source = self.repo.list_sources()[0]
        self.repo.update(source['source_id'], replace(self.config, trust_level=5), expected_revision=1, actor='ui')
        self.assertEqual(self.repo.change(change['change_id'])['provenance']['trust_level'], 90)
        self.runtime.ingestion.stability_checker = FileStabilityChecker(interval_seconds=0, sleep=lambda _: None)
        path = next(self.runtime.paths.inbox.glob('*.md'))
        self.assertTrue(self.runtime.ingestion.ingest(path).accepted)
        source = self.runtime.knowledge_access.source(path.stem)
        self.assertEqual(source['monitoring']['source_change_id'], change['change_id'])
        self.assertEqual(source['monitoring']['trust_level'], 90)

    def test_ingestion_error_has_backoff_and_does_not_block_other_changes(self):
        self.create(ingestion_policy='ingest')
        self.finish('Bad', now=1000)
        self.finish('Good', now=5000)
        original = self.runtime.api_ingestion.create

        def selective(payload, **kwargs):
            if payload['content'] == 'Bad':
                raise ValueError('sensitive remote text')
            return original(payload, **kwargs)

        with patch.object(self.runtime.api_ingestion, 'create', side_effect=selective):
            self.assertEqual(self.runtime.sources.deliver_ready(), 1)
        failed = self.repo.change(self.repo.changes()[-1]['change_id'])
        self.assertEqual(failed['delivery_error'], 'INGESTION_ERROR')
        self.assertGreater(failed['next_delivery_at'], time.time())
        self.assertEqual(self.runtime.sources.deliver_ready(), 0)
        with patch('knowledge_orchestrator.services.source_monitoring.time.time', return_value=time.time() + 61):
            self.assertEqual(self.runtime.sources.deliver_ready(), 1)

    def test_atomic_change_batch_rolls_back_before_retry(self):
        self.create()
        job = self.repo.lease_due(now=100)[0]
        item = SourceItem('same', 'Release', 'One', self.config.location)
        duplicate = replace(item, content='Two')
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.finish(job, FetchResult((item, duplicate)), now=101)
        self.assertEqual(self.count('source_changes'), 0)
        self.assertEqual(self.count('source_items'), 0)
        self.assertTrue(self.repo.finish(job, FetchResult((item,)), now=102))
        self.assertEqual(self.count('source_changes'), 1)

    def test_worker_checks_other_sources_while_one_is_waiting_without_broker(self):
        blocked = self.create()
        other = self.create(location='https://example.org/other')
        release = threading.Event()
        entered = threading.Event()
        client = StaticHttp('<p>Contenido</p>')

        class SlowConnector(WebConnector):
            def fetch(self, config, **kwargs):
                if config.location.endswith('/docs'):
                    entered.set()
                    release.wait(4)
                return super().fetch(config, **kwargs)

        self.runtime.sources.connectors = {'web': SlowConnector(client)}
        worker = self.runtime.source_worker
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not self.repo.get(other['source_id'])['last_checked_at']:
                time.sleep(0.02)
            self.assertIsNotNone(self.repo.get(other['source_id'])['last_checked_at'])
            self.assertIsNone(self.repo.get(blocked['source_id'])['last_checked_at'])
        finally:
            release.set()
            worker.stop()
            for check in worker._checks:
                check.join(3)

    def test_sources_ui_empty_selection_and_ingestion_action(self):
        try:
            probe = tk.Tk()
        except tk.TclError as error:
            if "Can't find a usable init.tcl" in str(error) or 'no display name' in str(error):
                self.skipTest('Tcl/Tk no disponible en este entorno; requiere validación visual local')
            raise
        probe.destroy()
        window = OrchestratorDashboard(self.runtime)
        window.withdraw()
        self.addCleanup(window.destroy)
        self.assertIn('Sin fuentes', window.source_summary.get())
        source = self.create()
        self.finish()
        window._refresh_sources()
        window.sources_tree.selection_set(str(source['source_id']))
        window._refresh_source_changes()
        change = window.source_changes_tree.get_children()[0]
        window.source_changes_tree.selection_set(change)
        window._preview_source_change()
        self.assertIn('Versión 1', window.source_preview.get('1.0', 'end'))
        window._ingest_source_change()
        self.assertEqual(self.repo.change(change)['status'], 'READY')
        window._edit_source(edit=True)
        dialog = next(child for child in window.winfo_children() if isinstance(child, tk.Toplevel))
        self.assertEqual(dialog.title(), 'Editar fuente')
        dialog.destroy()
        window.update_idletasks()

    def test_explicit_ingestion_does_not_approve_or_create_claims(self):
        self.create()
        self.finish()
        change = self.repo.changes()[0]
        self.repo.queue_ingestion(change['change_id'], actor='ui')
        self.repo.queue_ingestion(change['change_id'], actor='ui')
        self.runtime.sources.deliver_ready()
        self.assertEqual(self.count('api_ingestions'), 1)
        self.assertEqual(self.count('knowledge_claims'), 0)
        self.assertEqual(self.count('update_candidates'), 0)

    def test_check_request_idempotent_and_disabled_source_not_run(self):
        source = self.create()
        self.repo.request_check(source['source_id'], actor='ui', key='repeat')
        self.finish()
        after = self.repo.get(source['source_id'])
        self.repo.request_check(source['source_id'], actor='ui', key='repeat')
        self.assertEqual(self.repo.get(source['source_id'])['next_check_at'], after['next_check_at'])
        self.repo.update(source['source_id'], replace(self.config, enabled=False), expected_revision=1, actor='ui')
        with self.assertRaises(KnowledgeConflict):
            self.repo.request_check(source['source_id'], actor='ui', key='new-key')

    def test_api_source_scope_contracts_and_revision_conflict(self):
        tokens = {'reader': 'r' * 40, 'ingester': 'i' * 40, 'manager': 'm' * 40}
        auth = ApiAuth([{'name': name, 'token': token, 'scopes': [scope]}
                        for (name, token), scope in zip(tokens.items(), ('read', 'ingest', 'sources'), strict=True)])
        with httpx.Client(transport=httpx.WSGITransport(KnowledgeApi(self.runtime, auth)),
                          base_url='http://localhost/api/v1/') as client:
            for name in ('reader', 'ingester'):
                self.assertEqual(client.post('sources', json=asdict(self.config),
                                             headers={'Authorization': 'Bearer ' + tokens[name]}).status_code, 403)
            headers = {'Authorization': 'Bearer ' + tokens['manager'], 'Idempotency-Key': 'source-key-0001'}
            response = client.post('sources', json=asdict(self.config), headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            source_id = response.json()['source_id']
            self.assertEqual(client.post('sources', json=asdict(self.config), headers=headers).json()['source_id'],
                             source_id)
            invalid = client.post('sources', json={**asdict(self.config), 'token': 'do-not-store'}, headers=headers)
            self.assertEqual(invalid.status_code, 400)
            body = {**asdict(self.config), 'enabled': False, 'expected_revision': 1}
            self.assertEqual(client.patch(f'sources/{source_id}', json=body, headers=headers).status_code, 200)
            self.assertEqual(client.patch(f'sources/{source_id}', json=body, headers=headers).status_code, 409)
            spec = client.get('openapi.json', headers=headers).json()
            self.assertEqual(spec['paths']['/sources']['post']['x-required-scope'], 'sources')
            self.assertEqual(client.get('source-changes', headers=headers).json(), {'items': []})


class ConnectorTests(unittest.TestCase):
    config = SourceConfig('Feed', 'rss', 'https://example.org/feed')

    def test_html_trivial_markup_ignored_but_code_indent_preserved(self):
        first = '<title>Doc</title><nav>old</nav><p>Stable <b>text</b></p><pre>if x:\n    go()</pre>'
        second = '<title>Doc</title><nav>new</nav><p class="new">Stable <i>text</i></p><pre>if x:\n    go()</pre>'
        self.assertEqual(html_text(first), html_text(second))
        self.assertIn('    go()', html_text(first)[1])
        self.assertNotEqual(html_text(first), html_text(first.replace('    go()', 'go()')))
        self.assertEqual(html_text('<p>A<script>evil()</script>B</p>')[1], 'AB')

    def test_rss_dates_and_order_do_not_change_item_hashes(self):
        a = ('<item><guid>one</guid><title>Uno</title><description>&lt;p&gt;Texto&lt;/p&gt;</description>'
             '<pubDate>{}</pubDate></item>')
        b = '<item><guid>two</guid><title>Dos</title><description>Otro</description></item>'
        client = StaticHttp('<rss><channel>' + a.format('today') + b + '</channel></rss>')
        connector = RssConnector(client)
        first = connector.fetch(self.config, etag=None, last_modified=None)
        client.response = replace(client.response, body=('<rss><channel>' + b + a.format('tomorrow') +
                                                         '</channel></rss>').encode())
        second = connector.fetch(self.config, etag=None, last_modified=None)
        self.assertEqual(sorted((i.key, i.content_hash) for i in first.items),
                         sorted((i.key, i.content_hash) for i in second.items))

    def test_atom_and_no_article_fetch(self):
        body = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>urn:release:1</id><title>Release</title>'
                '<link href="https://example.org/v1"/><content type="html">&lt;p&gt;Version 1&lt;/p&gt;</content>'
                '</entry></feed>')
        client = StaticHttp(body)
        result = RssConnector(client).fetch(self.config, etag='v0', last_modified='yesterday')
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(result.items[0].content, 'Version 1')
        self.assertEqual(result.items[0].url, 'https://example.org/v1')
        self.assertEqual(client.calls[0][1]['etag'], 'v0')

    def test_malicious_xml_duplicate_ids_and_limits(self):
        for body, code in [('<!DOCTYPE rss [<!ENTITY x "boom">]><rss/>', 'UNSAFE_XML'),
                           ('<rss>\x00</rss>', 'UNSAFE_XML'), ('not xml', 'INVALID_FEED'),
                           ('<rss>' + '<item><guid>same</guid><title>A</title></item>' * 2 + '</rss>',
                            'DUPLICATE_ITEM_ID'),
                           ('<rss>' + '<item/>' * 201 + '</rss>', 'TOO_MANY_ITEMS')]:
            with self.subTest(code=code), self.assertRaises(SourceError) as raised:
                RssConnector(StaticHttp(body)).fetch(self.config, etag=None, last_modified=None)
            self.assertEqual(raised.exception.code, code)

    def test_public_dns_and_config_secrets_rejected(self):
        for address in ('127.0.0.1', '192.168.1.52', '169.254.169.254', '::1', '::ffff:127.0.0.1'):
            with patch('socket.getaddrinfo', return_value=[(socket.AF_INET, 1, 6, '', (address, 443))]), \
                    self.assertRaises(SourceError):
                public_addresses('example.org', 443)
        with patch('socket.getaddrinfo', return_value=[(socket.AF_INET, 1, 6, '', ('93.184.216.34', 443))]):
            self.assertEqual(public_addresses('example.org', 443), ['93.184.216.34'])
        for url in ('file:///etc/passwd', 'https://user:password@example.org', 'https://example.org/?api_key=secret'):
            with self.assertRaises(ValueError):
                replace(self.config, location=url)
        with self.assertRaises(ValueError):
            replace(self.config, credential_env='actual-secret-value')

    def test_network_permission_is_sanitized(self):
        with patch('socket.getaddrinfo', side_effect=PermissionError('sensitive request context')), \
                self.assertRaises(SourceError) as raised:
            SourceHttpClient().fetch('https://example.org')
        self.assertEqual(str(raised.exception), 'NETWORK_DENIED')

    def test_http_redirect_credentials_pinned_ip_and_private_redirect(self):
        responses = [HttpResponse(302, headers={'location': 'https://other.org/doc'}),
                     HttpResponse(200, b'doc', {'content-length': '3'})]
        connections = []

        def connection(*args, **kwargs):
            result = Mock()
            result.getresponse.return_value = responses.pop(0)
            connections.append((args, kwargs, result))
            return result

        with patch('knowledge_orchestrator.integrations.source_http.PinnedConnection', side_effect=connection), \
                patch('knowledge_orchestrator.integrations.source_http.public_addresses',
                      return_value=['93.184.216.34']), \
                patch.dict('os.environ', {'KO_SOURCE_SECRET_TEST': 'synthetic-secret'}):
            result = SourceHttpClient().fetch('https://example.org', credential_env='KO_SOURCE_SECRET_TEST')
        self.assertEqual(result.body, b'doc')
        self.assertEqual(connections[0][0], ('example.org', 443, '93.184.216.34'))
        self.assertTrue(connections[0][1]['tls'])
        self.assertIn('Authorization', connections[0][2].request.call_args.kwargs['headers'])
        self.assertNotIn('Authorization', connections[1][2].request.call_args.kwargs['headers'])
        self.assertTrue(all(item[2].close.called for item in connections))
        responses.append(HttpResponse(302, headers={'location': 'http://127.0.0.1/admin'}))
        with patch('knowledge_orchestrator.integrations.source_http.PinnedConnection', side_effect=connection), \
                patch('knowledge_orchestrator.integrations.source_http.public_addresses',
                      side_effect=[['93.184.216.34'], SourceError('ADDRESS_NOT_PUBLIC')]), \
                self.assertRaises(SourceError) as failure:
            SourceHttpClient().fetch('http://example.org')
        self.assertEqual(failure.exception.code, 'ADDRESS_NOT_PUBLIC')

    def test_http_rejects_large_compressed_truncated_or_unsolicited_304(self):
        cases = [(HttpResponse(200, headers={'content-length': '2000000'}), 'BODY_TOO_LARGE'),
                 (HttpResponse(200, b'x' * (1024 * 1024 + 1)), 'BODY_TOO_LARGE'),
                 (HttpResponse(200, headers={'content-encoding': 'gzip'}), 'UNSUPPORTED_ENCODING'),
                 (HttpResponse(200, b'x', {'content-length': '200'}), 'INCOMPLETE_BODY'),
                 (HttpResponse(304), 'UNEXPECTED_NOT_MODIFIED'), (HttpResponse(503, b'secret'), 'HTTP_503')]
        for response, code in cases:
            connection = Mock()
            connection.getresponse.return_value = response
            with self.subTest(code=code), \
                    patch('knowledge_orchestrator.integrations.source_http.PinnedConnection',
                          return_value=connection), \
                    patch('knowledge_orchestrator.integrations.source_http.public_addresses',
                          return_value=['93.184.216.34']), self.assertRaises(SourceError) as failure:
                SourceHttpClient().fetch('https://example.org')
            self.assertEqual(failure.exception.code, code)
            self.assertTrue(connection.close.called)


class HttpResponse:
    def __init__(self, status, body=b'', headers=None):
        self.status, self.body, self.headers = status, body, headers or {}

    def getheaders(self):
        return list(self.headers.items())

    def read1(self, size):
        result, self.body = self.body[:size], self.body[size:]
        return result


if __name__ == '__main__':
    unittest.main()
