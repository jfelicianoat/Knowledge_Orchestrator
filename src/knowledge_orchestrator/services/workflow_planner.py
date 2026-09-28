from __future__ import annotations

import json
from contextlib import closing
from dataclasses import replace
from typing import Any

from knowledge_orchestrator.domain.broker_contracts import validate_create_task_request
from knowledge_orchestrator.domain.broker_models import PlannedTask, StepKind, TaskStatus
from knowledge_orchestrator.domain.models import ProfileDefinition
from knowledge_orchestrator.repositories.capture_repository import CaptureRepository
from knowledge_orchestrator.repositories.domain_repository import DomainRepository
from knowledge_orchestrator.repositories.workflow_repository import WorkflowRepository
from knowledge_orchestrator.repositories.workflow_repository.base import fallback_eligible

from .prompting import (
    PromptRenderer,
    TextChunker,
    build_chat_request,
    estimate_tokens,
    prompt_context,
)

#: Paso final de la síntesis y prefijo de las reducciones intermedias.
FINAL_SYNTHESIS_STEP = "synthesis"
REDUCTION_PREFIX = "reduce_"
#: En la síntesis la transcripción ya no cabe (por eso se troceó): si una
#: plantilla personalizada la pide, recibe este aviso en vez de todo el texto.
TRANSCRIPT_OMITTED = (
    "[La transcripción completa no cabe en la ventana del modelo; "
    "trabaja solo con los resultados parciales.]"
)
TRUNCATION_MARK = "\n\n[… resultado parcial recortado para caber en la ventana del modelo]"


def _fallback_base(step_id: str) -> str:
    return step_id.removesuffix("_fallback")


