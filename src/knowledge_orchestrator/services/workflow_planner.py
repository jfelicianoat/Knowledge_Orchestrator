from __future__ import annotations

import json

from knowledge_orchestrator.domain.broker_contracts import validate_create_task_request
from knowledge_orchestrator.domain.broker_models import PlannedTask, StepKind, TaskStatus
from knowledge_orchestrator.repositories.capture_repository import CaptureRepository
from knowledge_orchestrator.repositories.domain_repository import DomainRepository
from knowledge_orchestrator.repositories.workflow_repository import WorkflowRepository

from .prompting import (
    PromptRenderer,
    TextChunker,
    build_chat_request,
    estimate_tokens,
    prompt_context,
)


class WorkflowPlanner:
    """Convierte una captura enriquecida en tareas Broker reanudables.

    El Broker ejecuta inferencias, pero no decide chunks, sintesis ni Obsidian.
    Esa responsabilidad se queda aqui, mi nino, para que el workflow de conocimiento
    no dependa de como el Broker planifique modelos por dentro.
    """

    def __init__(
        self,
        captures: CaptureRepository,
        domains: DomainRepository,
        workflows: WorkflowRepository,
        *,
        max_context_tokens: int = 16_000,
        safety_tokens: int = 1_000,
        renderer: PromptRenderer | None = None,
        chunker: TextChunker | None = None,
    ) -> None:
        self.captures = captures
        self.domains = domains
        self.workflows = workflows
        self.max_context_tokens = max_context_tokens
        self.safety_tokens = safety_tokens
        self.renderer = renderer or PromptRenderer()
        self.chunker = chunker or TextChunker()

    def plan_unplanned(self) -> list[str]:
        planned: list[str] = []
        for capture_id in self.workflows.list_unplanned_capture_ids():
            planned.append(self.plan_capture(capture_id))
        return planned

    def plan_capture(self, capture_id: str, *, revision: int | None = None) -> str:
        """Crea un workflow single o chunked segun el presupuesto real de contexto."""

        capture = self.captures.get(capture_id)
        if capture is None or capture.profile_id is None:
            raise ValueError("La captura no está enriquecida con un perfil")
        profile = self.domains.get_profile(capture.profile_id)
        if profile is None or not profile.enabled:
            raise ValueError("El perfil asignado no existe o está deshabilitado")
        metadata = json.loads(capture.metadata_json)
        context = prompt_context(metadata, capture.transcript_content)
        system = self.renderer.render(profile.system_prompt, context)
        user = self.renderer.render(profile.user_prompt, context)
        input_budget = self.max_context_tokens - profile.max_output_tokens - self.safety_tokens
        if input_budget < 500:
            raise ValueError("El perfil no deja espacio de contexto para la entrada")

        workflow_revision = revision or self.workflows.next_revision(capture_id)
        workflow_id = f"wf_{capture_id}_r{workflow_revision}"
        tasks: list[PlannedTask] = []
        if estimate_tokens(system + user) <= input_budget:
            strategy = "single"
            task = self._task(
                capture_id=capture_id,
                workflow_id=workflow_id,
                revision=workflow_revision,
                profile=profile,
                step_id="single",
                step_kind=StepKind.SINGLE,
                sequence_index=0,
                system=system,
                user=user,
                input_text=capture.transcript_content,
            )
            tasks.append(task)
            total_steps = 1
            chunk_count = 1
        else:
            strategy = "chunked"
            # Si no cabe, partimos localmente por limites naturales; el Broker recibe tareas opacas.
            empty_context = prompt_context(metadata, "", chunk="", chunk_index=1, chunk_count=1)
            overhead = estimate_tokens(
                self.renderer.render(profile.system_prompt, empty_context)
                + self.renderer.render(profile.chunk_prompt, empty_context)
            )
            chunk_budget = max(250, input_budget - overhead)
            chunks = self.chunker.split(capture.transcript_content, max_tokens=chunk_budget)
            chunk_count = len(chunks)
            for index, chunk in enumerate(chunks, start=1):
                chunk_context = prompt_context(
                    metadata,
                    chunk,
                    chunk=chunk,
                    chunk_index=index,
                    chunk_count=chunk_count,
                )
                tasks.append(self._task(
                    capture_id=capture_id,
                    workflow_id=workflow_id,
                    revision=workflow_revision,
                    profile=profile,
                    step_id=f"chunk_{index}",
                    step_kind=StepKind.CHUNK,
                    sequence_index=index - 1,
                    system=self.renderer.render(profile.system_prompt, chunk_context),
                    user=self.renderer.render(profile.chunk_prompt, chunk_context),
                    input_text=chunk,
                ))
            total_steps = chunk_count + 1

        self.workflows.create_workflow(
            workflow_id=workflow_id,
            capture_id=capture_id,
            revision=workflow_revision,
            profile_id=profile.profile_id or 0,
            profile_revision=profile.revision,
            strategy=strategy,
            total_steps=total_steps,
            plan={
                "strategy": strategy,
                "chunk_count": chunk_count,
                "max_context_tokens": self.max_context_tokens,
                "input_budget": input_budget,
            },
            tasks=tasks,
        )
        return workflow_id

    def advance_workflow(self, workflow_id: str) -> None:
        """Avanza workflows con resultados ya persistidos, sin esperar al Broker aqui."""

        workflow = self.workflows.get_workflow(workflow_id)
        if workflow is None or workflow.status.value in {"SUCCESS", "ERROR", "CANCELLED"}:
            return
        tasks = self.workflows.list_workflow_tasks(workflow_id)
        if workflow.strategy == "single":
            singles = [task for task in tasks if task.step_kind is StepKind.SINGLE]
            successful = next((task for task in singles if task.status is TaskStatus.SUCCESS), None)
            if successful:
                self.workflows.finish_workflow(workflow_id, self._assistant_content(successful.result_json))
                return
            self._create_single_fallback_if_needed(singles)
            return

        syntheses = [task for task in tasks if task.step_kind is StepKind.SYNTHESIS]
        successful = next((task for task in syntheses if task.status is TaskStatus.SUCCESS), None)
        if successful:
            self.workflows.finish_workflow(workflow_id, self._assistant_content(successful.result_json))
            return
        if syntheses:
            chunks = [task for task in tasks if task.step_kind is StepKind.CHUNK]
            self._create_fallback_if_needed(syntheses, [task.task_id for task in chunks])
            return
        chunks = [task for task in tasks if task.step_kind is StepKind.CHUNK]
        if not chunks or any(task.status is not TaskStatus.SUCCESS for task in chunks):
            return
        capture = self.captures.get(workflow.capture_id)
        profile = self.domains.get_profile(workflow.profile_id)
        if capture is None or profile is None:
            raise RuntimeError("No se puede construir la síntesis sin captura y perfil")
        metadata = json.loads(capture.metadata_json)
        partial_results = "\n\n---\n\n".join(self._assistant_content(task.result_json) for task in chunks)
        context = prompt_context(
            metadata,
            capture.transcript_content,
            partial_results=partial_results,
            chunk_count=len(chunks),
        )
        system = self.renderer.render(profile.system_prompt, context)
        user = self.renderer.render(profile.synthesis_prompt, context)
        task = self._task(
            capture_id=capture.capture_id,
            workflow_id=workflow_id,
            revision=workflow.revision,
            profile=profile,
            step_id="synthesis",
            step_kind=StepKind.SYNTHESIS,
            sequence_index=len(chunks),
            system=system,
            user=user,
            input_text=partial_results,
        )
        self.workflows.insert_synthesis_task(task, [item.task_id for item in chunks])

    def _create_single_fallback_if_needed(self, tasks: list) -> None:
        self._create_fallback_if_needed(tasks, [])

    def _create_fallback_if_needed(self, tasks: list, dependency_ids: list[str]) -> None:
        # El fallback a single no es un comodin: solo se crea para errores de consenso
        # ya tipados y con permiso del perfil.
        originals = [
            task for task in tasks
            if task.status is TaskStatus.ERROR
            and task.execution_strategy == "mixture_of_agents"
            and task.strategy_fallback_allowed
        ]
        for original in originals:
            if any(task.replacement_for_task_id == original.task_id for task in tasks):
                continue
            request = json.loads(original.request_json)
            fallback_task_id = f"{original.task_id}_fallback"
            fallback_step_id = f"{original.step_id}_fallback"
            request["request_id"] = fallback_task_id
            request["idempotency_key"] = f"{original.idempotency_key}:fallback"
            request["content"]["metadata"]["step_id"] = fallback_step_id
            request["execution"].update({
                "strategy": "single",
                "preset": "fast",
                "max_proposers": 1,
                "max_judges": 0,
                "max_rounds": 1,
            })
            request["execution"]["selection"]["proposer_count"] = 1
            # Frontera Orchestrator -> Broker: antes de persistir, el payload tiene que cumplir v2.
            validate_create_task_request(request)
            fallback = PlannedTask(
                task_id=fallback_task_id,
                workflow_id=original.workflow_id,
                capture_id=original.capture_id,
                step_id=fallback_step_id,
                step_kind=original.step_kind,
                sequence_index=original.sequence_index + 1,
                idempotency_key=request["idempotency_key"],
                request=request,
                input_text=original.input_text,
                strategy_fallback_allowed=False,
                replacement_for_task_id=original.task_id,
            )
            self.workflows.insert_synthesis_task(fallback, dependency_ids)
            return

    def _task(
        self,
        *,
        capture_id: str,
        workflow_id: str,
        revision: int,
        profile,
        step_id: str,
        step_kind: StepKind,
        sequence_index: int,
        system: str,
        user: str,
        input_text: str,
    ) -> PlannedTask:
        task_id = f"proc_{capture_id}_r{revision}_{step_id}"
        request = build_chat_request(
            task_id=task_id,
            idempotency_key=f"{capture_id}:{revision}:{step_id}",
            workflow_id=workflow_id,
            step_id=step_id,
            profile=profile,
            system_content=system,
            user_content=user,
            execution_step=step_kind.value.lower(),
        )
        # Frontera Orchestrator -> Broker: no se guarda una tarea que el Broker no pueda aceptar.
        validate_create_task_request(request)
        return PlannedTask(
            task_id=task_id,
            workflow_id=workflow_id,
            capture_id=capture_id,
            step_id=step_id,
            step_kind=step_kind,
            sequence_index=sequence_index,
            idempotency_key=request["idempotency_key"],
            request=request,
            input_text=input_text,
            strategy_fallback_allowed=(
                request["execution"]["strategy"] == "mixture_of_agents"
                and profile.consensus_fallback_to_single
            ),
        )

    @staticmethod
    def _assistant_content(result_json: str | None) -> str:
        if not result_json:
            raise ValueError("Falta result_json")
        result = json.loads(result_json)
        content = result.get("assistant_content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Falta assistant_content válido")
        return content
