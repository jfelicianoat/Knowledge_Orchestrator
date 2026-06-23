from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from knowledge_orchestrator.domain.models import ProfileDefinition
from knowledge_orchestrator.domain.profiles import ProfileValidationError, validate_profile
from knowledge_orchestrator.repositories.database import Database
from knowledge_orchestrator.repositories.domain_repository import DomainRepository
from knowledge_orchestrator.services.profile_service import ProfileService


def profile_definition(**overrides) -> ProfileDefinition:
    values = {
        "name": "Resumen técnico",
        "system_prompt": "Analiza únicamente la fuente proporcionada.",
        "user_prompt": "Título: {title}\n\n{transcript}",
        "chunk_prompt": "Fragmento {chunk_index}/{chunk_count}:\n{chunk}",
        "synthesis_prompt": "Combina sin inventar:\n{partial_results}",
        "preferred_model": "llama3.1:8b",
    }
    values.update(overrides)
    return ProfileDefinition(**values)


class ProfileServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        database = Database(Path(self.temporary.name) / "orchestrator.db")
        database.initialize()
        self.repository = DomainRepository(database)
        self.service = ProfileService(self.repository)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_creates_and_edits_profile_with_optimistic_revision(self) -> None:
        created = self.service.save_profile(profile_definition())
        self.assertEqual(created.revision, 1)
        updated = self.service.save_profile(profile_definition(
            profile_id=created.profile_id,
            revision=created.revision,
            temperature=0.7,
        ))
        self.assertEqual(updated.revision, 2)
        self.assertEqual(updated.temperature, 0.7)
        with self.assertRaisesRegex(RuntimeError, "modificado por otra"):
            self.service.save_profile(profile_definition(
                profile_id=created.profile_id,
                revision=1,
            ))

    def test_rejects_unknown_and_missing_placeholders(self) -> None:
        with self.assertRaises(ProfileValidationError):
            self.service.save_profile(profile_definition(user_prompt="{transcript} {internet_search}"))
        with self.assertRaises(ProfileValidationError):
            self.service.save_profile(profile_definition(chunk_prompt="Sin contenido"))
        with self.assertRaisesRegex(ProfileValidationError, "placeholders simples"):
            self.service.save_profile(profile_definition(user_prompt="{transcript.__class__}"))

    def test_cannot_disable_profile_used_by_inbox(self) -> None:
        default_profile = self.service.list_profiles(enabled_only=True)[0]
        self.assertIs(validate_profile(default_profile), default_profile)
        with self.assertRaisesRegex(ValueError, "usado por temas activos"):
            self.service.set_enabled(default_profile.profile_id or 0, False)

    def test_persists_and_validates_multitasking_policy(self) -> None:
        created = self.service.save_profile(profile_definition(
            execution_strategy="mixture_of_agents",
            multitasking_steps=("synthesis", "single"),
            consensus_max_proposers=3,
            consensus_fallback_to_single=True,
        ))
        self.assertEqual(created.execution_strategy, "mixture_of_agents")
        self.assertEqual(created.multitasking_steps, ("synthesis", "single"))
        with self.assertRaises(ProfileValidationError):
            self.service.save_profile(replace(
                created,
                data_classification="local_only",
                cloud_allowed=True,
                allowed_providers=("deepseek",),
            ))


if __name__ == "__main__":
    unittest.main()
