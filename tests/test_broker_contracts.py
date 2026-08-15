from __future__ import annotations

import json
import unittest
from pathlib import Path

from knowledge_orchestrator.domain.broker_contracts import (
    BrokerContractError,
    normalize_capabilities_response,
    validate_accepted_response,
    validate_create_task_request,
    validate_task_status_response,
)


def valid_request() -> dict:
    return {
        "idempotency_key": "capture:1:single",
        "request_id": "task_1",
        "content": {
            "prompt": (
                "<system_instructions>Analiza</system_instructions>\n"
                "<user_request>Contenido final</user_request>"
            ),
            "attachments": [],
            "metadata": {"workflow_id": "wf_1", "step_id": "single"},
        },
        "output": {"format": "markdown", "json_schema": None, "language": "es"},
        "generation": {"temperature": 0.3, "max_output_tokens": 1000},
        "model_requirements": {
            "preferred_model": "llama3.1:8b", "fallback_allowed": True,
            "cloud_allowed": False, "allowed_providers": ["ollama"], "max_cost_usd": 0.05,
        },
        "execution": {
            "strategy": "single", "preset": "fast", "scheduling": "adaptive",
            "max_proposers": 1, "max_judges": 0, "max_rounds": 1,
            "timeout_seconds": 600, "early_stop": True,
            "selection": {
                "mode": "auto", "diversity_policy": "different_families",
                "arbiter_policy": "strongest_available", "allow_substitution": True,
                "proposers": [], "required_proposers": [], "proposer_count": 1,
            },
        },
        "risk": {"data_classification": "local_only", "human_review_required": False},
        "priority": 100,
    }


def accepted_response() -> dict:
    return {
        "task_id": "broker_task_1", "status": "queued", "execution_strategy": "single",
        "execution_preset": "fast", "selection_mode": "auto",
        "status_url": "/api/v1/tasks/broker_task_1", "cancel_url": "/api/v1/tasks/broker_task_1",
    }


