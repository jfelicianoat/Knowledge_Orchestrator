"""Servidor WSGI de loopback. La API también puede montarse en un servidor WSGI externo."""
from __future__ import annotations

from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from knowledge_orchestrator.api.application import KnowledgeApi
from knowledge_orchestrator.api.auth import ApiAuth
from knowledge_orchestrator.runtime import OrchestratorRuntime


class LocalServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True
    allow_reuse_address = True

    def get_request(self):
        stream, address = super().get_request()
        stream.settimeout(15)
        return stream, address


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        # El evento API_REQUEST evita registrar URLs de consulta, cuerpos y credenciales.
        pass


def serve(runtime: OrchestratorRuntime, *, port: int = 8766) -> None:
    auth = ApiAuth.from_environment()
    if not 1 <= port <= 65535:
        raise ValueError('Puerto API inválido')
    with make_server('127.0.0.1', port, KnowledgeApi(runtime, auth),
                     server_class=LocalServer, handler_class=QuietHandler) as server:
        runtime.start()
        try:
            print(f'Knowledge API: http://127.0.0.1:{port}/api/v1')
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            runtime.stop()
