"""Servidor WSGI de loopback. La API también puede montarse en un servidor WSGI externo."""
from __future__ import annotations

import threading
from socketserver import ThreadingMixIn
from typing import TYPE_CHECKING
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from knowledge_orchestrator.api.application import KnowledgeApi
from knowledge_orchestrator.api.auth import ApiAuth

if TYPE_CHECKING:
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


class ApiServerController:
    """Estado observado de este listener, sin inferir otros procesos ni exponer tokens."""

    def __init__(self, runtime: OrchestratorRuntime) -> None:
        self.runtime = runtime
        self._lock = threading.RLock()
        self._server: LocalServer | None = None
        self._thread: threading.Thread | None = None
        self._auth: ApiAuth | None = None
        self._state = 'STOPPED'
        self._error: str | None = None

    def snapshot(self) -> dict:
        with self._lock:
            state, error = self._state, self._error
            alive = bool(self._thread and self._thread.is_alive())
            auth = self._auth
            address = f'http://127.0.0.1:{self._server.server_port}/api/v1' if self._server else None
        if auth is None:
            try:
                auth = ApiAuth.from_environment()
            except ValueError:
                pass
        return {'state': state, 'running': state == 'RUNNING' and alive, 'address': address,
                'error_code': error, 'configured': auth is not None, 'scope': 'this_runtime',
                'clients': [{'name': client.name, 'scopes': sorted(client.scopes)} for client in auth.clients]
                if auth else []}

    def start(self, *, port: int = 8766) -> dict:
        # Port 0 is useful for isolated programmatic tests; UI/CLI require a concrete port.
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError('Puerto API inválido')
        with self._lock:
            if self._state == 'STOPPING':
                raise ValueError('La API todavía está cerrándose')
            if self._thread and self._thread.is_alive():
                if self._server and port not in {0, self._server.server_port}:
                    raise ValueError('Detén la API antes de cambiar su puerto')
                return self.snapshot()
            try:
                auth = ApiAuth.from_environment()
            except ValueError:
                self._state, self._error = 'ERROR', 'API_CREDENTIALS_NOT_CONFIGURED'
                raise ValueError('No hay consumidores API válidos configurados para esta sesión') from None
            try:
                server = make_server('127.0.0.1', port, KnowledgeApi(self.runtime, auth),
                                     server_class=LocalServer, handler_class=QuietHandler)
            except OSError:
                self._state, self._error = 'ERROR', 'API_BIND_FAILED'
                raise ValueError('No se pudo abrir el puerto local; puede estar ocupado o restringido') from None
            self._server, self._auth = server, auth
            self._state, self._error = 'RUNNING', None
            self._thread = threading.Thread(target=self._run, args=(server,), name='knowledge-api', daemon=True)
            try:
                self._thread.start()
            except RuntimeError:
                server.server_close()
                self._server, self._auth, self._thread = None, None, None
                self._state, self._error = 'ERROR', 'API_START_FAILED'
                raise ValueError('No se pudo iniciar la API local') from None
            return self.snapshot()

    def _run(self, server: LocalServer) -> None:
        failed = False
        try:
            server.serve_forever(poll_interval=0.1)
        except Exception:
            failed = True
        finally:
            server.server_close()
            with self._lock:
                if self._server is server and self._state != 'STOPPING':
                    self._server, self._auth = None, None
                    self._state = 'ERROR'
                    self._error = 'API_SERVER_FAILED' if failed else 'API_SERVER_STOPPED_UNEXPECTEDLY'

    def stop(self) -> None:
        with self._lock:
            server, thread = self._server, self._thread
            if server is None or self._state == 'STOPPING':
                return
            self._state = 'STOPPING'
        server.shutdown()
        if thread:
            thread.join(timeout=3)
        with self._lock:
            if thread and thread.is_alive():
                self._error = 'API_STOP_PENDING'
                return
            self._server, self._thread, self._auth = None, None, None
            self._state, self._error = 'STOPPED', None


def serve(runtime: OrchestratorRuntime, *, port: int = 8766) -> None:
    if not 1 <= port <= 65535:
        raise ValueError('Puerto API inválido')
    try:
        runtime.start()
        snapshot = runtime.api_server.start(port=port)
        print(f"Knowledge API: {snapshot['address']}")
        while runtime.api_server.snapshot()['running']:
            threading.Event().wait(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        runtime.stop()
