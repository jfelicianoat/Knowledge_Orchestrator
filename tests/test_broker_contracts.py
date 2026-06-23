from __future__ import annotations

import unittest
import json
from pathlib import Path

from knowledge_orchestrator.domain.broker_contracts import (
    BrokerContractError,
    validate_accepted_response,
    validate_create_task_request,
    validate_task_status_response,
)


def valid_request() -> dict:
    return {
        "idempotency_key": "capture:1:single",
        "request_id": "task_1",
        "content": {
            "prompt": "<system_instructions>Analiza</system_instructions>\n<user_request>Contenido final</user_request>",
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
        fixture = Path(__file__).parents[2] / "docs" / "contracts" / "broker_v2_single_request.json"
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


if __name__ == "__main__":
    unittest.main()