class BrokerContractTests(unittest.TestCase):
    def test_shared_v2_single_fixture_matches_orchestrator_validator(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "broker_v2_single_request.json"
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        self.assertIs(validate_create_task_request(payload), payload)

    def test_validates_v2_request_acceptance_and_result(self) -> None:
        request = valid_request()
        self.assertIs(validate_create_task_request(request), request)
        accepted = accepted_response()
        self.assertIs(validate_accepted_response(accepted), accepted)
        success = {
            "task_id": "broker_task_1", "status": "completed", "request_id": "task_1",
            "created_at": "2026-06-23T10:00:00Z", "updated_at": "2026-06-23T10:01:00Z",
            "execution_strategy": "single", "execution_preset": "fast", "selection_mode": "auto",
            "progress": {"phase": "completed"}, "result": {"result_markdown": "Resultado"}, "error": None,
        }
        self.assertIs(validate_task_status_response(success, "broker_task_1"), success)

    def test_rejects_unresolved_prompt_before_network(self) -> None:
        request = valid_request()
        request["content"]["prompt"] = "Procesa {transcript}"
        with self.assertRaises(BrokerContractError):
            validate_create_task_request(request)

    def test_rejects_malformed_or_mismatched_broker_response(self) -> None:
        malformed = accepted_response()
        malformed.pop("execution_strategy")
        with self.assertRaises(BrokerContractError):
            validate_accepted_response(malformed)
        with self.assertRaises(BrokerContractError):
            validate_task_status_response(
                {
                    "task_id": "wrong", "status": "completed", "created_at": "x", "updated_at": "x",
                    "progress": {}, "result": {"result_markdown": "x"}, "error": None,
                },
                "broker_task_1",
            )

    def test_accepts_v28_auto_strategy_round_trip(self) -> None:
        # Contrato v2.8: la petición puede delegar en el meta-router del Broker
        # y las respuestas conservan "auto" en execution_strategy toda la vida
        # de la tarea (la resolución interna viaja en el evento strategy.routed).
        request = valid_request()
        request["execution"]["strategy"] = "auto"
        self.assertIs(validate_create_task_request(request), request)

        accepted = accepted_response()
        accepted["execution_strategy"] = "auto"
        self.assertIs(validate_accepted_response(accepted), accepted)

        completed = {
            "task_id": "broker_task_1", "status": "completed", "request_id": "task_1",
            "created_at": "2026-07-19T10:00:00Z", "updated_at": "2026-07-19T10:01:00Z",
            "execution_strategy": "auto", "execution_preset": "fast", "selection_mode": "auto",
            "progress": {"phase": "completed"},
            # Aunque el Broker haya resuelto a mixture internamente, para "auto"
            # solo se exige result_markdown: el bloque consensus no es garantía.
            "result": {"result_markdown": "Resultado"}, "error": None,
        }
        self.assertIs(validate_task_status_response(completed, "broker_task_1"), completed)

    def test_accepts_v27_waiting_for_tools_and_slow_preset(self) -> None:
        waiting = {
            "task_id": "broker_task_1", "status": "waiting_for_tools", "request_id": "task_1",
            "created_at": "2026-07-19T10:00:00Z", "updated_at": "2026-07-19T10:01:00Z",
            "execution_strategy": "agent", "execution_preset": "fast", "selection_mode": "auto",
            "progress": {
                "phase": "waiting_for_tools", "agent_iteration": 2, "agent_max_iterations": 6,
            },
            "result": {
                "status": "waiting_for_tools",
                "pending_tool_calls": [
                    {"id": "call_1", "name": "consultar_stock", "arguments": {"sku": "A-1"}},
                ],
            },
            "error": None,
        }
        self.assertIs(validate_task_status_response(waiting, "broker_task_1"), waiting)

        request = valid_request()
        request["execution"]["strategy"] = "mixture_of_agents"
        request["execution"]["preset"] = "slow"
        self.assertIs(validate_create_task_request(request), request)

    def test_v27_derives_data_boundary_when_legacy_fields_are_omitted(self) -> None:
        request = valid_request()
        request["risk"]["data_classification"] = "confidential"
        request["model_requirements"].pop("cloud_allowed")
        request["model_requirements"].pop("allowed_providers")
        self.assertIs(validate_create_task_request(request), request)

        request["model_requirements"]["cloud_allowed"] = True
        with self.assertRaises(BrokerContractError):
            validate_create_task_request(request)

    def test_accepts_v27_ingestion_state_with_nullable_execution_fields(self) -> None:
        payload = {
            "task_id": "ingest_1", "kind": "ingestion", "status": "converting",
            "created_at": "2026-07-26T10:00:00Z", "updated_at": "2026-07-26T10:01:00Z",
            "execution_strategy": None, "execution_preset": None, "selection_mode": None,
            "progress": {"phase": "converting"}, "result": None, "error": None,
        }
        self.assertIs(validate_task_status_response(payload, "ingest_1"), payload)

    def test_accepts_v27_waiting_for_memory_as_non_terminal(self) -> None:
        payload = {
            "task_id": "broker_task_1", "kind": "inference", "status": "waiting_for_memory",
            "created_at": "2026-07-28T10:00:00Z", "updated_at": "2026-07-28T10:01:00Z",
            "execution_strategy": "single", "execution_preset": "fast", "selection_mode": "auto",
            "progress": {"phase": "waiting_for_memory"}, "result": None, "error": None,
        }
        self.assertIs(validate_task_status_response(payload, "broker_task_1"), payload)

    def test_accepts_v28_dependencies_and_waiting_state(self) -> None:
        request = valid_request()
        request.update({
            "group": "capture:1",
            "depends_on": ["broker_parent_1", "broker_parent_2"],
            "depends_on_group": "previous_batch",
        })
        self.assertIs(validate_create_task_request(request), request)

        waiting = {
            "task_id": "broker_task_1", "kind": "inference",
            "status": "waiting_for_dependencies",
            "created_at": "2026-08-15T10:00:00Z", "updated_at": "2026-08-15T10:01:00Z",
            "execution_strategy": "single", "execution_preset": "fast", "selection_mode": "auto",
            "progress": {"phase": "waiting_for_dependencies"}, "result": None, "error": None,
        }
        self.assertIs(validate_task_status_response(waiting, "broker_task_1"), waiting)

        request["depends_on"] = [f"task_{index}" for index in range(65)]
        with self.assertRaisesRegex(BrokerContractError, "depends_on"):
            validate_create_task_request(request)

    def test_rejects_unknown_request_strategy_but_accepts_new_intermediate_status(self) -> None:
        request = valid_request()
        request["execution"]["strategy"] = "swarm"
        with self.assertRaises(BrokerContractError):
            validate_create_task_request(request)
        unknown_status = {
            "task_id": "broker_task_1", "status": "hibernating", "created_at": "x",
            "updated_at": "x", "execution_strategy": "single", "progress": {"phase": "hibernating"},
        }
        self.assertIs(validate_task_status_response(unknown_status, "broker_task_1"), unknown_status)

    def test_requires_v27_failure_retryability_and_tool_call_details(self) -> None:
        failed = {
            "task_id": "broker_task_1", "status": "failed", "created_at": "x", "updated_at": "x",
            "execution_strategy": "single", "progress": {"phase": "failed"},
            "result": None, "error": {"code": "PROVIDER_UNAVAILABLE", "message": "caído"},
        }
        with self.assertRaisesRegex(BrokerContractError, "error.retryable"):
            validate_task_status_response(failed, "broker_task_1")

        waiting = {
            "task_id": "broker_task_1", "status": "waiting_for_tools", "created_at": "x", "updated_at": "x",
            "execution_strategy": "agent",
            "progress": {"phase": "waiting_for_tools", "agent_iteration": 1, "agent_max_iterations": 6},
            "result": {"status": "waiting_for_tools", "pending_tool_calls": []}, "error": None,
        }
        with self.assertRaisesRegex(BrokerContractError, "pending_tool_calls"):
            validate_task_status_response(waiting, "broker_task_1")

    def test_normalizes_v28_capabilities_and_preserves_future_fields(self) -> None:
        normalized = normalize_capabilities_response({
            "contract_version": "2.8",
            "strategies": ["single", "auto"],
            "agent_skills_egress": ["web_search", "fetch_url"],
            "task_dependencies": True,
            "presets": {"single": ["fast"], "broken": "slow"},
            "scheduling_by_preset": {"fast": ["sequential"]},
            "ingestion_formats": {"text": [".md", ".txt"]},
            "work_lanes": "inference",
            "future_field": {"kept": True},
        })
        self.assertEqual(normalized["presets"], {"single": ["fast"]})
        self.assertEqual(normalized["ingestion_formats"]["text"], [".md", ".txt"])
        self.assertEqual(normalized["work_lanes"], ["inference"])
        self.assertEqual(normalized["agent_skills_egress"], ["web_search", "fetch_url"])
        self.assertTrue(normalized["task_dependencies"])
        self.assertEqual(normalized["future_field"], {"kept": True})

    def test_accepts_v28_result_warnings_agent_citations_and_second_round(self) -> None:
        payload = {
            "task_id": "broker_consensus", "status": "completed",
            "created_at": "2026-08-15T10:00:00Z", "updated_at": "2026-08-15T10:01:00Z",
            "execution_strategy": "mixture_of_agents", "execution_preset": "verified",
            "selection_mode": "auto", "progress": {"phase": "completed"},
            "result": {
                "assistant_content": "Resultado con revisión",
                "warnings": ["Una dependencia terminó con avisos"],
                "agent": {
                    "final_turn": True, "stop_reason": "completed",
                    "citations": {"cited": 2, "unsupported": ["https://invalid.example"]},
                },
                "consensus": {
                    "proposers_completed": 2, "synthesized": True,
                    "rounds": 2, "confidence": 0.84,
                },
                "scheduling": {"mode_used": "parallel"},
                "usage": {"invocations": 3},
                "models_used": [{"model": "a"}, {"model": "b"}, {"model": "arbiter"}],
            },
            "error": None,
        }
        self.assertIs(validate_task_status_response(payload, "broker_consensus"), payload)

        payload["result"]["consensus"]["confidence"] = 1.2
        with self.assertRaisesRegex(BrokerContractError, "confidence"):
            validate_task_status_response(payload, "broker_consensus")

    def test_validates_complete_consensus_metadata_and_rejects_false_quorum(self) -> None:
        payload = {
            "task_id": "broker_consensus", "status": "completed", "request_id": "local_consensus",
            "created_at": "2026-06-23T10:00:00Z", "updated_at": "2026-06-23T10:01:00Z",
            "execution_strategy": "mixture_of_agents", "execution_preset": "fast", "selection_mode": "auto",
            "progress": {"phase": "completed", "invocations_completed": 4, "invocations_total": 4},
            "result": {
                "result_markdown": "# Consenso",
                "consensus": {"proposers_completed": 3, "confidence": 0.7},
                "scheduling": {"mode_used": "parallel", "waves": 1},
                "usage": {"invocations": 4, "cost_usd": 0.01},
                "models_used": [{"model": "a"}, {"model": "b"}, {"model": "c"}, {"model": "arbiter"}],
            },
            "error": None,
        }
        self.assertIs(validate_task_status_response(payload, "broker_consensus"), payload)
        payload["result"]["consensus"]["proposers_completed"] = 1
        with self.assertRaises(BrokerContractError):
            validate_task_status_response(payload, "broker_consensus")

    def test_accepts_degraded_consensus_when_arbiters_failed(self) -> None:
        payload = {
            "task_id": "broker_degraded", "status": "completed", "request_id": "local_degraded",
            "created_at": "2026-08-12T10:00:00Z", "updated_at": "2026-08-12T10:01:00Z",
            "execution_strategy": "mixture_of_agents", "execution_preset": "fast", "selection_mode": "auto",
            "progress": {"phase": "completed", "invocations_completed": 4, "invocations_total": 4},
            "result": {
                "assistant_content": "Mejor propuesta disponible",
                "model_used": {"provider": "ollama", "deployment": "local", "model": "proposer-a"},
                "models_used": [{"model": "proposer-a"}, {"model": "proposer-b"}],
                "consensus": {
                    "proposers_completed": 2, "synthesized": False,
                    "warnings": ["No fue posible sintetizar"],
                },
                "scheduling": {"mode_used": "sequential"},
                "usage": {"invocations": 4, "cost_usd": 0.01},
                "arbiter_failures": [
                    {"model": {"model": "arbiter-a"}, "code": "PROMPT_ECHOED", "message": "eco"},
                    {"model": {"model": "arbiter-b"}, "code": "DEGENERATE_OUTPUT", "message": "repetición"},
                ],
            },
            "error": None,
        }
        self.assertIs(validate_task_status_response(payload, "broker_degraded"), payload)

        payload["result"]["arbiter_failures"] = []
        with self.assertRaisesRegex(BrokerContractError, "arbiter_failures"):
            validate_task_status_response(payload, "broker_degraded")


if __name__ == "__main__":
    unittest.main()
