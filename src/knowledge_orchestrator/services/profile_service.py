from __future__ import annotations

from dataclasses import replace

from knowledge_orchestrator.domain.models import ProfileDefinition
from knowledge_orchestrator.domain.profiles import validate_profile
from knowledge_orchestrator.repositories.domain_repository import DomainRepository


class ProfileService:
    def __init__(self, repository: DomainRepository) -> None:
        self.repository = repository

    def list_profiles(self, *, enabled_only: bool = False) -> list[ProfileDefinition]:
        return self.repository.list_profiles(enabled_only=enabled_only)

    def get_profile(self, profile_id: int) -> ProfileDefinition:
        profile = self.repository.get_profile(profile_id)
        if profile is None:
            raise ValueError(f"Perfil inexistente: {profile_id}")
        return profile

    def save_profile(self, profile: ProfileDefinition) -> ProfileDefinition:
        validated = validate_profile(profile)
        if (
            validated.profile_id is not None
            and not validated.enabled
            and self.repository.enabled_topic_usage_count(validated.profile_id) > 0
        ):
            raise ValueError("No se puede deshabilitar un perfil usado por temas activos")
        return self.repository.save_profile(validated)

    def set_enabled(self, profile_id: int, enabled: bool) -> ProfileDefinition:
        current = self.get_profile(profile_id)
        updated = replace(current, enabled=enabled)
        return self.save_profile(updated)
