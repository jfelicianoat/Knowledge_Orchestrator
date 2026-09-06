"""Contrato de la API local; cuerpos compartidos con el validador de solicitudes."""
from __future__ import annotations

from knowledge_orchestrator.api.contracts import (
    CLAIM_REVIEW,
    DOCUMENT,
    PAGINATION,
    QUERY,
    REVIEW_ACTION,
    REVIEW_EDIT,
    SEMANTIC,
    SOURCE,
    SOURCE_UPDATE,
    STATE,
)
from knowledge_orchestrator.api.response_schemas import SCHEMAS, response_schema

# Método, ruta, permiso, descripción, cuerpo, parámetros de consulta.
ROUTES: list[tuple[str, str, str, str, dict | None, dict]] = [
    ('GET', '/openapi.json', '', 'Contrato OpenAPI', None, {}),
    ('GET', '/status', 'read', 'Estado y capacidades de la API', None, {}),
    ('GET', '/vaults', 'read', 'Bóveda configurada en este runtime', None, {}),
    ('GET', '/documents', 'read', 'Documentos publicados', None, PAGINATION),
    ('GET', '/documents/{document_id}', 'read', 'Contenido Markdown y procedencia', None, {}),
    ('GET', '/documents/{document_id}/history', 'read', 'Revisiones preservadas', None, PAGINATION),
    ('POST', '/documents', 'ingest', 'Recibir documento sin publicar directamente', DOCUMENT, {}),
    ('POST', '/ingestions', 'ingest', 'Recibir documento para el flujo de ingesta', DOCUMENT, {}),
    ('GET', '/ingestions/{ingestion_id}', 'ingest', 'Estado de una ingesta propia', None, {}),
    ('GET', '/entities', 'read', 'Entidades de conocimiento', None, PAGINATION),
    ('GET', '/entities/{entity_id}', 'read', 'Entidad por identificador', None, {}),
    ('GET', '/claims', 'read', 'Claims filtrados por vigencia', None,
     {**PAGINATION, 'state': STATE, 'entity_id': {'type': 'integer', 'minimum': 1},
      'note_id': {'type': 'integer', 'minimum': 1}}),
    ('GET', '/claims/{claim_id}', 'read', 'Claim con evidencia y procedencia', None, {'state': STATE}),
    ('GET', '/claims/{claim_id}/history', 'read', 'Transiciones y sucesión de un claim', None, {}),
    ('PATCH', '/claims/{claim_id}/knowledge-state', 'review', 'Revisar vigencia sin alterar notas ni borrar histórico',
     CLAIM_REVIEW, {}),
    ('GET', '/knowledge/{entity_id}', 'read', 'Conocimiento de una entidad', None, {**PAGINATION, 'state': STATE}),
    ('GET', '/knowledge/{entity_id}/history', 'read', 'Histórico de entidad y sucesores', None, PAGINATION),
    ('GET', '/search', 'read', 'Búsqueda léxica de claims', None,
     {**PAGINATION, 'q': {'type': 'string', 'minLength': 1, 'maxLength': 4000}, 'state': STATE}),
    ('POST', '/search/semantic', 'read', 'Búsqueda por vector en el espacio del modelo declarado', SEMANTIC, {}),
    ('POST', '/query', 'query', 'Consulta IA durable con citas exactas', QUERY, {}),
    ('GET', '/queries/{query_id}', 'query', 'Resultado o progreso de una consulta propia', None, {}),
    ('GET', '/review-tasks', 'read', 'Propuestas revisables existentes', None, PAGINATION),
    ('GET', '/review-tasks/{candidate_id}', 'read', 'Detalle de propuesta y evidencia', None, {}),
    ('PATCH', '/review-tasks/{candidate_id}', 'review', 'Editar o regenerar propuesta con revisión optimista',
     REVIEW_EDIT, {}),
    ('POST', '/review-tasks/{candidate_id}/approve', 'review', 'Aplicar una revisión concreta con evidencia',
     REVIEW_ACTION, {}),
    ('POST', '/review-tasks/{candidate_id}/reject', 'review', 'Rechazar una revisión concreta de propuesta',
     REVIEW_ACTION, {}),
    ('POST', '/sources', 'sources', 'Registrar fuente vigilada', SOURCE, {}),
    ('GET', '/sources', 'sources', 'Fuentes y salud de sus comprobaciones', None, PAGINATION),
    ('GET', '/sources/{source_id}', 'sources', 'Configuración y estado de fuente', None, {}),
    ('PATCH', '/sources/{source_id}', 'sources', 'Reemplazar configuración con revisión optimista', SOURCE_UPDATE, {}),
    ('POST', '/sources/{source_id}/check', 'sources', 'Solicitar comprobación en segundo plano', None, {}),
    ('GET', '/sources/{source_id}/checks', 'sources', 'Historial de comprobaciones', None, PAGINATION),
    ('GET', '/source-changes', 'sources', 'Novedades detectadas', None,
     {**PAGINATION, 'source_id': {'type': 'integer', 'minimum': 1},
      'status': {'type': 'string', 'enum': ['REVIEW', 'READY', 'DELIVERED']}}),
    ('GET', '/source-changes/{change_id}', 'sources', 'Contenido y procedencia de novedad', None, {}),
    ('POST', '/source-changes/{change_id}/ingest', 'sources', 'Incorporar novedad al flujo de ingesta', None, {}),
]


