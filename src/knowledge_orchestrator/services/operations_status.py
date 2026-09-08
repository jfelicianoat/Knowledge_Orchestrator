"""Estado de servicios y actividad acotada; nunca devuelve credenciales ni cuerpos."""
from __future__ import annotations

import re
import time
from contextlib import closing
from typing import TYPE_CHECKING

from knowledge_orchestrator.api.openapi import ROUTES

if TYPE_CHECKING:
    from knowledge_orchestrator.runtime import OrchestratorRuntime

API_ACTIVITY_WINDOW = 1000


class OperationsStatusService:
    def __init__(self, runtime: OrchestratorRuntime) -> None:
        self.runtime = runtime

    def snapshot(self) -> dict:
        runtime = self.runtime
        api = runtime.api_server.snapshot()
        with closing(runtime.database.connect(readonly=True)) as connection:
            connection.execute('BEGIN')
            rows = connection.execute(
                'SELECT event_id,created_at,json_extract(details_json,\'$.client\') AS client,'
                "json_extract(details_json,'$.route') AS route,json_extract(details_json,'$.method') AS method,"
                "json_extract(details_json,'$.status') AS status FROM events "
                "WHERE event_type='API_REQUEST' AND json_valid(details_json) "
                'ORDER BY event_id DESC LIMIT ?', (API_ACTIVITY_WINDOW,)).fetchall()
            sources = dict(connection.execute(
                "SELECT count(*) AS total,COALESCE(sum(json_extract(config_json,'$.enabled')=1),0) AS enabled,"
                'COALESCE(sum(failures>0),0) AS errors,COALESCE(sum(lease_until>?),0) AS checking,'
                'min(CASE WHEN json_extract(config_json,\'$.enabled\')=1 THEN next_check_at END) AS next_check_at '
                'FROM monitored_sources', (time.time(),)).fetchone())
            batches = {row['status']: row['count'] for row in connection.execute(
                'SELECT status,count(*) AS count FROM review_batches GROUP BY status')}
            analysis = {row['status']: row['count'] for row in connection.execute(
                'SELECT status,count(*) AS count FROM semantic_jobs GROUP BY status')}
            policies = dict(connection.execute('SELECT count(*) AS total,COALESCE(sum(enabled),0) AS enabled '
                                                'FROM automation_policies').fetchone())
            control = dict(connection.execute('SELECT paused,revision FROM automation_control '
                                               'WHERE singleton=1').fetchone())
            automatic_runs = {row['status']: row['count'] for row in connection.execute(
                'SELECT status,count(*) AS count FROM automation_runs GROUP BY status')}
            reserved_today = connection.execute('SELECT count(*) FROM automation_reservations '
                                                  "WHERE utc_day=strftime('%Y-%m-%d','now')").fetchone()[0]
            schedules = dict(connection.execute(
                'SELECT count(*) AS total,COALESCE(sum(failures>0),0) AS errors,'
                'COALESCE(sum(lease_until>?),0) AS evaluating FROM automation_schedules',
                (time.time(),)).fetchone())
        consumers = {client['name']: {**client, 'configured': True, 'requests': 0, 'errors': 0, 'last_seen': None}
                     for client in api['clients']}
        activity = []
        allowed_routes = {row[1] for row in ROUTES}
        for row in rows:
            name = row['client']
            name = name if isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', name) else None
            status = row['status'] if type(row['status']) is int and 100 <= row['status'] <= 599 else None
            route = row['route'] if row['route'] in allowed_routes else 'unmatched'
            methods = {'GET', 'POST', 'PATCH', 'PUT', 'DELETE', 'HEAD', 'OPTIONS'}
            method = row['method'] if row['method'] in methods else '?'
            activity.append({'event_id': row['event_id'], 'created_at': row['created_at'], 'client': name,
                             'route': route, 'method': method, 'status': status})
            if name is not None:
                consumer = consumers.setdefault(name, {'name': name, 'scopes': [], 'configured': False,
                                                        'requests': 0, 'errors': 0, 'last_seen': None})
                consumer['requests'] += 1
                consumer['errors'] += int(status is not None and status >= 400)
                if consumer['last_seen'] is None:
                    consumer['last_seen'] = row['created_at']
        automation_running = runtime.automation_worker.running
        reason = ('PAUSED' if control['paused'] else 'NO_ENABLED_POLICIES' if not policies['enabled']
                  else 'RUNNING' if automation_running else 'WORKER_STOPPED')
        return {'api': api, 'consumers': sorted(consumers.values(), key=lambda item: item['name']),
                'activity': activity, 'activity_window': API_ACTIVITY_WINDOW, 'sources': sources,
                'batches': batches, 'analysis': analysis,
                'workers': {'sources': runtime.source_worker.running, 'reviews': runtime.review_worker.running,
                            'broker': runtime.broker_worker.running, 'automations': automation_running},
                'autoapproval': {'enabled': reason == 'RUNNING', 'engine_available': True, 'reason': reason,
                                 'policies': policies, 'control': control,
                                 'runs': automatic_runs, 'reserved_today': reserved_today, 'schedules': schedules}}
