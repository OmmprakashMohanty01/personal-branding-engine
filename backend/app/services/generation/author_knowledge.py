"""
author_knowledge.py
===================
AuthorKnowledgeService — provides factual, verifiable information
about Ommprakash Mohanty for prompt injection.

No personality adjectives. Pure facts only.
Topic-aware filtering ensures only relevant projects are injected.

Includes dynamic context fields (current_project, recent_learning, etc.)
that can be sourced from a database in the future.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("branding_engine.generation.author_knowledge")

GITHUB_URL = "https://github.com/OmmprakashMohanty01"

AUTHOR_LINKS: Dict[str, str] = {
    "GitHub": GITHUB_URL,
}

AUTHOR_BACKGROUND = (
    "B.Tech in Computer Science. Full-stack engineer and AI systems builder. "
    "Runs Zero One: Codebreak (investigative tech content channel) "
    "and @op_x_visuals (digital media and visual storytelling)."
)


@dataclass
class Project:
    """A real project with verifiable details."""

    name: str
    description: str
    tags: List[str] = field(default_factory=list)


@dataclass
class DynamicContext:
    """Dynamic author context — eventually sourced from a database.

    TODO: Back these fields with a database table or admin API
    so the engine evolves with the author's actual work.
    """

    current_project: str = "Personal Branding Engine — autonomous AI content pipeline"
    recent_learning: Optional[str] = None
    current_problem: Optional[str] = None
    recent_success: Optional[str] = None


# ---------------------------------------------------------------------------
# Canonical project registry — extend as portfolio grows
# ---------------------------------------------------------------------------
PROJECT_REGISTRY: List[Project] = [
    Project(
        name="ai-customer-ops-hub",
        description="AI-powered customer support automation: LLM agents + event-driven HITL workflows + Lemma SDK",
        tags=["agents", "ai", "automation", "customer-support", "workflow"],
    ),
    Project(
        name="Business-RAG-Q-A-Bot",
        description="Retrieval-Augmented Generation system for business document Q&A using vector databases and LLM inference.",
        tags=["python", "rag", "llm", "langchain"],
    ),
    Project(
        name="cinematic-prompt-engine",
        description="Prompt engineering engine for generative AI models and LLMs.",
        tags=["ai", "generative-ai", "llm", "prompt-engineering", "python"],
    ),
    Project(
        name="f1-telemetry-dashboard",
        description="Telemetry dashboard for Formula 1 data using FastF1.",
        tags=["dashboard", "fastf1", "formula1", "python", "telemetry"],
    ),
    Project(
        name="gun101-gkp",
        description="A passwordless, asymmetric file encryption library. Recipients share a public Identity Token; only their RSA-4096 private key can decrypt files sent to them. No shared secrets required.",
        tags=["encryption", "security", "cryptography"],
    ),
    Project(
        name="JudgeGauge",
        description="Fail-closed calibration gates for LLM-as-judge pipelines",
        tags=["ai", "llm", "evaluation"],
    ),
    Project(
        name="mcp-context-forge",
        description="An AI Gateway, registry, and proxy that sits in front of any MCP, A2A, or REST/gRPC APIs, exposing a unified endpoint with centralized discovery, guardrails and management.",
        tags=["ai", "gateway", "mcp", "agents"],
    ),
    Project(
        name="Olist-Ecommerce-Sales-Analysis",
        description="End-to-end data engineering pipeline: PostgreSQL + SQL analytics + Tableau dashboard on the Olist Brazilian E-Commerce dataset",
        tags=["analytics", "data-engineering", "ecommerce", "postgresql", "sql", "tableau"],
    ),
    Project(
        name="personal-branding-engine",
        description="Autonomous LinkedIn content engine: FastAPI + Gemini AI + React dashboard + GitHub Actions scheduling",
        tags=["ai", "automation", "fastapi", "gemini", "linkedin", "python"],
    ),
]

# ---------------------------------------------------------------------------
# Technology registry
# ---------------------------------------------------------------------------
ALL_TECHNOLOGIES: List[str] = [
    "Python", "FastAPI", "PostgreSQL", "Docker", "Render",
    "Gemini", "Cohere", "Pollinations AI", "GitHub Actions",
    "SQLAlchemy", "Alembic", "Pydantic", "Tableau", "SQL",
    "LangChain", "RAG", "Linux", "Git", "Vercel", "MCP",
]


@dataclass
class AuthorContext:
    """Factual author context for a single generation."""

    projects: List[Project]
    technologies: List[str]
    background: str = AUTHOR_BACKGROUND
    links: Dict[str, str] = field(default_factory=lambda: dict(AUTHOR_LINKS))
    current_context: Optional[DynamicContext] = None

    def to_dict(self) -> dict:
        return {
            "projects": [p.name for p in self.projects],
            "technologies": self.technologies,
            "background": self.background,
            "links": self.links,
            "has_dynamic_context": self.current_context is not None,
        }


class AuthorKnowledgeService:
    """Returns factual author context filtered by topic relevance."""

    def __init__(self):
        self._dynamic_context = DynamicContext()

    def get_relevant_context(
        self,
        topic: str,
        max_projects: int = 3,
    ) -> AuthorContext:
        """Retrieve author facts relevant to the given topic.

        Args:
            topic: The post topic string.
            max_projects: Maximum number of projects to inject.

        Returns:
            An AuthorContext with topic-filtered projects and technologies.
        """
        topic_lower = topic.lower()

        # Score each project by tag overlap with the topic
        scored = []
        for project in PROJECT_REGISTRY:
            score = sum(1 for tag in project.tags if tag in topic_lower)
            name_words = project.name.lower().split()
            score += sum(1 for word in name_words if len(word) > 3 and word in topic_lower)
            scored.append((score, project))

        scored.sort(key=lambda x: x[0], reverse=True)
        relevant_projects = [p for score, p in scored[:max_projects] if score > 0]

        if not relevant_projects:
            relevant_projects = [p for _, p in scored[:2]]

        # Filter technologies
        relevant_techs = [
            tech for tech in ALL_TECHNOLOGIES
            if tech.lower() in topic_lower
        ]
        if not relevant_techs:
            relevant_techs = ["Python", "FastAPI", "PostgreSQL", "Gemini"]

        context = AuthorContext(
            projects=relevant_projects,
            technologies=relevant_techs,
            current_context=self._dynamic_context,
        )

        logger.info(
            "[AUTHOR KNOWLEDGE] Context selected",
            extra={
                "injected_projects": [p.name for p in relevant_projects],
                "injected_technologies": relevant_techs,
            },
        )
        return context

    def update_dynamic_context(
        self,
        current_project: Optional[str] = None,
        recent_learning: Optional[str] = None,
        current_problem: Optional[str] = None,
        recent_success: Optional[str] = None,
    ) -> None:
        """Update the dynamic context fields.

        TODO: Eventually read these from a database instead of in-memory state.

        Args:
            current_project: What the author is currently working on.
            recent_learning: Something recently learned.
            current_problem: A problem currently being worked on.
            recent_success: A recent win or achievement.
        """
        if current_project is not None:
            self._dynamic_context.current_project = current_project
        if recent_learning is not None:
            self._dynamic_context.recent_learning = recent_learning
        if current_problem is not None:
            self._dynamic_context.current_problem = current_problem
        if recent_success is not None:
            self._dynamic_context.recent_success = recent_success
