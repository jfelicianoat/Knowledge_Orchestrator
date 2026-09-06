"""Contratos de fuentes: la confianza describe procedencia, nunca certeza factual."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from urllib.parse import parse_qsl, urlsplit

ROLES = ('official_documentation', 'official_repository', 'official_blog', 'secondary', 'generic')


def source_url(value: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 2000 or any(c.isspace() for c in value):
        raise ValueError('URL inválida')
    url = urlsplit(value)
    if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password or url.fragment:
        raise ValueError('Se requiere HTTP(S), sin credenciales ni fragmentos')
    if url.port not in {None, 80, 443} or any(ord(c) < 32 for c in value):
        raise ValueError('Puerto o caracteres no permitidos')
    if any(re.search(r'token|secret|password|credential|api.?key|signature', key, re.I)
           for key, _ in parse_qsl(url.query)):
        raise ValueError('Use una referencia de entorno para las credenciales')
    return value


@dataclass(frozen=True)
class SourceConfig:
    name: str
    kind: str
    location: str
    interval_seconds: int = 3600
    enabled: bool = True
    scope: str = ''
    trust_level: int = 50
    source_role: str = 'generic'
    ingestion_policy: str = 'review'
    credential_env: str = ''

    def __post_init__(self) -> None:
        source_url(self.location)
        if not isinstance(self.name, str) or not 1 <= len(self.name.strip()) <= 200:
            raise ValueError('Nombre requerido (máximo 200 caracteres)')
        if self.kind not in {'web', 'rss'} or self.source_role not in ROLES:
            raise ValueError('Tipo o categoría de fuente no admitido')
        if type(self.interval_seconds) is not int or not 60 <= self.interval_seconds <= 2592000:
            raise ValueError('Frecuencia entre un minuto y 30 días')
        if type(self.trust_level) is not int or not 0 <= self.trust_level <= 100:
            raise ValueError('Confianza entre 0 y 100')
        if type(self.enabled) is not bool or not isinstance(self.scope, str) or len(self.scope) > 500:
            raise ValueError('Activación o ámbito inválidos')
        if self.ingestion_policy not in {'review', 'ingest'}:
            raise ValueError('Política de ingesta inválida')
        if not isinstance(self.credential_env, str) or (self.credential_env and not re.fullmatch(
            r'KO_SOURCE_SECRET_[A-Z0-9_]{1,80}', self.credential_env
        )):
            raise ValueError('Credencial: referencia KO_SOURCE_SECRET_…')

    def json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)


@dataclass(frozen=True)
class SourceItem:
    key: str
    title: str
    content: str
    url: str

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(json.dumps([self.title, self.content], ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True)
class FetchResult:
    items: tuple[SourceItem, ...] = ()
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False


class SourceError(Exception):
    """Solo códigos estables; nunca conservar cuerpos remotos ni secretos en errores."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code
