"""Conectores Web y RSS/Atom: no ejecutan scripts ni siguen enlaces de artículos."""
from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from typing import Protocol
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

from knowledge_orchestrator.domain.monitoring import FetchResult, SourceConfig, SourceError, SourceItem, source_url
from knowledge_orchestrator.integrations.source_http import SourceHttpClient, SourceResponse


class Connector(Protocol):
    def fetch(self, config: SourceConfig, *, etag: str | None, last_modified: str | None) -> FetchResult: ...


class VisibleHtml(HTMLParser):
    HIDDEN = {'script', 'style', 'nav', 'header', 'footer', 'noscript', 'svg'}
    BREAKS = {'p', 'div', 'li', 'br', 'h1', 'h2', 'h3', 'h4', 'section', 'article', 'tr'}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden: list[str] = []
        self.pre = 0
        self.parts: list[tuple[bool, str]] = []
        self.in_title = False
        self.title: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.rsplit(':', 1)[-1]
        if tag in self.HIDDEN:
            self.hidden.append(tag)
        if self.hidden:
            return
        if tag == 'title':
            self.in_title = True
        elif tag == 'pre':
            self.pre += 1
            self.parts.append((True, '\n```\n'))
        elif tag in self.BREAKS:
            self.parts.append((bool(self.pre), '\n'))

    def handle_endtag(self, tag):
        tag = tag.rsplit(':', 1)[-1]
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
            return
        if tag == 'title':
            self.in_title = False
        elif tag == 'pre' and self.pre:
            self.parts.append((True, '\n```\n'))
            self.pre -= 1
        elif tag in self.BREAKS:
            self.parts.append((bool(self.pre), '\n'))

    def handle_data(self, data):
        if self.hidden:
            return
        if self.in_title:
            self.title.append(data)
        else:
            self.parts.append((bool(self.pre), data))

    def text(self) -> str:
        output: list[str] = []
        normal: list[str] = []
        for pre, text in self.parts + [(True, '')]:
            if pre:
                if normal:
                    output.append(re.sub(r'\s+', ' ', ''.join(normal)).strip())
                    normal = []
                output.append(text.replace('\r\n', '\n'))
            else:
                normal.append(text)
        return ''.join(output).strip()


def html_text(value: str) -> tuple[str, str]:
    parser = VisibleHtml()
    parser.feed(value)
    parser.close()
    return ' '.join(''.join(parser.title).split()), parser.text()


class HttpConnector:
    def __init__(self, client: SourceHttpClient | None = None):
        self.client = client or SourceHttpClient()

    def fetch(self, config: SourceConfig, *, etag: str | None, last_modified: str | None) -> FetchResult:
        response = self.client.fetch(config.location, etag=etag, last_modified=last_modified,
                                     credential_env=config.credential_env)
        # No validator can inject a header into the next request or grow unbounded in SQLite.
        def validator(name):
            value = response.headers.get(name)
            return value if value and len(value) <= 1000 and all(32 <= ord(c) < 127 for c in value) else None

        items = () if response.status == 304 else self.parse(response, config)
        keys = [item.key for item in items]
        if len(keys) != len(set(keys)):
            raise SourceError('DUPLICATE_ITEM_ID')
        for item in items:
            if not item.content.strip() or len(item.content) > 500000 or not 1 <= len(item.title) <= 500:
                raise SourceError('INVALID_CONTENT')
        return FetchResult(items, validator('etag'), validator('last-modified'), response.status == 304)

    def parse(self, response: SourceResponse, config: SourceConfig) -> tuple[SourceItem, ...]:
        raise NotImplementedError


class WebConnector(HttpConnector):
    def parse(self, response: SourceResponse, config: SourceConfig) -> tuple[SourceItem, ...]:
        content_type = response.headers.get('content-type', '').lower()
        if content_type.split(';')[0].strip() not in {'text/html', 'text/plain', 'application/xhtml+xml'}:
            raise SourceError('UNSUPPORTED_CONTENT_TYPE')
        charset = re.search(r'charset=["\']?([\w-]+)', content_type)
        try:
            text = response.body.decode(charset[1] if charset else 'utf-8')
        except (LookupError, UnicodeError) as error:
            raise SourceError('INVALID_TEXT_ENCODING') from error
        if 'html' in content_type:
            title, content = html_text(text)
        else:
            title, content = '', text.replace('\r\n', '\n').strip()
        return (SourceItem(config.location, title or config.name, content, response.url),)


class RssConnector(HttpConnector):
    def parse(self, response: SourceResponse, config: SourceConfig) -> tuple[SourceItem, ...]:
        # Reject declarations before parsing; UTF-16/32 XML is rejected to avoid alternate-encoding bypasses.
        if b'\x00' in response.body or re.search(br'<!\s*(DOCTYPE|ENTITY)', response.body, re.I):
            raise SourceError('UNSAFE_XML')
        try:
            root = ET.fromstring(response.body)
        except ET.ParseError as error:
            raise SourceError('INVALID_FEED') from error
        def local(tag):
            return tag.rsplit('}', 1)[-1]

        if local(root.tag) not in {'rss', 'feed', 'RDF'}:
            raise SourceError('INVALID_FEED')
        entries = [element for element in root.iter() if local(element.tag) in {'entry', 'item'}]
        if len(entries) > 200:
            raise SourceError('TOO_MANY_ITEMS')
        items = []
        for entry in entries:
            values: dict[str, str] = {}
            link = ''
            for child in entry:
                name = local(child.tag)
                value = ''.join(child.itertext()).strip()
                if name == 'link':
                    if child.get('rel', 'alternate') == 'alternate':
                        link = child.get('href', value)
                elif name in {'title', 'description', 'summary', 'content', 'encoded', 'id', 'guid'}:
                    # XHTML Atom content needs actual separators, not concatenated itertext.
                    values[name] = ET.tostring(child, encoding='unicode') if len(child) else value
            _, content = html_text(values.get('encoded') or values.get('content') or values.get('description')
                                   or values.get('summary') or values.get('title', ''))
            _, title = html_text(values.get('title', ''))
            url = config.location
            if link:
                try:
                    url = source_url(urljoin(response.url, link))
                except ValueError:
                    pass  # Store a safe feed URL; never follow or retain credential-bearing links.
            identifier = values.get('id') or values.get('guid') or link or hashlib.sha256(content.encode()).hexdigest()
            key = hashlib.sha256((config.location + '\n' + identifier).encode()).hexdigest()
            items.append(SourceItem(key, title or config.name, content, url))
        return tuple(items)
