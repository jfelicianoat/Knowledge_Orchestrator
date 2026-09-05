"""Persistencia de las ubicaciones elegidas por la persona usuaria."""
from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

from knowledge_orchestrator.config import (
    ENV_INBOX,
    ENV_OBSIDIAN_VAULT,
    ENV_ROOT,
    PipelinePaths,
)


def _settings_path(home: Path | None = None) -> Path:
    if home is None and os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"])
    else:
        base = (home or Path.home()) / "AppData" / "Local"
    return base / "Knowledge Orchestrator" / "config" / "paths.json"


def _paths_from_locations(data_root: Path, inbox: Path, obsidian_vault: Path) -> PipelinePaths:
    return replace(
        PipelinePaths.under(data_root),
        inbox=inbox,
        obsidian_vault=obsidian_vault,
    )


class PipelinePathStore:
    """Guarda solo las tres ubicaciones comprensibles que se pueden elegir."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _settings_path()

    def load(self) -> dict[str, Path]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        result: dict[str, Path] = {}
        for key in ("data_root", "inbox", "obsidian_vault"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                result[key] = Path(value)
        return result

    def save(self, data_root: Path | str, inbox: Path | str, obsidian_vault: Path | str) -> PipelinePaths:
        raw_locations = {
            "data_root": data_root,
            "inbox": inbox,
            "obsidian_vault": obsidian_vault,
        }
        if any(not str(value).strip() for value in raw_locations.values()):
            raise ValueError("Las tres carpetas deben tener una ubicación.")
        locations = {
            key: Path(value).expanduser().resolve()
            for key, value in raw_locations.items()
        }
        paths = _paths_from_locations(**locations)
        paths.ensure_directories()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({key: str(value) for key, value in locations.items()}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
        return paths


def load_pipeline_paths(*, config_path: Path | None = None, home: Path | None = None) -> PipelinePaths:
    """Combina valores guardados con los overrides explícitos del entorno."""

    defaults = PipelinePaths.defaults(home=home)
    stored = PipelinePathStore(config_path or _settings_path(home)).load()
    data_root = stored.get("data_root", defaults.state.parent)
    paths = _paths_from_locations(
        data_root,
        stored.get("inbox", defaults.inbox),
        stored.get("obsidian_vault", defaults.obsidian_vault),
    )
    if os.environ.get(ENV_ROOT):
        paths = replace(
            paths,
            staging=defaults.staging,
            processing=defaults.processing,
            completed=defaults.completed,
            failed=defaults.failed,
            rejected=defaults.rejected,
            state=defaults.state,
            logs=defaults.logs,
            backups=defaults.backups,
            diagnostics=defaults.diagnostics,
        )
    if os.environ.get(ENV_INBOX):
        paths = replace(paths, inbox=defaults.inbox)
    if os.environ.get(ENV_OBSIDIAN_VAULT):
        paths = replace(paths, obsidian_vault=defaults.obsidian_vault)
    return paths
