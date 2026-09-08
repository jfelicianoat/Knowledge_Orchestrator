"""Adaptador de gobernanza; todas las rutas requieren el permiso governance."""
from __future__ import annotations

from typing import TYPE_CHECKING

from knowledge_orchestrator.domain.automation import AutomationPolicyConfig

if TYPE_CHECKING:
    from knowledge_orchestrator.runtime import OrchestratorRuntime


def dispatch(runtime: OrchestratorRuntime, method: str, route: str, ids: dict, query: dict, body: dict,
             owner: str, key: str) -> tuple:
    service, policies = runtime.automation_governance, runtime.automation_policies
    actor = 'api:' + owner
    if route == '/automation/policies':
        if method == 'GET':
            items = policies.list(**query)
            for item in items:
                item['enabled'] = bool(item['enabled'])
            return 200, {'items': items}, {}
        policy = policies.create(AutomationPolicyConfig(**body), actor=actor, key=key)
        return 200, policy, {'Location': f"/api/v1/automation/policies/{policy['policy_id']}"}
    if route == '/automation/policies/{policy_id}':
        if method == 'GET':
            return 200, policies.get(ids['policy_id']), {}
        return 200, policies.update(ids['policy_id'], AutomationPolicyConfig(**body['config']), actor=actor,
                                     **{k: v for k, v in body.items() if k != 'config'}), {}
    if route == '/automation/policies/{policy_id}/activation':
        return 200, service.set_enabled(ids['policy_id'], actor=actor, **body), {}
    if route == '/automation/policies/{policy_id}/history':
        return 200, service.repository.history(ids['policy_id'], **query), {}
    if route == '/automation/policies/{policy_id}/schedule':
        return 200, {'schedule': service.repository.schedule(ids['policy_id'])}, {}
    if route == '/automation/policies/{policy_id}/simulations':
        result = service.simulate(ids['policy_id'], actor=actor, key=key, **body)
        return 200, result, {'Location': f"/api/v1/automation/simulations/{result['simulation_id']}"}
    if route == '/automation/control':
        return 200, policies.control() if method == 'GET' else policies.set_paused(actor=actor, **body), {}
    if route == '/automation/control/history':
        return 200, {'items': service.repository.control_history(**query)}, {}
    if route in {'/automation/simulations', '/automation/runs'}:
        return 200, {'items': service.repository.list_records(route.rsplit('/', 1)[-1], **query)}, {}
    if route == '/automation/simulations/{simulation_id}':
        return 200, policies.simulation(ids['simulation_id']), {}
    if route == '/automation/runs/{run_id}':
        return 200, runtime.automation_execution.repository.get(ids['run_id']), {}
    raise LookupError('Ruta de gobernanza inexistente')
