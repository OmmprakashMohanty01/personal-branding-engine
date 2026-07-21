"""
prompts.py
==========
PromptFactory — backward-compatible interface that delegates to the
modular PromptBuilder pipeline.

Existing callers (orchestrator, tests) continue using the same
render_system_prompt() and render_user_prompt() signatures.
"""

from typing import Any, Optional

from jinja2 import Template
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.generation.prompt_builder import PromptBuilder


class PromptFactory:
    """Backward-compatible prompt factory that delegates to PromptBuilder.

    Preserves the original API surface so existing orchestrator and test code
    continue working without modification.
    """

    def __init__(self):
        self._builder = PromptBuilder()

    @property
    def COHERE_SYSTEM_TEMPLATE(self) -> str:
        """Return the Stage 2 Cohere refinement prompt."""
        return self._builder.build_cohere_prompt()

    async def render_system_prompt(
        self,
        persona: Any,
        db: Optional[AsyncSession] = None,
        topic: str = "",
    ) -> str:
        """Render the full modular system prompt.

        Args:
            persona: Persona model instance.
            db: Database session for memory retrieval.
            topic: Post topic for author context filtering.

        Returns:
            The complete assembled system prompt.
        """
        return await self._builder.build_system_prompt(persona, topic, db)

    def render_user_prompt(self, topic: str, feedback: Optional[str] = None) -> str:
        """Render the user prompt with topic and optional feedback.

        Args:
            topic: The post topic.
            feedback: Optional adjustment feedback.

        Returns:
            The rendered user prompt string.
        """
        return self._builder.build_user_prompt(topic, feedback)

    def get_generation_metadata(self) -> dict:
        """Retrieve metadata from the last prompt build.

        Returns:
            Dict with hook, ending, project, and memory metadata.
        """
        return self._builder.get_generation_metadata()
