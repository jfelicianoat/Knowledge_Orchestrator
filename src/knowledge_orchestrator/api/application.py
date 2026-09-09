"""Adaptador WSGI local: valida contratos y permisos antes de llamar servicios."""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import asdict
from http import HTTPStatus
from typing import TYPE_CHECKING
from urllib.parse import parse_qs

from knowledge_orchestrator.api.auth import ApiAuth
from knowledge_orchestrator.api.automation import dispatch as automation_dispatch
from knowledge_orchestrator.api.contracts import validate
from knowledge_orchestrator.api.openapi import ROUTES, specification
from knowledge_orchestrator.api.reversions import dispatch as reversion_dispatch
from knowledge_orchestrator.domain.knowledge import KnowledgeConflict, KnowledgeState
from knowledge_orchestrator.domain.monitoring import SourceConfig
from knowledge_orchestrator.integrations.obsidian_bridge import ObsidianBridgeUnavailable

if TYPE_CHECKING:
    from knowledge_orchestrator.runtime import OrchestratorRuntime

MAX_BODY = 2 * 1024 * 1024


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('JSON contiene claves duplicadas')
        result[key] = value
    return result


class KnowledgeApi:
    def __init__(self, runtime: OrchestratorRuntime, auth: ApiAuth) -> None:
        self.runtime = runtime
        self.auth = auth
        self.access = runtime.knowledge_access
        self.routes = [(re.compile('^' + '/'.join(
            f'(?P<{segment[1:-1]}>[A-Za-z0-9_-]+)' if segment.startswith('{') else re.escape(segment)
            for segment in path.split('/')) + '$'),
                        method, path, scope, schema, query)
                       for method, path, scope, _summary, schema, query in ROUTES]

    def __call__(self, environ: dict, start_response):
        request_id = uuid.uuid4().hex
        headers: dict[str, str] = {}
        client = None
        route = 'unmatched'
        try:
            client = self.auth.authenticate(environ.get('HTTP_AUTHORIZATION', ''))
            if client is None:
                raise ApiError(401, 'UNAUTHENTICATED', 'Se requiere un token Bearer válido')
            path = environ.get('PATH_INFO', '')
            if not path.startswith('/api/v1/'):
                raise ApiError(404, 'NOT_FOUND', 'Ruta inexistente')
            path = path[len('/api/v1'):]
            method = environ.get('REQUEST_METHOD', 'GET')
            matches = [(entry, entry[0].fullmatch(path)) for entry in self.routes if entry[0].fullmatch(path)]
            if not matches:
                raise ApiError(404, 'NOT_FOUND', 'Ruta inexistente')
            matched = next(((entry, match) for entry, match in matches if entry[1] == method), None)
            if matched is None:
                headers['Allow'] = ', '.join(sorted({entry[1] for entry, _ in matches}))
                raise ApiError(405, 'METHOD_NOT_ALLOWED', 'Método no permitido')
            entry, match = matched
            assert match is not None
            _, _, route, scope, schema, query_schema = entry
            if scope and scope not in client.scopes:
                raise ApiError(403, 'FORBIDDEN', 'El consumidor no tiene este permiso')
            ids: dict = match.groupdict()
            for name, value in list(ids.items()):
                if name not in {'query_id', 'ingestion_id', 'change_id', 'batch_id', 'simulation_id', 'run_id',
                                'reversion_id'}:
                    if not value.isdecimal() or not 1 <= int(value) <= 2**63 - 1:
                        raise ValueError('Identificador inválido')
                    ids[name] = int(value)
            query = self._query(environ.get('QUERY_STRING', ''), query_schema)
            body = self._body(environ, schema) if schema else {}
            key = environ.get('HTTP_IDEMPOTENCY_KEY', '')
            if method == 'POST' and route != '/search/semantic' and not re.fullmatch(r'[A-Za-z0-9_.:-]{8,200}', key):
                raise ValueError('Idempotency-Key requiere 8–200 caracteres alfanuméricos, punto, guion, : o _')
            status, payload, extra = self.dispatch(method, route, ids, query, body, client.name, key)
            headers.update(extra)
        except ApiError as error:
            status, payload = error.status, {'error': {'code': error.code, 'message': error.message}}
        except KnowledgeConflict as error:
            status, payload = 409, {'error': {'code': 'CONFLICT', 'message': str(error)}}
        except ObsidianBridgeUnavailable:
            status, payload = 503, {'error': {
                'code': 'OBSIDIAN_UNAVAILABLE',
                'message': 'La operación queda pendiente. Abre y comprueba el puente de Obsidian '
                           'y reinicia el Orchestrator para recuperar la intención autorizada.',
            }}
        except LookupError:
            status, payload = 404, {'error': {'code': 'NOT_FOUND', 'message': 'Recurso no disponible'}}
        except (ValueError, TypeError, OverflowError, RecursionError):
            status, payload = 400, {'error': {'code': 'INVALID_REQUEST', 'message': 'Solicitud fuera del contrato'}}
        except Exception:
            status, payload = 500, {'error': {'code': 'INTERNAL_ERROR', 'message': 'No se pudo completar la operación'}}
        if status >= 400:
            payload['request_id'] = request_id
        if status == 401:
            headers['WWW-Authenticate'] = 'Bearer'
        try:
            self.runtime.repository.record_event('API_REQUEST', 'Petición a la API de conocimiento', details={
                'request_id': request_id, 'client': client.name if client else None, 'route': route,
                'method': environ.get('REQUEST_METHOD'), 'status': status,
            })
        except (sqlite3.Error, OSError):
            # La escritura durable de ingestas/queries incluye su propio evento transaccional.
            pass
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
        standard = {'Content-Type': 'application/json; charset=utf-8', 'Content-Length': str(len(data)),
                    'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'X-Request-ID': request_id}
        start_response(f'{status} {HTTPStatus(status).phrase}', list({**standard, **headers}.items()))
        return [data]

    @staticmethod
    def _query(raw: str, schema: dict) -> dict:
        values = parse_qs(raw, keep_blank_values=True, max_num_fields=32)
        if set(values) - set(schema) or any(len(items) != 1 for items in values.values()):
            raise ValueError('Parámetros de consulta desconocidos o duplicados')
        result = {}
        for name, spec in schema.items():
            if name not in values:
                if 'default' in spec:
                    result[name] = spec['default']
                elif name == 'q':
                    raise ValueError('Falta q')
                continue
            value = int(values[name][0]) if spec['type'] == 'integer' else values[name][0]
            validate(value, spec, name)
            result[name] = value
        return result

    @staticmethod
    def _body(environ: dict, schema: dict) -> dict:
        if environ.get('CONTENT_TYPE', '').split(';')[0].strip().lower() != 'application/json':
            raise ApiError(415, 'UNSUPPORTED_MEDIA_TYPE', 'Se requiere application/json')
        if not environ.get('CONTENT_LENGTH'):
            raise ApiError(411, 'LENGTH_REQUIRED', 'Se requiere Content-Length')
        length = int(environ['CONTENT_LENGTH'])
        if length > MAX_BODY:
            raise ApiError(413, 'BODY_TOO_LARGE', 'El cuerpo supera 2 MiB')
        if length <= 0:
            raise ValueError('Cuerpo vacío')
        content = environ['wsgi.input'].read(length)
        if len(content) != length:
            raise ValueError('Cuerpo incompleto')
        body = json.loads(content.decode('utf-8'), object_pairs_hook=unique_object)
        validate(body, schema)
        return body

    def dispatch(self, method: str, route: str, ids: dict, query: dict, body: dict, owner: str, key: str) -> tuple:
        runtime = self.runtime
        if route.startswith('/review-reversions') or route == '/review-publications':
            return reversion_dispatch(runtime, method, route, ids, query, body, owner, key)
        if route.startswith('/automation/'):
            return automation_dispatch(runtime, method, route, ids, query, body, owner, key)
        if route == '/review-batches':
            return 200, {'items': runtime.review_batches.repository.list(owner=owner, **query)}, {}
        if route == '/review-batches/preview':
            result = runtime.review_batches.preview(owner=owner, key=key, selection=body.get('selection'))
            return 200, result, {'Location': '/api/v1/review-batches/' + result['batch_id']}
        if route == '/review-batches/{batch_id}/confirm':
            result = runtime.review_batches.repository.confirm(ids['batch_id'], owner=owner,
                                                                plan_hash=body['plan_hash'])
            return 202, result, {'Location': '/api/v1/review-batches/' + result['batch_id']}
        if route == '/review-batches/{batch_id}':
            return 200, runtime.review_batches.repository.get(ids['batch_id'], owner=owner), {}
        if route == '/openapi.json':
            return 200, specification(), {}
        if route == '/status':
            capabilities = runtime.broker_worker.capabilities_snapshot()
            return 200, {'api_version': 'v1', 'authentication': 'required',
                         'capabilities': ['documents', 'claims', 'entities', 'history', 'fts_search',
                                          'vector_search', 'grounded_query', 'controlled_ingestion',
                                          'source_monitoring'],
                         'broker': {'contract_version': capabilities.get('contract_version'),
                                    'capabilities_observed': bool(capabilities)}}, {}
        if route == '/vaults':
            return 200, {'items': [{'vault_id': 'default', 'name': runtime.paths.obsidian_vault.name}]}, {}
        if route in {'/documents', '/ingestions'} and method == 'POST':
            result = runtime.api_ingestion.create(body, owner=owner, key=key)
            return 202, result, {'Location': '/api/v1/ingestions/' + result['ingestion_id']}
        if route == '/ingestions/{ingestion_id}':
            return 200, runtime.api_ingestion.get(ids['ingestion_id'], owner=owner), {}
        if route == '/documents':
            return 200, {'items': self.access.documents(**query)}, {}
        if route == '/documents/{document_id}':
            return 200, self.access.document(ids['document_id']), {}
        if route == '/documents/{document_id}/history':
            return 200, {'items': self.access.document_history(ids['document_id'], **query)}, {}
        if route == '/entities':
            return 200, {'items': [asdict(e) for e in runtime.knowledge.repository.entities(**query)]}, {}
        if route == '/entities/{entity_id}':
            entity = runtime.knowledge.repository.entity(ids['entity_id'])
            if entity is None:
                raise LookupError('Entidad inexistente')
            return 200, asdict(entity), {}
        if route == '/claims':
            return 200, {'items': self.access.claims(**query)}, {}
        if route == '/claims/{claim_id}':
            return 200, self.access.claim(ids['claim_id'], **query), {}
        if route == '/claims/{claim_id}/history':
            self.access.claim(ids['claim_id'], state='all')
            return 200, {'transitions': runtime.knowledge.repository.history(ids['claim_id']),
                         'succession': [self.access.claim_payload(c.claim_id)
                                        for c in runtime.knowledge.repository.succession(ids['claim_id'])]}, {}
        if route == '/claims/{claim_id}/knowledge-state':
            runtime.knowledge.repository.review_state(ids['claim_id'], KnowledgeState(body['state']),
                                                      expected_revision=body['expected_revision'], actor=owner,
                                                      reason=body['reason'])
            return 200, self.access.claim(ids['claim_id'], state='all'), {}
        if route == '/knowledge/{entity_id}':
            return 200, self.access.entity_knowledge(ids['entity_id'], **query), {}
        if route == '/knowledge/{entity_id}/history':
            return 200, self.access.entity_history(ids['entity_id'], **query), {}
        if route == '/search':
            text = query.pop('q')
            return 200, {'items': self.access.search(text, **query)}, {}
        if route == '/search/semantic':
            return 200, {'items': self.access.semantic_search(**body), 'retrieval': 'vector_cosine'}, {}
        if route in {'/query', '/queries/{query_id}'}:
            result = runtime.knowledge_queries.create(body['question'], state=body.get('state', 'current'),
                                                       owner=owner, key=key) if method == 'POST' else \
                runtime.knowledge_queries.get(ids['query_id'], owner=owner)
            status = 200 if result['status'] == 'SUCCESS' else 409 if result['status'] == 'STALE' else \
                502 if result['status'] == 'ERROR' else 202
            if status >= 400:
                result['error'] = {'code': result['error_code'],
                                   'message': 'El conocimiento cambió' if status == 409 else 'La consulta IA falló'}
            return status, result, {'Location': '/api/v1/queries/' + result['query_id']}
        sources = runtime.sources.repository
        if route == '/sources':
            if method == 'POST':
                result = sources.create(SourceConfig(**body), actor=owner, key=key)
                return 200, result, {'Location': '/api/v1/sources/' + str(result['source_id'])}
            return 200, {'items': sources.list_sources(**query)}, {}
        if route == '/sources/{source_id}':
            if method == 'PATCH':
                revision = body.pop('expected_revision')
                return 200, sources.update(ids['source_id'], SourceConfig(**body),
                                           expected_revision=revision, actor=owner), {}
            return 200, sources.get(ids['source_id']), {}
        if route == '/sources/{source_id}/check':
            result = sources.request_check(ids['source_id'], actor=owner, key=key)
            return 202, result, {'Location': '/api/v1/sources/' + str(result['source_id'])}
        if route == '/sources/{source_id}/checks':
            return 200, {'items': sources.history(ids['source_id'], **query)}, {}
        if route == '/source-changes':
            return 200, {'items': sources.changes(**query)}, {}
        if route == '/source-changes/{change_id}':
            return 200, sources.change(ids['change_id']), {}
        if route == '/source-changes/{change_id}/ingest':
            return 202, sources.queue_ingestion(ids['change_id'], actor=owner), {
                'Location': '/api/v1/source-changes/' + ids['change_id']}
        if route == '/review-tasks':
            items = runtime.semantic_repository.list_candidates('PENDING_COMPARISON', 'PENDING_REVIEW', 'CONFLICT')
            start = query['offset']
            return 200, {'items': [self._candidate(c) for c in items[start:start + query['limit']]]}, {}
        if route.startswith('/review-tasks/') and method in {'POST', 'PATCH'}:
            candidate = runtime.semantic_repository.get_candidate(ids['candidate_id'])
            if candidate is None:
                raise LookupError('Propuesta inexistente')
            revision = body.pop('expected_revision')
            if candidate.proposal_revision != revision:
                raise KnowledgeConflict('La propuesta cambió desde que se abrió')
            try:
                if method == 'PATCH':
                    runtime.semantic_maintenance.edit(candidate.candidate_id, body,
                                                      expected_revision=revision, actor=owner)
                elif route.endswith('/approve') and candidate.status != 'APPLIED':
                    runtime.semantic_maintenance.approve(candidate.candidate_id,
                                                         expected_revision=revision, actor=owner)
                elif route.endswith('/reject') and candidate.status != 'REJECTED':
                    runtime.semantic_maintenance.reject(candidate.candidate_id, expected_revision=revision, actor=owner,
                                                        reason=body.get('reason', 'Rechazo explícito desde API'))
            except ValueError as error:
                raise KnowledgeConflict(str(error)) from error
            return 200, runtime.semantic_maintenance.proposal_detail(candidate.candidate_id), {}
        candidate = runtime.semantic_repository.get_candidate(ids['candidate_id'])
        if candidate is None:
            raise LookupError('Propuesta inexistente')
        return 200, {**self._candidate(candidate),
                     'review': runtime.semantic_maintenance.proposal_detail(candidate.candidate_id),
                     'target': self.access.claim_payload(candidate.target_claim_id),
                     'new_claim': self.access.claim_payload(candidate.new_claim_id)}, {}

    @staticmethod
    def _candidate(candidate) -> dict:
        payload = asdict(candidate)
        payload.pop('temp_path', None)
        return payload
