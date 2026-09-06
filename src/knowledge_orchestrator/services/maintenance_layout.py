"""Transformaciones documentales deterministas; fallback a revisión si la estructura es ambigua."""
from __future__ import annotations

import re

CURRENT = '## Estado actual\n\n'
HISTORY = '## Histórico\n\n'


def historical_entry(claim_id: int, quote: str) -> str:
    return f'### Sustituido — claim {claim_id}\n\n{quote}\n\n'


def history_boundary(document: str) -> int | None:
    if document.count(CURRENT) == 1 and document.count(HISTORY) == 1:
        current, historical = document.index(CURRENT), document.index(HISTORY)
        if current < historical:
            return historical
    return None


def plan_layout(document: str, patch: dict, *, claim_id: int, body_start: int) -> dict:
    old, new = patch['old'], patch['replacement']
    boundary = history_boundary(document)
    if boundary is not None:
        content_start = document.index(CURRENT) + len(CURRENT)
        if content_start <= patch['start'] < patch['end'] <= boundary and \
                document[content_start:boundary].strip() == old.strip():
            end = boundary + len(HISTORY)
            return {**patch, 'end': end, 'old': document[patch['start']:end],
                    'replacement': new + '\n\n' + HISTORY + historical_entry(claim_id, old),
                    'history_strategy': 'existing_current_history', 'current_offset': 0}
    # Only an H1 and this isolated paragraph: there is no other prose, list, table or code to reorganize.
    body = document[body_start:].strip()
    simple = re.fullmatch(r'# [^\n]+\n+' + re.escape(old.strip()), body)
    if simple and '\n' not in old and not re.search(r'[`|<>\[\]#]', old + new):
        return {**patch, 'replacement': CURRENT + new + '\n\n' + HISTORY + historical_entry(claim_id, old),
                'history_strategy': 'create_current_history', 'current_offset': len(CURRENT)}
    return {**patch, 'history_strategy': 'revision_snapshot', 'current_offset': 0}


def valid_layout(patch: dict, *, claim_id: int, old_quote: str, new_quote: str) -> bool:
    strategy = patch.get('history_strategy', 'revision_snapshot')
    if strategy == 'revision_snapshot':
        expected, offset = new_quote, 0
    elif strategy == 'create_current_history':
        expected = CURRENT + new_quote + '\n\n' + HISTORY + historical_entry(claim_id, old_quote)
        offset = len(CURRENT)
    elif strategy == 'existing_current_history':
        expected = new_quote + '\n\n' + HISTORY + historical_entry(claim_id, old_quote)
        offset = 0
    else:
        return False
    return patch['replacement'] == expected and patch.get('current_offset', 0) == offset
