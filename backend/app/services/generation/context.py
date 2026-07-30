"""
context.py
==========
PipelineContext — encapsulates the single execution state object passed
through all generation pipeline stages.

Carries trace_id, telemetry, topic, persona, generated outputs, and errors.
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from app.models.content import Persona, ContentDraft


@dataclass
class TelemetryData:
    """Records fine-grained latency and operational metrics for an execution trace."""

    start_time: float = field(default_factory=time.time)
    total_duration_ms: float = 0.0
    provider_latency_ms: float = 0.0
    db_latency_ms: float = 0.0
    image_generation_latency_ms: float = 0.0
    linkedin_latency_ms: float = 0.0
    retry_count: int = 0
    fallback_provider_used: Optional[str] = None

    def finish(self) -> float:
        """Mark total duration in milliseconds."""
        self.total_duration_ms = round((time.time() - self.start_time) * 1000, 2)
        return self.total_duration_ms

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_duration_ms": self.total_duration_ms,
            "provider_latency_ms": self.provider_latency_ms,
            "db_latency_ms": self.db_latency_ms,
            "image_generation_latency_ms": self.image_generation_latency_ms,
            "linkedin_latency_ms": self.linkedin_latency_ms,
            "retry_count": self.retry_count,
            "fallback_provider_used": self.fallback_provider_used,
        }


@dataclass
class PipelineContext:
    """Single state object passed through all stages of the generation pipeline."""

    topic: str
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    db: Optional[AsyncSession] = None
    persona: Optional[Persona] = None
    persona_id: Optional[str] = None
    feedback: Optional[str] = None

    # Pipeline Artifacts
    draft: Optional[ContentDraft] = None
    generated_text: str = ""
    refined_text: str = ""
    requires_image: bool = True
    image_prompt: Optional[str] = None
    image_url: Optional[str] = None

    # Metadata & Tracking
    llm_metadata: Dict[str, Any] = field(default_factory=dict)
    telemetry: TelemetryData = field(default_factory=TelemetryData)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        """Append an execution error."""
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        """Append an execution warning."""
        self.warnings.append(message)

    def to_dict(self) -> Dict[str, Any]:
        """Convert context state summary to dict for logging and response payload."""
        return {
            "trace_id": self.trace_id,
            "topic": self.topic,
            "persona_id": self.persona_id or (self.persona.id if self.persona else None),
            "requires_image": self.requires_image,
            "has_image_url": self.image_url is not None,
            "errors": self.errors,
            "warnings": self.warnings,
            "telemetry": self.telemetry.to_dict(),
        }
