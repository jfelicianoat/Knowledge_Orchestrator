from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Callable

import yaml

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.domain.publication_models import NoteRecord, PublishableWorkflow, ReprocessIntent
from knowledge_orchestrator.repositories.capture_repository import CaptureRepository
from knowledge_orchestrator.repositories.domain_repository import DomainRepository
from knowledge_orchestrator.repositories.publication_repository import PublicationRepository

from .filesystem import write_synced
from .workflow_planner import WorkflowPlanner


class PublicationError(ValueError):
    pass


class ResultMarkdownError(PublicationError):
    pass


def validate_result_markdown(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResultMarkdownError("El resultado Markdown está vacío")
    if "\x00" in value:
        raise ResultMarkdownError("El resultado Markdown contiene bytes nulos")
    if value.lstrip("\ufeff \t\r\n").startswith("---"):
        raise ResultMarkdownError("El LLM no debe generar frontmatter")
    if len(value.encode("utf-8")) > 20 * 1024 * 1024:
        raise ResultMarkdownError("El resultado Markdown supera 20 MiB")
    return value.strip() + "\n"


def _safe_filename(value: str, fallback: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", value).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)[:120].strip(" .")
    return cleaned or fallback


def _safe_identifier(value: str) -> str:
    cleaned = _safe_filename(value, "capture")
    if len(cleaned) <= 64:
        return cleaned
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
    return f"{cleaned[:53]}-{digest}"


class PublicationService:
    """Publica, rechaza y reprocesa notas sin perder la fuente original.

    Aqui el orden importa bastante:
    - Primero se guarda una intencion durable en SQLite.
    - Luego se materializan ficheros con temporales y replace atomico.
    - Al recuperar, repetimos pasos ya hechos sin duplicar notas ni borrar evidencias.
    """

    def __init__(
        self,
        paths: PipelinePaths,
        captures: CaptureRepository,
        domains: DomainRepository,
        repository: PublicationRepository,
        planner: WorkflowPlanner,
        *,
        checkpoint: Callable[[str], None] | None = None,
        on_published: Callable[[NoteRecord], None] | None = None,
    ) -> None:
        self.paths = paths
        self.captures = captures
        self.domains = domains
        self.repository = repository
        self.planner = planner
        self.checkpoint = checkpoint or (lambda _name: None)
        self.on_published = on_published or (lambda _note: None)

    def publish_ready(self) -> int:
        published = 0
        for workflow in self.repository.list_publishable():
            try:
                self.publish(workflow)
            except ResultMarkdownError as error:
                self.repository.fail_publication(workflow, str(error))
            else:
                published += 1
        return published

    def publish(self, workflow: PublishableWorkflow) -> NoteRecord:
        """Materializa un workflow completado en Obsidian y archiva su fuente."""

        capture = self.captures.get(workflow.capture_id)
        topic = self.domains.get_topic(workflow.topic_id)
        profile = self.domains.get_profile(workflow.profile_id)
        if capture is None or topic is None or profile is None:
            raise PublicationError("Faltan captura, tema o perfil para publicar")
        body = validate_result_markdown(workflow.final_result)
        metadata = json.loads(capture.metadata_json)
        frontmatter = {
            "title": capture.title,
            "source": metadata.get("source_url"),
            "source_type": capture.source_type,
            "channel": metadata.get("channel"),
            "published_date": metadata.get("published_date"),
            "captured_at": metadata.get("captured_at"),
            "processed_at": workflow.processed_at,
            "profile_used": profile.name,
            "topic": topic.name,
            "obsolescence_date": capture.obsolescence_date,
            "capture_id": capture.capture_id,
            "revision": workflow.revision,
            "status": "processed",
        }
        frontmatter = {key: value for key, value in frontmatter.items() if value is not None}
        document = "---\n" + yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False) + "---\n\n" + body
        capture_label = _safe_identifier(capture.capture_id)
        suffix = capture_label if workflow.revision == 1 else f"{capture_label}-r{workflow.revision}"
        filename = f"{_safe_filename(capture.title, capture.capture_id)} [{suffix}].md"
        destination = self.paths.obsidian_vault / topic.folder / filename
        temporary = destination.with_name(f".{destination.name}.{workflow.workflow_id}.tmp")
        archive = self.paths.completed / f"{capture_label}-r{workflow.revision}-{_safe_filename(capture.original_filename, 'source.md')}"
        digest = hashlib.sha256(document.encode("utf-8")).hexdigest()
        note = self.repository.create_intent(
            workflow, vault_path=destination, temp_path=temporary, content_hash=digest, source_archive_path=archive,
        )
        # Este checkpoint prueba que la intencion ya existe antes de tocar el vault.
        self.checkpoint("publication_intent")
        self._materialize_note(note, document)
        self.checkpoint("note_renamed")
        self.repository.mark_published(note.note_id)
        self.checkpoint("note_persisted")
        self._archive_source(self.repository.get_note(note.note_id) or note)
        self.checkpoint("source_archived")
        self.repository.complete_capture(note.note_id)
        published_note = self.repository.get_note(note.note_id) or note
        self.on_published(published_note)
        return published_note

    def recover(self) -> None:
        """Continua publicaciones, rechazos y reprocesos que quedaron a medias."""

        for note in self.repository.list_notes_by_status("PUBLISHING"):
            workflow = self.repository.get_workflow_for_note(note.note_id)
            self.publish(workflow)
        for note in self.repository.list_notes_by_status("PUBLISHED"):
            capture = self.captures.get(note.capture_id)
            if capture and capture.status.value != "COMPLETED":
                self._archive_source(note)
                self.repository.complete_capture(note.note_id)
                self.on_published(self.repository.get_note(note.note_id) or note)
        for note in self.repository.list_notes_by_status("REJECTING"):
            self._finish_rejection(note)
        for intent in self.repository.list_reprocess_intents("PREPARED", "COPIED"):
            self._resume_reprocess(intent)

    def reject(self, note_id: int) -> NoteRecord:
        note = self.repository.get_note(note_id)
        if note is None:
            raise ValueError("Nota inexistente")
        rejected_note = self.paths.rejected / "notes" / f"{_safe_identifier(note.capture_id)}-r{note.revision}.md"
        rejected_source = self.paths.rejected / "sources" / note.source_archive_path.name
        note = self.repository.prepare_rejection(
            note_id, rejected_note=rejected_note, rejected_source=rejected_source,
        )
        self.checkpoint("rejection_intent")
        self._finish_rejection(note)
        return self.repository.get_note(note_id) or note

    def _finish_rejection(self, note: NoteRecord) -> None:
        capture = self.captures.get(note.capture_id)
        if note.rejected_path is None or capture is None or capture.rejected_source_path is None:
            raise PublicationError("Intención de rechazo incompleta")
        self._move_idempotent(note.vault_path, note.rejected_path)
        self.checkpoint("note_rejected_move")
        self._move_idempotent(note.source_archive_path, capture.rejected_source_path)
        self.checkpoint("source_rejected_move")
        self.repository.complete_rejection(note.note_id)

    def reprocess(self, note_id: int) -> str:
        note = self.repository.get_note(note_id)
        capture = self.captures.get(note.capture_id) if note else None
        if note is None or note.status != "REJECTED" or capture is None or capture.rejected_source_path is None:
            raise ValueError("Solo se puede reprocesar una nota rechazada con fuente conservada")
        revision = self.repository.next_revision(note.capture_id)
        target = self.paths.processing / f"{_safe_identifier(note.capture_id)}-r{revision}.md"
        intent = self.repository.create_reprocess_intent(
            note.capture_id, note.note_id, revision, capture.rejected_source_path, target,
        )
        self.checkpoint("reprocess_intent")
        return self._resume_reprocess(intent)

    def _resume_reprocess(self, intent: ReprocessIntent) -> str:
        if intent.status == "PREPARED":
            self._copy_atomic(intent.source_path, intent.target_path)
            self.checkpoint("reprocess_copied")
            self.repository.mark_reprocess_copied(intent.intent_id, intent.target_path)
        workflow_id = self.planner.plan_capture(intent.capture_id, revision=intent.revision)
        self.repository.mark_reprocess_planned(intent.intent_id)
        return workflow_id

    def _materialize_note(self, note: NoteRecord, document: str) -> None:
        encoded = document.encode("utf-8")
        if note.vault_path.exists() and self._hash(note.vault_path) == note.content_hash:
            return
        if note.temp_path is None:
            raise PublicationError("La intención no conserva temporal")
        write_synced(note.temp_path, encoded)
        note.vault_path.parent.mkdir(parents=True, exist_ok=True)
        # La intencion ya esta persistida; el replace deja la nota entera o sin tocar.
        os.replace(note.temp_path, note.vault_path)
        if self._hash(note.vault_path) != note.content_hash:
            raise PublicationError("El hash de la nota publicada no coincide")

    def _archive_source(self, note: NoteRecord) -> None:
        capture = self.captures.get(note.capture_id)
        if capture is None:
            raise PublicationError("Captura inexistente")
        if note.source_archive_path.exists():
            return
        if capture.processing_path is None or not capture.processing_path.exists():
            raise PublicationError("No existe la fuente en processing ni en completed")
        note.source_archive_path.parent.mkdir(parents=True, exist_ok=True)
        # Archivamos la fuente solo despues de publicar la nota; asi siempre queda evidencia local.
        os.replace(capture.processing_path, note.source_archive_path)

    @staticmethod
    def _move_idempotent(source: Path, target: Path) -> None:
        if target.exists():
            return
        if not source.exists():
            raise PublicationError(f"No existe el fichero que debe moverse: {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, target)

    @staticmethod
    def _copy_atomic(source: Path, target: Path) -> None:
        if target.exists():
            return
        if not source.exists():
            raise PublicationError("No existe la fuente rechazada")
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with source.open("rb") as source_stream, temporary.open("wb") as target_stream:
                shutil.copyfileobj(source_stream, target_stream)
                target_stream.flush()
                os.fsync(target_stream.fileno())
            # Para reprocesar copiamos, no movemos: el rechazo debe conservar su evidencia.
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