def split_budget(total: float | None, parts: int) -> float | None:
    """Reparte el presupuesto del documento sin superar nunca el total."""

    if total is None:
        return None
    if parts <= 0:
        return 0.0
    # Se redondea hacia abajo: la suma de las partes nunca excede el total.
    return int(total * 1_000_000 / parts) / 1_000_000


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
            try:
                planned.append(self.plan_capture(capture_id))
            except (ValueError, RuntimeError) as error:
                # Un documento que no se puede planificar (perfil desactivado,
                # plantilla rota) pide atención; los demás siguen su curso.
                self.workflows.fail_unplannable_capture(capture_id, "PLANNING_FAILED", str(error))
        return planned

    def plan_capture(self, capture_id: str, *, revision: int | None = None) -> str:
        """Crea un workflow single o chunked segun el presupuesto real de contexto."""

        capture = self.captures.get(capture_id)
        if capture is None or capture.profile_id is None:
            raise ValueError("La captura no está enriquecida con un perfil")
        base_profile = self.domains.get_profile(capture.profile_id)
        if base_profile is None or not base_profile.enabled:
            raise ValueError("El perfil asignado no existe o está deshabilitado")
        window = self.context_window_for(base_profile)
        profile = self.effective_profile(base_profile, window=window)
        metadata = json.loads(capture.metadata_json)
        context = prompt_context(metadata, capture.transcript_content)
        system = self.renderer.render(profile.system_prompt, context)
        user = self.renderer.render(profile.user_prompt, context)
        input_budget = window - profile.max_output_tokens - self.safety_tokens
        if input_budget < 500:
            raise ValueError("El perfil no deja espacio de contexto para la entrada")
        # El presupuesto es del documento, no de cada petición (auditoría H08):
        # los fragmentos se reparten la bolsa y la última parte queda para la
        # síntesis. Lo que se envía de verdad lo vigila la reserva del workflow.
        document_budget = float(base_profile.max_cost_usd)

        workflow_revision = revision or self.workflows.next_revision(capture_id)
        workflow_id = f"wf_{capture_id}_r{workflow_revision}"
        tasks: list[PlannedTask] = []
        # El map_reduce 2.8 del Broker solo trocea documentos ingeridos y
        # referenciados como broker_file. Knowledge Orchestrator envía ahora la
        # captura como texto inline, por lo que debe conservar su chunking local.
        # Delegarlo aquí produciría CONTEXT_LIMIT_EXCEEDED en documentos grandes.
        if estimate_tokens(system + user) <= input_budget:
            strategy = "single"
            profile = replace(profile, max_cost_usd=document_budget)
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
            profile = replace(profile, max_cost_usd=split_budget(document_budget, chunk_count + 1) or 0.0)
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
                "max_context_tokens": window,
                "input_budget": input_budget,
                "output_tokens": profile.max_output_tokens,
                "long_context": profile.long_context,
                "long_context_execution": "local_chunks" if strategy == "chunked" else "not_needed",
                "human_review_required": base_profile.human_review_required,
                "budget_usd": document_budget,
            },
            tasks=tasks,
            # La política de revisión se congela aquí: cambiar el perfil después
            # no publica ni retiene documentos ya planificados.
            review_required=base_profile.human_review_required,
            budget_usd=document_budget,
        )
        return workflow_id

    def context_window_for(self, profile: ProfileDefinition) -> int:
        """Ventana utilizable: la configurada, o menos si el modelo elegido declara menos.

        La ventana era un número fijo aunque el catálogo del Broker dice cuánto
        admite cada modelo (auditoría H06). Nunca se amplía por encima de lo
        configurado: el catálogo puede declarar ventanas que la máquina no sirve.
        """

        window = self.max_context_tokens
        if not profile.preferred_model:
            return window
        try:
            with closing(self.workflows.database.connect(readonly=True)) as connection:
                row = connection.execute(
                    "SELECT context_window FROM model_catalog WHERE name = ? ORDER BY context_window LIMIT 1",
                    (profile.preferred_model,),
                ).fetchone()
        except Exception:  # un catálogo ilegible no impide planificar
            return window
        declared = int(row["context_window"]) if row and row["context_window"] else 0
        return min(window, declared) if declared >= 2_000 else window

    def effective_profile(self, profile: ProfileDefinition, *, window: int | None = None) -> ProfileDefinition:
        """El perfil con la salida acotada a la ventana: el mismo para trocear y para sintetizar.

        Nunca reservamos más de la mitad de la ventana para la salida: un perfil
        detallado debe seguir funcionando con modelos de contexto más pequeño y
        trocear la entrada en vez de quedarse sin presupuesto. Antes la síntesis
        releía el perfil original y pedía 8000 tokens de salida con una ventana
        de 4000.
        """

        usable = window if window is not None else self.context_window_for(profile)
        effective_output_tokens = min(
            profile.max_output_tokens,
            max(1_000, (usable - self.safety_tokens) // 2),
        )
        return replace(profile, max_output_tokens=effective_output_tokens)

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
        final = [task for task in syntheses if _fallback_base(task.step_id) == FINAL_SYNTHESIS_STEP]
        successful = next((task for task in final if task.status is TaskStatus.SUCCESS), None)
        if successful:
            self.workflows.finish_workflow(workflow_id, self._assistant_content(successful.result_json))
            return
        chunks = [task for task in tasks if task.step_kind is StepKind.CHUNK]
        if final:
            self._create_fallback_if_needed(final, [task.task_id for task in chunks])
            return
        if not chunks or any(task.status is not TaskStatus.SUCCESS for task in chunks):
            return
        # Reducción jerárquica (auditoría H06): los resultados parciales se
        # funden por niveles hasta que el conjunto cabe en una sola síntesis.
        results = [self._assistant_content(task.result_json) for task in chunks]
        dependency_ids = [task.task_id for task in chunks]
        level = 1
        while True:
            level_tasks = [task for task in syntheses if task.step_id.startswith(f"{REDUCTION_PREFIX}{level}_")]
            if not level_tasks:
                break
            groups: dict[str, list[Any]] = {}
            for task in level_tasks:
                groups.setdefault(_fallback_base(task.step_id), []).append(task)
            winners = []
            for step_id in sorted(groups, key=lambda value: int(value.rsplit("_", 1)[1])):
                done = next((task for task in groups[step_id] if task.status is TaskStatus.SUCCESS), None)
                if done is None:
                    self._create_fallback_if_needed(groups[step_id], [])
                    return
                winners.append(done)
            results = [self._assistant_content(task.result_json) for task in winners]
            dependency_ids = [task.task_id for task in winners]
            level += 1
        self._plan_synthesis_stage(workflow, tasks, results, dependency_ids, level=level)

    def _plan_synthesis_stage(
        self,
        workflow: Any,
        tasks: list[Any],
        results: list[str],
        dependency_ids: list[str],
        *,
        level: int,
    ) -> None:
        """Crea la síntesis final si cabe; si no, un nivel más de reducción."""

        capture = self.captures.get(workflow.capture_id)
        base_profile = self.domains.get_profile(workflow.profile_id)
        if capture is None or base_profile is None:
            raise RuntimeError("No se puede construir la síntesis sin captura y perfil")
        window = self.context_window_for(base_profile)
        profile = self.effective_profile(base_profile, window=window)
        metadata = json.loads(capture.metadata_json)
        input_budget = window - profile.max_output_tokens - self.safety_tokens

        def render(partials: list[str], index: int, count: int) -> tuple[str, str, str]:
            joined = "\n\n---\n\n".join(partials)
            context = prompt_context(
                metadata, TRANSCRIPT_OMITTED, partial_results=joined,
                chunk_index=index, chunk_count=count,
            )
            return (
                self.renderer.render(profile.system_prompt, context),
                self.renderer.render(profile.synthesis_prompt, context),
                joined,
            )

        overhead = sum(estimate_tokens(part) for part in render([""], 1, 1)[:2])
        room = input_budget - overhead
        if room < 250:
            raise ValueError("La plantilla de síntesis no deja espacio para los resultados parciales")
        remaining_budget = self._remaining_budget(workflow.workflow_id)
        sequence = max((task.sequence_index for task in tasks), default=0) + 1
        system, user, joined = render(results, 1, len(results))
        if estimate_tokens(system + user) <= input_budget or len(results) == 1:
            if len(results) == 1 and estimate_tokens(system + user) > input_budget:
                results = [self._fit(results[0], room)]
                system, user, joined = render(results, 1, 1)
            final_profile = replace(profile, max_cost_usd=remaining_budget if remaining_budget is not None
                                    else profile.max_cost_usd)
            self.workflows.insert_synthesis_task(self._task(
                capture_id=capture.capture_id, workflow_id=workflow.workflow_id, revision=workflow.revision,
                profile=final_profile, step_id=FINAL_SYNTHESIS_STEP, step_kind=StepKind.SYNTHESIS,
                sequence_index=sequence, system=system, user=user, input_text=joined,
            ), dependency_ids)
            return

        groups = self._pack(results, room)
        # Cada nivel reparte lo que queda entre sus reducciones y las que aún
        # vendrán (se estiman dividiendo por dos hasta llegar a la final).
        pending, size = 0, len(groups)
        while size > 1:
            pending += size
            size = (size + 1) // 2
        share = split_budget(remaining_budget, pending + 1)
        reduction_profile = replace(profile, max_cost_usd=share if share is not None else profile.max_cost_usd)
        for index, group in enumerate(groups, start=1):
            system, user, joined = render(group, index, len(groups))
            self.workflows.insert_synthesis_task(self._task(
                capture_id=capture.capture_id, workflow_id=workflow.workflow_id, revision=workflow.revision,
                profile=reduction_profile, step_id=f"{REDUCTION_PREFIX}{level}_{index}",
                step_kind=StepKind.SYNTHESIS, sequence_index=sequence + index - 1,
                system=system, user=user, input_text=joined,
            ), dependency_ids)
        self.workflows.record_workflow_event(
            workflow.workflow_id, "SYNTHESIS_REDUCTION_PLANNED",
            f"Los {len(results)} resultados parciales no caben en una síntesis; "
            f"se funden primero en {len(groups)} grupos (nivel {level}).",
            {"level": level, "inputs": len(results), "groups": len(groups)},
        )

    def _remaining_budget(self, workflow_id: str) -> float | None:
        with closing(self.workflows.database.connect(readonly=True)) as connection:
            row = connection.execute(
                "SELECT budget_usd, budget_reserved_usd FROM workflows WHERE workflow_id = ?", (workflow_id,)
            ).fetchone()
        if row is None or row["budget_usd"] is None:
            return None
        return max(0.0, float(row["budget_usd"]) - float(row["budget_reserved_usd"] or 0.0))

    @staticmethod
    def _fit(text: str, max_tokens: int) -> str:
        """Recorta un parcial que por sí solo no cabe; queda marcado, nunca en silencio."""

        if estimate_tokens(text) <= max_tokens:
            return text
        keep = max(0, max_tokens * 4 - len(TRUNCATION_MARK))
        return text[:keep].rstrip() + TRUNCATION_MARK

    @classmethod
    def _pack(cls, results: list[str], room: int) -> list[list[str]]:
        """Agrupa parciales consecutivos sin pasar de `room` tokens por grupo.

        Cada parcial se limita a media ventana para que en un grupo quepan al
        menos dos: así cada nivel reduce el número de piezas y la reducción
        siempre termina.
        """

        separator = estimate_tokens("\n\n---\n\n")
        fitted = [cls._fit(result, max(1, room // 2 - separator)) for result in results]
        groups: list[list[str]] = []
        current: list[str] = []
        used = 0
        for result in fitted:
            size = estimate_tokens(result) + separator
            if current and used + size > room:
                groups.append(current)
                current, used = [], 0
            current.append(result)
            used += size
        if current:
            groups.append(current)
        if len(groups) >= len(results) and len(results) > 1:
            groups = [fitted[index:index + 2] for index in range(0, len(fitted), 2)]
        return groups

    def _create_single_fallback_if_needed(self, tasks: list) -> None:
        self._create_fallback_if_needed(tasks, [])

    def _create_fallback_if_needed(self, tasks: list, dependency_ids: list[str]) -> None:
        # El fallback a single no es un comodin: solo se crea para errores de consenso
        # ya tipados y con permiso del perfil. Incluye "auto" (contrato v2.5): el
        # meta-router del Broker pudo resolver a mixture y fallar por lo mismo.
        originals = [
            task for task in tasks
            if task.status is TaskStatus.ERROR
            and fallback_eligible(task.execution_strategy, task.strategy_fallback_allowed, task.error_code)
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
                request["execution"]["strategy"] in {"mixture_of_agents", "auto"}
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
