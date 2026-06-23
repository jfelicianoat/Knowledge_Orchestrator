from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ContractIssue:
    boundary: str
    field: str
    reason: str
    contract_version: str | None
    code: str = "CONTRACT_VALIDATION_FAILED"

    def as_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "boundary": self.boundary,
            "field": self.field,
            "reason": self.reason,
            "contract_version": self.contract_version,
        }


class CaptureContractError(ValueError):
    def __init__(self, issue: ContractIssue):
        super().__init__(f"{issue.field}: {issue.reason}")
        self.issue = issue


class FileLockedError(OSError):
    """El fichero siguió bloqueado después de todos los reintentos."""


class FileStabilityError(OSError):
    """El fichero no alcanzó tres observaciones estables."""


class IngestionCancelled(RuntimeError):
    """La aplicación solicitó detener una ingesta que todavía estaba esperando."""


class RecoveryError(RuntimeError):
    """No se pudo reconciliar un estado durable con el filesystem."""
