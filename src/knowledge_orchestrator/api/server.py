"""Servidor WSGI de loopback. La API también puede montarse en un servidor WSGI externo."""
from __future__ import annotations

import json
import threading
from socketserver import ThreadingMixIn
from typing import TYPE_CHECKING
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

import httpx

from knowledge_orchestrator.api.application import KnowledgeApi
from knowledge_orchestrator.api.auth import ApiAuth
from knowledge_orchestrator.repositories.api_consumer_repository import ApiConsumerRepository
from knowledge_orchestrator.services.filesystem import atomic_write_json

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


#: Preferencias de la API junto a los datos (como la conexión del Broker): una raíz de pruebas no lee las reales.
SETTINGS_FILE = 'api_settings.json'


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
        # Consumidores dados de alta desde la aplicación; se leen en cada petición.
        self.consumers = ApiConsumerRepository(runtime.database)

    def snapshot(self) -> dict:
        with self._lock:
            state, error = self._state, self._error
            alive = bool(self._thread and self._thread.is_alive())
            auth = self._auth
            address = f'http://127.0.0.1:{self._server.server_port}/api/v1' if self._server else None
        if auth is None:
            try:
                auth = ApiAuth.from_environment(self.consumers)
            except ValueError:
                pass
        clients = auth.all_clients() if auth else []
        return {'state': state, 'running': state == 'RUNNING' and alive, 'address': address,
                'error_code': error, 'configured': bool(clients), 'scope': 'this_runtime',
                'clients': [{'name': client.name, 'scopes': sorted(client.scopes), 'origin': client.origin}
                            for client in clients]}

    def environment_client_names(self) -> set[str]:
        """Nombres ya usados por `KO_API_CLIENTS`; un consumidor nuevo no puede repetirlos."""

        try:
            return {client.name for client in ApiAuth.from_environment().clients}
        except ValueError:
            return set()

    def probe(self, token: str | None = None) -> dict:
        """Petición real a `/status` del listener de esta sesión, con la credencial dada o sin ella.

        Sin credencial, un 401 es la respuesta correcta: prueba que la API escucha
        y que exige autenticación. La credencial no se guarda ni se registra.
        """

        with self._lock:
            address = f'http://127.0.0.1:{self._server.server_port}/api/v1' if self._server else None
        if address is None:
            return {'reachable': False, 'status': None, 'client': None}
        headers = {'Authorization': 'Bearer ' + token} if token else {}
        try:
            with httpx.Client(timeout=5, trust_env=False) as client:
                response = client.get(address + '/status', headers=headers)
        except httpx.HTTPError:
            return {'reachable': False, 'status': None, 'client': None}
        name = None
        if response.status_code == 200 and token:
            authenticated = (self._auth or ApiAuth([], store=self.consumers)).authenticate('Bearer ' + token)
            name = authenticated.name if authenticated else None
        return {'reachable': True, 'status': response.status_code, 'client': name}

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
                auth = ApiAuth.from_environment(self.consumers)
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

    def preferences(self) -> dict:
        """Inicio automático (activado si nunca se tocó) y último puerto usado."""
        try:
            payload = json.loads((self.runtime.paths.state / SETTINGS_FILE).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            payload = {}
        autostart, port = payload.get('autostart'), payload.get('port')
        return {'autostart': autostart if isinstance(autostart, bool) else True,
                'port': port if type(port) is int and 1 <= port <= 65535 else None}

    def save_preferences(self, *, autostart: bool, port: int | None) -> None:
        atomic_write_json(self.runtime.paths.state / SETTINGS_FILE, {'autostart': autostart, 'port': port})

    def autostart(self, default_port: int) -> dict | None:
        """Inicia la API al abrir la aplicación si así se quiere y hay consumidores; si no, nada.

        Así otra aplicación (p. ej. ChatyGPT) puede consultar mientras la ventana esté
        abierta sin que nadie se acuerde de pulsar «Iniciar API». Un fallo (puerto
        ocupado) se lanza como ValueError, igual que al iniciarla a mano.
        """
        preferences = self.preferences()
        if not preferences['autostart'] or not self.snapshot()['configured']:
            return None
        return self.start(port=preferences['port'] or default_port)

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
