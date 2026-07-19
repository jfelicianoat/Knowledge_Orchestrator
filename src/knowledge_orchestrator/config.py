from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Nombres de las variables de entorno que permiten reubicar el pipeline y el
# vault sin editar código, p.ej. para desplegar en otra máquina o apuntar a un
# Broker distinto del LAN por defecto.
ENV_ROOT = "KO_ROOT"
ENV_INBOX = "KO_INBOX_DIR"
ENV_OBSIDIAN_VAULT = "KO_OBSIDIAN_VAULT"
ENV_BROKER_URL = "KO_BROKER_URL"
ENV_BROKER_ADMIN_TOKEN = "KO_BROKER_ADMIN_TOKEN"


@dataclass(frozen=True, slots=True)
class PipelinePaths:
    inbox: Path
    staging: Path
    processing: Path
    completed: Path
    failed: Path
    rejected: Path
    state: Path
    logs: Path
    backups: Path
    diagnostics: Path
    obsidian_vault: Path

    @classmethod
    def defaults(cls, home: Path | None = None) -> PipelinePaths:
        user_home = home or Path.home()
        root = Path(os.environ.get(ENV_ROOT) or "C:/YT-Pipeline")
        inbox = os.environ.get(ENV_INBOX)
        vault = os.environ.get(ENV_OBSIDIAN_VAULT)
        return cls(
            inbox=Path(inbox) if inbox else user_home / "Downloads" / "YT-Knowledge-Inbox",
            staging=root / "staging",
            processing=root / "processing",
            completed=root / "completed",
            failed=root / "failed",
            rejected=root / "rejected",
            state=root / "state",
            logs=root / "logs",
            backups=root / "backups",
            diagnostics=root / "diagnostics",
            obsidian_vault=Path(vault) if vault else Path("C:/ObsidianVault/Knowledge"),
        )

    @classmethod
    def under(cls, root: Path) -> PipelinePaths:
        return cls(
            inbox=root / "inbox",
            staging=root / "staging",
            processing=root / "processing",
            completed=root / "completed",
            failed=root / "failed",
            rejected=root / "rejected",
            state=root / "state",
            logs=root / "logs",
            backups=root / "backups",
            diagnostics=root / "diagnostics",
            obsidian_vault=root / "vault",
        )

    @property
    def database(self) -> Path:
        return self.state / "orchestrator.db"

    @property
    def failed_contracts(self) -> Path:
        return self.failed / "contracts"

    @property
    def failed_duplicates(self) -> Path:
        return self.failed / "duplicates"

    @property
    def failed_transcriptions(self) -> Path:
        return self.failed / "transcriptions"

    def ensure_directories(self) -> None:
        for directory in (
            self.inbox,
            self.staging,
            self.processing,
            self.completed,
            self.failed,
            self.failed_contracts,
            self.failed_duplicates,
            self.failed_transcriptions,
            self.rejected,
            self.state,
            self.logs,
            self.backups,
            self.diagnostics,
            self.obsidian_vault,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def _default_broker_url() -> str:
    # El puerto por defecto del Broker cambió de 8080 a 8765 (contrato v2.5).
    return os.environ.get(ENV_BROKER_URL) or "http://broker-machine.local:8765"


def _default_admin_token() -> str | None:
    return os.environ.get(ENV_BROKER_ADMIN_TOKEN) or None


@dataclass(frozen=True, slots=True)
class BrokerSettings:
    base_url: str = field(default_factory=_default_broker_url)
    # Requerido por el Broker en POST/DELETE /api/v1/tasks, PATCH /api/v1/queue y
    # /api/v1/dispatcher/tick solo cuando el operador configura admin_token_env o
    # keyring en el Broker; en LAN sin token configurado, None no cambia nada.
    admin_token: str | None = field(default_factory=_default_admin_token)
    request_timeout_seconds: float = 10.0
    poll_interval_seconds: float = 2.0
    discovery_interval_seconds: float = 300.0
    health_interval_seconds: float = 10.0
    dispatcher_interval_seconds: float = 0.5
    max_context_tokens: int = 16_000
    submission_backoff_seconds: tuple[float, ...] = (30.0, 60.0, 120.0)
