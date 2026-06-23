from __future__ import annotations

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
        updated = ProfileDefinition(
            profile_id=current.profile_id,
            name=current.name,
            system_prompt=current.system_prompt,
            user_prompt=current.user_prompt,
            chunk_prompt=current.chunk_prompt,
            synthesis_prompt=current.synthesis_prompt,
            preferred_model=current.preferred_model,
            fallback_allowed=current.fallback_allowed,
            temperature=current.temperature,
            max_output_tokens=current.max_output_tokens,
            enabled=enabled,
            revision=current.revision,
        )
        return self.save_profile(updated)
