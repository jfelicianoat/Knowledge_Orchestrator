"""Saneamiento compartido de diagnósticos, sin acceso a configuración."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus

SENSITIVE_KEYS = re.compile(r"(token|secret|password|api[_-]?key|authorization|cookie)", re.IGNORECASE)
URL_CREDENTIALS = re.compile(r"://[^/@\s?#]+@")
SENSITIVE_HEADER = re.compile(
    r"(?im)\b((?:proxy-)?authorization|(?:set-)?cookie)\b\s*[:=]\s*[^\r\n]+"
)
SENSITIVE_ASSIGNMENT = re.compile(
    r'''(?ix)["']?\b([\w.-]*(?:token|secret|password|api[_-]?key|authorization|cookie)[\w.-]*)
    \b["']?\s*[:=]\s*(?:"(?:\\.|[^"\\])*(?:"|$)|'(?:\\.|[^'\\])*(?:'|$)|[^\s,;&\#}\]]+)'''
)
REDACTED = "***REDACTED***"


def sanitize(value: Any, *, known_secrets: tuple[str, ...] = ()) -> Any:
    variants = {
        variant
        for secret in known_secrets if secret
        for variant in (secret, quote(secret, safe=""), quote_plus(secret), json.dumps(secret)[1:-1])
    }
    return _sanitize(value, tuple(sorted(variants, key=len, reverse=True)), depth=0)


def _sanitize(value: Any, secrets: tuple[str, ...], *, depth: int) -> Any:
    if depth > 20:
        return "[OMITTED: nested data]"
    if isinstance(value, dict):
        return {
            _mask_known(str(key), secrets): REDACTED if SENSITIVE_KEYS.search(str(key))
            else _sanitize(item, secrets, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item, secrets, depth=depth + 1) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize(item, secrets, depth=depth + 1) for item in value)
    if isinstance(value, Path):
        value = str(value)
    if isinstance(value, str):
        if value.lstrip().startswith(("{", "[")):
            try:
                parsed = json.loads(value)
            except (ValueError, RecursionError):
                pass
            else:
                return json.dumps(_sanitize(parsed, secrets, depth=depth + 1), ensure_ascii=False)
        redacted = URL_CREDENTIALS.sub("://***:***@", value)
        redacted = SENSITIVE_HEADER.sub(lambda match: f"{match.group(1)}={REDACTED}", redacted)
        redacted = SENSITIVE_ASSIGNMENT.sub(lambda match: f"{match.group(1)}={REDACTED}", redacted)
        return _mask_known(redacted, secrets)
    return value


def _mask_known(value: str, secrets: tuple[str, ...]) -> str:
    for secret in secrets:
        value = value.replace(secret, REDACTED)
    return value
