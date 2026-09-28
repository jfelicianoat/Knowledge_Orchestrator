"""Persistencia de las ubicaciones elegidas por la persona usuaria."""
from __future__ import annotations

import json
import os
import uuid
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


def _inside(child: Path, parent: Path) -> bool:
    return child == parent or child.is_relative_to(parent)


def validate_locations(data_root: Path, inbox: Path, obsidian_vault: Path) -> None:
    """Rechaza combinaciones que las operaciones no soportan (auditoría H13).

    - Bandeja y bóveda no pueden coincidir ni contenerse: cada nota publicada
      volvería a entrar como documento nuevo.
    - La bandeja no puede estar dentro de la raíz de datos (ni al revés): las
      carpetas internas se mueven y renombran solas.
    - La bóveda sí puede contener la raíz de datos (es el caso de quien la
      guarda en `.knowledge-orchestrator`), pero no ser ella.
    """

    if _inside(inbox, obsidian_vault) or _inside(obsidian_vault, inbox):
        raise ValueError("La carpeta vigilada y la de resultados no pueden coincidir ni estar una dentro de otra: "
                         "cada nota publicada volvería a entrar como un documento nuevo.")
    if _inside(inbox, data_root) or _inside(data_root, inbox):
        raise ValueError("La carpeta vigilada no puede estar dentro de la carpeta de datos ni contenerla.")
    if data_root == obsidian_vault or _inside(obsidian_vault, data_root):
        raise ValueError("La carpeta de resultados no puede ser la carpeta de datos ni estar dentro de ella.")


def probe_vault(vault: Path) -> None:
    """Comprueba que en la bóveda se puede instalar una nota sin sustituir nada.

    Se prueba con dos ficheros temporales la misma operación que usa la
    publicación. Si el volumen no la admite, se dice al elegir la carpeta y no
    cuando el primer documento se queda en PUBLISHING.
    """

    from knowledge_orchestrator.services.filesystem import install_new_file

    token = uuid.uuid4().hex
    temporary, destination = vault / f".ko-probe-{token}.tmp", vault / f".ko-probe-{token}.md"
    try:
        temporary.write_bytes(b"probe")
        install_new_file(temporary, destination)
        if destination.read_bytes() != b"probe":
            raise ValueError("La carpeta de resultados no conserva los ficheros escritos")
    except OSError as error:
        raise ValueError(
            f"No se pueden publicar notas en {vault}: el volumen no admite instalarlas sin sobrescribir ({error})."
        ) from error
    finally:
        temporary.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)


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
        validate_locations(**locations)
        paths = _paths_from_locations(**locations)
        paths.ensure_directories()
        probe_vault(paths.obsidian_vault)
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


#: Carpetas que un cliente de sincronización reescribe por su cuenta.
SYNC_MARKERS = ("mi unidad", "my drive", "google drive", "onedrive", "dropbox", "icloud")
_DRIVE_REMOTE = 4


def _is_network_drive(path: Path) -> bool:
    if os.name != "nt":
        return False
    import ctypes

    anchor = path.anchor or str(path)
    try:
        return int(ctypes.windll.kernel32.GetDriveTypeW(anchor)) == _DRIVE_REMOTE
    except (AttributeError, OSError):
        return False


def storage_warnings(paths: PipelinePaths) -> list[str]:
    """Avisos sobre dónde vive la base operativa. No bloquean: explican el riesgo.

    La instalación real del usuario tenía la raíz de datos en Google Drive y su
    base registraba «disk I/O error»: SQLite en modo WAL no admite que otro
    proceso (el cliente de sincronización) toque sus ficheros. La bóveda puede
    estar donde se quiera; la base, mejor en un disco local.
    """

    root = paths.state.parent
    lowered = str(root).replace("\\", "/").lower()
    warnings: list[str] = []
    if any(marker in lowered for marker in SYNC_MARKERS) or _is_network_drive(root):
        warnings.append(
            "La carpeta de datos está en una unidad sincronizada o de red. La base de datos de la aplicación "
            "puede corromperse o fallar con «disk I/O error» ahí. Elige una carpeta de datos local "
            "(por ejemplo en este equipo); la bóveda de Obsidian puede seguir en la nube."
        )
    return warnings
