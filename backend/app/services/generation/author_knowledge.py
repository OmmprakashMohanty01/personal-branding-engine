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
        name="Personal Branding Engine",
        description="Autonomous AI pipeline that generates and publishes daily LinkedIn posts using Gemini, Cohere, and Pollinations AI. Deployed on Render with PostgreSQL and GitHub Actions cron automation.",
        tags=["fastapi", "ai", "llm", "automation", "linkedin", "render", "postgresql", "gemini", "cohere", "pollinations", "github-actions", "python"],
    ),
    Project(
        name="AI Job Hunter",
        description="Automated job application system using AI agents for resume tailoring, cover letter generation, and application tracking.",
        tags=["ai", "automation", "agents", "python", "job-search", "llm"],
    ),
    Project(
        name="YOLOv8 Player ReID",
        description="Computer vision system for real-time player re-identification in sports footage using YOLOv8 object detection and re-identification techniques.",
        tags=["computer-vision", "yolo", "deep-learning", "python", "pytorch", "sports", "ml"],
    ),
    Project(
        name="Business RAG",
        description="Retrieval-Augmented Generation system for business document Q&A using vector databases and LLM inference.",
        tags=["rag", "llm", "vector-database", "ai", "python", "langchain"],
    ),
]

# ---------------------------------------------------------------------------
# Technology registry
# ---------------------------------------------------------------------------
ALL_TECHNOLOGIES: List[str] = [
    "Python", "FastAPI", "PostgreSQL", "Docker", "Render",
    "Gemini", "Cohere", "Pollinations AI", "GitHub Actions",
    "SQLAlchemy", "Alembic", "Pydantic", "YOLOv8", "PyTorch",
    "LangChain", "RAG", "Linux", "Git", "Vercel",
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
