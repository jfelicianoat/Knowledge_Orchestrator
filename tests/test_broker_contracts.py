from __future__ import annotations

import unittest

from knowledge_orchestrator.domain.broker_contracts import (
    BrokerContractError,
    validate_accepted_response,
    validate_create_task_request,
    validate_task_status_response,
)


def valid_request() -> dict:
    return {
        "contract_version": "1.0",
        "task_id": "task_1",
        "idempotency_key": "capture:1:single",
        "routing": {
            "preferred_model": "llama3.1:8b",
            "fallback_allowed": True,
            "quality_priority": "high",
            "max_cost_usd": 0.05,
        },
        "inference": {
            "kind": "chat",
            "messages": [
                {"role": "system", "content": "Analiza la fuente"},
                {"role": "user", "content": "Contenido final"},
            ],
            "temperature": 0.3,
            "max_output_tokens": 1000,
            "response_format": "text",
        },
        "client_context": {"workflow_id": "wf_1", "step_id": "single"},
    }


class BrokerContractTests(unittest.TestCase):
    def test_validates_both_sides_of_chat_contract(self) -> None:
        request = valid_request()
        self.assertIs(validate_create_task_request(request), request)
        accepted = {
            "task_id": "task_1",
            "status": "queued",
            "status_url": "/api/v1/tasks/task_1",
            "cancel_url": "/api/v1/tasks/task_1",
        }
        self.assertIs(validate_accepted_response(accepted, "task_1"), accepted)
        success = {
            "task_id": "task_1",
            "status": "success",
            "result": {"assistant_content": "Resultado"},
            "error": None,
        }
        self.assertIs(validate_task_status_response(success, "task_1"), success)

    def test_rejects_unresolved_prompt_before_network(self) -> None:
        request = valid_request()
        request["inference"]["messages"][1]["content"] = "Procesa {transcript}"
        with self.assertRaises(BrokerContractError):
            validate_create_task_request(request)

    def test_rejects_malformed_or_mismatched_broker_response(self) -> None:
        with self.assertRaises(BrokerContractError):
            validate_accepted_response(
                {"task_id": "other", "status": "queued", "status_url": "/x", "cancel_url": "/x"},
                "task_1",
            )
        with self.assertRaises(BrokerContractError):
            validate_task_status_response(
                {"task_id": "task_1", "status": "success", "result": {}, "error": None},
                "task_1",
            )


if __name__ == "__main__":
    unittest.main()