def specification() -> dict:
    paths: dict = {}
    for method, path, scope, summary, body, query in ROUTES:
        parameters = [{'name': name, 'in': 'query', 'schema': schema, 'required': name == 'q'}
                      for name, schema in query.items()]
        for segment in path.split('/'):
            if segment.startswith('{'):
                name = segment[1:-1]
                kind = 'string' if name in {'ingestion_id', 'query_id', 'change_id'} else 'integer'
                parameters.append({'name': name, 'in': 'path', 'required': True, 'schema': {'type': kind}})
        if method == 'POST' and path != '/search/semantic':
            parameters.append({'name': 'Idempotency-Key', 'in': 'header', 'required': True,
                               'schema': {'type': 'string', 'minLength': 8, 'maxLength': 200}})
        operation: dict = {
            'summary': summary, 'operationId': method.lower() + '_' + path.strip('/').replace('/', '_').replace('{', '')
            .replace('}', '').replace('.', '_'),
            'security': [{'bearerAuth': []}], 'x-required-scope': scope,
            'parameters': parameters,
            'responses': {
                '200': {'description': 'Resultado JSON', 'content': {'application/json': {
                    'schema': response_schema(method, path)}}},
                **{str(code): {'description': description, 'content': {'application/json': {
                    'schema': {'$ref': '#/components/schemas/Error'}}}}
                   for code, description in [(400, 'Solicitud inválida'), (401, 'Token requerido'),
                                              (403, 'Permiso insuficiente'), (404, 'No disponible'),
                                              (409, 'Conflicto o consulta obsoleta'), (413, 'Cuerpo demasiado grande'),
                                              (405, 'Método no permitido'), (411, 'Content-Length requerido'),
                                              (415, 'Se requiere application/json'),
                                              (500, 'Error interno saneado'), (502, 'Fallo de consulta IA')]},
            },
        }
        if body:
            operation['requestBody'] = {'required': True, 'content': {'application/json': {'schema': body}}}
        if method == 'POST' and path != '/search/semantic' or path == '/queries/{query_id}':
            operation['responses']['202'] = {'description': 'Trabajo durable aceptado; consultar Location',
                                             'content': {'application/json': {'schema': response_schema(method, path)}},
                                             'headers': {'Location': {'schema': {'type': 'string'}}}}
        paths.setdefault(path, {})[method.lower()] = operation
    return {'openapi': '3.1.0', 'info': {'title': 'Knowledge Orchestrator API', 'version': '1.0.0'},
            'servers': [{'url': '/api/v1'}], 'paths': paths,
            'components': {'securitySchemes': {'bearerAuth': {'type': 'http', 'scheme': 'bearer'}},
                           'schemas': {**SCHEMAS, 'Error': {'type': 'object', 'required': ['error', 'request_id'],
                                                'properties': {'error': {'type': 'object',
                                                                        'required': ['code', 'message'],
                                                                        'properties': {'code': {'type': 'string'},
                                                                                       'message': {'type': 'string'}}},
                                                               'request_id': {'type': 'string'}}}}}}
