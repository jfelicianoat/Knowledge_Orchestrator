"""HTTP acotado; resuelve y conecta a la misma IP pública para evitar DNS rebinding."""
from __future__ import annotations

import http.client
import ipaddress
import os
import socket
import ssl
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from knowledge_orchestrator.domain.monitoring import SourceError, source_url

MAX_BYTES = 1024 * 1024


@dataclass(frozen=True)
class SourceResponse:
    status: int
    body: bytes
    headers: dict[str, str]
    url: str


def public_addresses(host: str, port: int) -> list[str]:
    addresses = list(dict.fromkeys(str(info[4][0]) for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
    parsed = [ipaddress.ip_address(address) for address in addresses]
    if not parsed or any(not ip.is_global or ip.is_multicast or ip.is_reserved for ip in parsed):
        raise SourceError('ADDRESS_NOT_PUBLIC')
    return addresses


class PinnedConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, ip: str, *, tls: bool, timeout: float):
        super().__init__(host, port, timeout=timeout)
        self.ip, self.tls = ip, tls

    def connect(self) -> None:
        sock = socket.create_connection((self.ip, self.port), self.timeout)
        try:
            self.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host) if self.tls else sock
        except BaseException:
            sock.close()
            raise


class SourceHttpClient:
    def fetch(self, url: str, *, etag: str | None = None, last_modified: str | None = None,
              credential_env: str = '') -> SourceResponse:
        try:
            return self._fetch(url, etag=etag, last_modified=last_modified, credential_env=credential_env)
        except SourceError:
            raise
        except TimeoutError as error:
            raise SourceError('TIMEOUT') from error
        except PermissionError as error:
            raise SourceError('NETWORK_DENIED') from error
        except (OSError, http.client.HTTPException, ValueError, UnicodeError) as error:
            raise SourceError('NETWORK_ERROR') from error

    def _fetch(self, url: str, *, etag: str | None, last_modified: str | None, credential_env: str) -> SourceResponse:
        original = urlsplit(source_url(url))
        origin = (original.scheme, original.hostname, original.port)
        secret = os.environ.get(credential_env, '') if credential_env else ''
        if credential_env and (not secret or not secret.isascii() or any(c.isspace() for c in secret)):
            raise SourceError('CREDENTIAL_UNAVAILABLE')
        if secret and original.scheme != 'https':
            raise SourceError('CREDENTIAL_REQUIRES_HTTPS')
        deadline = time.monotonic() + 25
        for _ in range(4):
            parsed = urlsplit(source_url(url))
            assert parsed.hostname is not None
            port = parsed.port or (443 if parsed.scheme == 'https' else 80)
            addresses = public_addresses(parsed.hostname, port)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SourceError('TIMEOUT')
            headers = {'User-Agent': 'KnowledgeOrchestrator/0.1 source-monitor', 'Accept-Encoding': 'identity',
                       'Accept': 'text/html,application/rss+xml,application/atom+xml,text/plain,application/xml'}
            if etag:
                headers['If-None-Match'] = etag
            if last_modified:
                headers['If-Modified-Since'] = last_modified
            if secret and (parsed.scheme, parsed.hostname, parsed.port) == origin:
                headers['Authorization'] = 'Bearer ' + secret
            connection = PinnedConnection(parsed.hostname, port, addresses[0], tls=parsed.scheme == 'https',
                                          timeout=min(8, remaining))
            try:
                target = parsed.path or '/'
                if parsed.query:
                    target += '?' + parsed.query
                connection.request('GET', target, headers=headers)
                response = connection.getresponse()
                response_headers = {name.lower(): value for name, value in response.getheaders()}
                if response.status in {301, 302, 303, 307, 308}:
                    location = response_headers.get('location')
                    if not location:
                        raise SourceError('INVALID_REDIRECT')
                    next_url = urljoin(url, location)
                    if parsed.scheme == 'https' and urlsplit(next_url).scheme != 'https':
                        raise SourceError('INSECURE_REDIRECT')
                    url = next_url
                    continue
                if response.status == 304:
                    if not etag and not last_modified:
                        raise SourceError('UNEXPECTED_NOT_MODIFIED')
                    return SourceResponse(304, b'', response_headers, url)
                if response.status != 200:
                    raise SourceError('HTTP_' + str(response.status))
                if response_headers.get('content-encoding', 'identity').lower() != 'identity':
                    raise SourceError('UNSUPPORTED_ENCODING')
                expected_size = int(response_headers.get('content-length', '-1'))
                if expected_size > MAX_BYTES:
                    raise SourceError('BODY_TOO_LARGE')
                chunks: list[bytes] = []
                size = 0
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise SourceError('TIMEOUT')
                    if connection.sock:
                        connection.sock.settimeout(min(8, remaining))
                    chunk = response.read1(min(65536, MAX_BYTES + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise SourceError('BODY_TOO_LARGE')
                if expected_size >= 0 and size != expected_size:
                    raise SourceError('INCOMPLETE_BODY')
                return SourceResponse(200, b''.join(chunks), response_headers, url)
            finally:
                connection.close()
        raise SourceError('TOO_MANY_REDIRECTS')
