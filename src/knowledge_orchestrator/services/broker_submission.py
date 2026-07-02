from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from knowledge_orchestrator.domain.broker_contracts import BrokerContractError
from knowledge_orchestrator.integrations.broker_client import (
    BrokerClient,
    PermanentBrokerError,
    TransientBrokerError,
)

DispatchKind = Literal["accepted", "retry", "exhausted", "permanent"]


@dataclass(frozen=True, slots=True)
class DispatchDecision:
    kind: DispatchKind
    response: dict[str, Any] | None = None
    retry_at: str | None = None
    message: str | None = None


async def attempt_broker_submission(
    client: BrokerClient,
    request_json: str,
    *,
    attempt: int,
    backoff_seconds: tuple[float, ...],
) -> DispatchDecision:
    """Envía una solicitud ya persistida al Broker y clasifica el resultado.

    Comparte la lógica de reintento/backoff entre BrokerDispatcher y
    SemanticBrokerProcessor. Solo se tratan como fallo permanente los errores
    de contrato conocidos (incluido un JSON local corrupto, que nunca podrá
    reintentarse); cualquier otro ``ValueError`` propaga como bug real en
    lugar de reclasificarse silenciosamente como fallo de contrato.
    """
    try:
        response = await client.create_task(json.loads(request_json))
    except TransientBrokerError as error:
        retry_index = attempt - 1
        if retry_index < len(backoff_seconds):
            retry_at = datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds[retry_index])
            return DispatchDecision("retry", retry_at=retry_at.isoformat(), message=str(error))
        return DispatchDecision("exhausted", message=str(error))
    except (PermanentBrokerError, BrokerContractError, json.JSONDecodeError) as error:
        return DispatchDecision("permanent", message=str(error))
    return DispatchDecision("accepted", response=response)
