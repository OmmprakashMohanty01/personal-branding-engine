"""
prompt_builder.py
=================
PromptBuilder — orchestrates the modular prompt pipeline assembly.

Pipeline:
    SYSTEM → PERSONA → AUTHOR CONTEXT → CONTENT STRATEGY →
    WRITING DNA → MEMORY → IMAGE RULES → SELF-CHECK → OUTPUT CONTRACT

Each section is rendered independently via Jinja2 and concatenated.
"""

import logging
from typing import Any, Optional

from jinja2 import Template
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.generation.prompt_templates import (
    SYSTEM_TEMPLATE,
    PERSONA_TEMPLATE,
    AUTHOR_CONTEXT_TEMPLATE,
    CONTENT_STRATEGY_TEMPLATE,
    WRITING_DNA_TEMPLATE,
    MEMORY_TEMPLATE,
    SELF_CHECK_TEMPLATE,
    OUTPUT_SCHEMA_TEMPLATE,
    COHERE_REFINEMENT_TEMPLATE,
    USER_TEMPLATE,
    CLAIM_CATEGORIES_TEMPLATE,
    GITHUB_LINK_RULES_TEMPLATE,
    GROUNDING_CONTRACT_TEMPLATE,
)
from app.services.generation.writing_dna import WritingDNA, WritingDNAEngine, ContentStrategy
from app.services.generation.author_knowledge import AuthorKnowledgeService, AuthorContext
from app.services.generation.prompt_memory import PromptMemoryService, MemoryContext
from app.services.generation.image_rules import ImageRulesEngine

logger = logging.getLogger("branding_engine.generation.prompt_builder")

SECTION_SEPARATOR = "\n\n---\n\n"


class PromptBuilder:
    """Orchestrates the full prompt pipeline assembly from modular components.

    Usage:
        builder = PromptBuilder()
        system_prompt = await builder.build_system_prompt(persona, topic, db)
        user_prompt = builder.build_user_prompt(topic, feedback)
        cohere_prompt = builder.build_cohere_prompt()
        metadata = builder.get_generation_metadata()
    """

    def __init__(self):
        self.writing_dna_engine = WritingDNAEngine()
        self.author_knowledge = AuthorKnowledgeService()
        self.memory_service = PromptMemoryService()
        self.image_rules_engine = ImageRulesEngine()

        # State from the last build — for logging and metadata
        self._last_writing_dna: Optional[WritingDNA] = None
        self._last_content_strategy: Optional[ContentStrategy] = None
        self._last_author_context: Optional[AuthorContext] = None
        self._last_memory_context: Optional[MemoryContext] = None

    async def build_system_prompt(
        self,
        persona: Any,
        topic: str,
        db: Optional[AsyncSession] = None,
    ) -> str:
        """Assemble the full system prompt from all pipeline sections.

        Args:
            persona: Persona model instance with name, tone, vocabulary, formatting.
            topic: The post topic (used for author context filtering).
            db: Database session for memory retrieval (optional).

        Returns:
            The complete system prompt string.
        """
        # 1. Load memory context
        memory_context = await self.memory_service.get_recent_context(db)
        self._last_memory_context = memory_context

        # 2. Generate writing DNA (avoiding recent patterns)
        writing_dna = self.writing_dna_engine.generate(
            recent_hooks=memory_context.recent_hooks if not memory_context.is_empty else None,
            recent_endings=memory_context.recent_endings if not memory_context.is_empty else None,
        )
        self._last_writing_dna = writing_dna

        # 3. Generate content strategy
        content_strategy = self.writing_dna_engine.generate_strategy()
        self._last_content_strategy = content_strategy

        # 4. Get relevant author context
        author_context = self.author_knowledge.get_relevant_context(topic)
        self._last_author_context = author_context

        # 5. Render each section
        sections = []

        # SYSTEM identity
        sections.append(SYSTEM_TEMPLATE)

        # PERSONA
        persona_rendered = Template(PERSONA_TEMPLATE).render(persona=persona)
        sections.append(persona_rendered)

        # AUTHOR CONTEXT
        author_rendered = Template(AUTHOR_CONTEXT_TEMPLATE).render(
            projects=author_context.projects,
            technologies=author_context.technologies,
            background=author_context.background,
            links=author_context.links,
            current_context=author_context.current_context,
        )
        sections.append(author_rendered)

        # CONTENT STRATEGY
        strategy_rendered = Template(CONTENT_STRATEGY_TEMPLATE).render(
            strategy=content_strategy,
        )
        sections.append(strategy_rendered)

        # WRITING DNA
        dna_rendered = Template(WRITING_DNA_TEMPLATE).render(writing_dna=writing_dna)
        sections.append(dna_rendered)

        # MEMORY (only if non-empty)
        if not memory_context.is_empty:
            memory_rendered = Template(MEMORY_TEMPLATE).render(memory=memory_context)
            sections.append(memory_rendered)
            
        # CLAIM CATEGORIES
        sections.append(CLAIM_CATEGORIES_TEMPLATE)
        
        # GITHUB LINK RULES
        sections.append(GITHUB_LINK_RULES_TEMPLATE)
        
        # GROUNDING CONTRACT
        sections.append(GROUNDING_CONTRACT_TEMPLATE)

        # IMAGE RULES removed: image prompts are now deterministic (P5).
        # The LLM no longer generates image prompts.

        # SELF-CHECK
        sections.append(SELF_CHECK_TEMPLATE)

        # OUTPUT CONTRACT
        sections.append(OUTPUT_SCHEMA_TEMPLATE)

        full_prompt = SECTION_SEPARATOR.join(sections)

        logger.info(
            "[PROMPT BUILDER] System prompt assembled",
            extra={
                "sections_count": len(sections),
                "total_length": len(full_prompt),
                "hook_strategy": writing_dna.hook_strategy,
                "ending_strategy": writing_dna.ending_strategy,
                "goal": content_strategy.goal,
                "audience": content_strategy.audience,
                "emotional_intent": content_strategy.emotional_intent,
                "injected_projects": [p.name for p in author_context.projects],
                "memory_items": not memory_context.is_empty,
            },
        )

        return full_prompt

    def build_user_prompt(
        self,
        topic: str,
        feedback: Optional[str] = None,
    ) -> str:
        """Render the user prompt with topic and optional feedback."""
        return Template(USER_TEMPLATE).render(topic=topic, feedback=feedback)

    def build_cohere_prompt(self) -> str:
        """Return the Stage 2 Cohere refinement system prompt.
        
        .. deprecated::
            Stage 2 Cohere rewriting has been removed from the pipeline.
            Cohere is now only used as a Stage 1 fallback generator.
            This method is kept for backward compatibility.
        """
        return COHERE_REFINEMENT_TEMPLATE

    def get_generation_metadata(self) -> dict:
        """Return metadata about the last prompt assembly for logging."""
        metadata = {}
        if self._last_writing_dna:
            metadata.update(self._last_writing_dna.to_dict())
        if self._last_content_strategy:
            metadata.update(self._last_content_strategy.to_dict())
        if self._last_author_context:
            metadata["injected_projects"] = [p.name for p in self._last_author_context.projects]
            metadata["injected_technologies"] = self._last_author_context.technologies
        if self._last_memory_context:
            metadata["memory_loaded"] = not self._last_memory_context.is_empty
        return metadata
