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
        ):
            directory.mkdir(parents=True, exist_ok=True)
