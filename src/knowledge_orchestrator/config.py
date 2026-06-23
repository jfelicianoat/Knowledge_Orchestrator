from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
    obsidian_vault: Path

    @classmethod
    def defaults(cls, home: Path | None = None) -> "PipelinePaths":
        user_home = home or Path.home()
        root = Path("C:/YT-Pipeline")
        return cls(
            inbox=user_home / "Downloads" / "YT-Knowledge-Inbox",
            staging=root / "staging",
            processing=root / "processing",
            completed=root / "completed",
            failed=root / "failed",
            rejected=root / "rejected",
            state=root / "state",
            logs=root / "logs",
            obsidian_vault=Path("C:/ObsidianVault/Knowledge"),
        )

    @classmethod
    def under(cls, root: Path) -> "PipelinePaths":
        return cls(
            inbox=root / "inbox",
            staging=root / "staging",
            processing=root / "processing",
            completed=root / "completed",
            failed=root / "failed",
            rejected=root / "rejected",
            state=root / "state",
            logs=root / "logs",
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
            self.obsidian_vault,
        ):
            directory.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True, slots=True)
class BrokerSettings:
    base_url: str = "http://broker-machine.local:8080"
    request_timeout_seconds: float = 10.0
    poll_interval_seconds: float = 2.0
    discovery_interval_seconds: float = 300.0
    health_interval_seconds: float = 10.0
    dispatcher_interval_seconds: float = 0.5
    max_context_tokens: int = 16_000
    submission_backoff_seconds: tuple[float, ...] = (30.0, 60.0, 120.0)
