"""
validators.py
=============
ValidatorRegistry — enforces quality, safety, length, and compliance rules
on generated content drafts.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Any

logger = logging.getLogger("branding_engine.generation.validators")

BANNED_CLICHES: List[str] = [
    "delve",
    "unlock",
    "leverage",
    "synergy",
    "game-changer",
    "paradigm shift",
    "in today's world",
]

SUSPICIOUS_SHORT_LINKS: List[str] = [
    "lnkd.in",
    "bit.ly",
    "tinyurl.com",
    "goo.gl",
    "ow.ly",
    "t.co",
]

FORBIDDEN_IMAGE_TERMS: List[str] = [
    "text",
    "words",
    "typography",
    "laptop",
    "code screenshot",
    "ui screenshot",
    "blue brain",
    "hologram",
    "robot",
    "logo",
]

SUSPICIOUS_PERSONAL_CLAIMS: List[str] = [
    r"\bi built\b",
    r"\bi created\b",
    r"\bi developed\b",
    r"\blast year i\b",
    r"\bi experimented with\b",
    r"\bwhen i worked at\b",
    r"\bi recently published\b",
    r"\bi founded\b",
]


@dataclass
class ValidationResult:
    """Result of content validation."""

    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_error(self, err: str) -> None:
        self.errors.append(err)
        self.is_valid = False

    def add_warning(self, warn: str) -> None:
        self.warnings.append(warn)


class LengthValidator:
    """Validates that text length is within LinkedIn's limits (<= 3000 chars)."""

    def __init__(self, max_length: int = 3000):
        self.max_length = max_length

    def validate(self, text: str, result: ValidationResult) -> None:
        if len(text) > self.max_length:
            result.add_error(
                f"Post length ({len(text)} chars) exceeds LinkedIn maximum limit of {self.max_length} chars."
            )


class BannedWordValidator:
    """Validates that text contains none of the 7 high-impact clichés."""

    def __init__(self, banned_words: List[str] = BANNED_CLICHES):
        self.banned_words = banned_words

    def validate(self, text: str, result: ValidationResult) -> None:
        text_lower = text.lower()
        for word in self.banned_words:
            if word in text_lower:
                result.add_error(f"Banned cliché detected: '{word}'.")


class LinkValidator:
    """Validates that links are legitimate and do not contain fake shortened URLs."""

    def validate(self, text: str, result: ValidationResult) -> None:
        # Check for hallucinated shortened links
        for shortener in SUSPICIOUS_SHORT_LINKS:
            if shortener in text.lower():
                result.add_error(f"Hallucinated shortened link detected ('{shortener}').")

        # Count markdown or HTTP links
        url_matches = re.findall(r"https?://[^\s\)]+", text)
        if len(url_matches) > 1:
            result.add_warning(f"Multiple links detected ({len(url_matches)} links). Prefer max 1 link.")


class ImageValidator:
    """Validates image prompt rules when requires_image is True."""

    def validate(self, requires_image: bool, image_prompt: str, result: ValidationResult) -> None:
        if not requires_image:
            return

        if not image_prompt or not image_prompt.strip():
            result.add_warning("requires_image is True but image_prompt is empty.")
            return

        prompt_lower = image_prompt.lower()
        for forbidden in FORBIDDEN_IMAGE_TERMS:
            if forbidden in prompt_lower:
                result.add_warning(
                    f"Image prompt contains discouraged element: '{forbidden}'."
                )

class FactValidator:
    """Validates that personal claims correspond to the Author Context."""

    def __init__(self, patterns: List[str] = SUSPICIOUS_PERSONAL_CLAIMS):
        self.patterns = patterns

    def validate(self, text: str, author_context: Optional[Any], result: ValidationResult) -> None:
        text_lower = text.lower()
        
        for pattern in self.patterns:
            matches = re.finditer(pattern, text_lower)
            for match in matches:
                # Extract surrounding context (roughly a sentence or two)
                start_idx = max(0, match.start() - 30)
                end_idx = min(len(text_lower), match.end() + 70)
                claim_context = text_lower[start_idx:end_idx]
                
                is_grounded = False
                
                if author_context:
                    # Fuzzy match: check if any project name or technology appears in the claim context
                    for p in author_context.projects:
                        if p.name.lower() in claim_context:
                            is_grounded = True
                            break
                    if not is_grounded:
                        for t in author_context.technologies:
                            if t.lower() in claim_context:
                                is_grounded = True
                                break
                    if not is_grounded and author_context.current_context:
                        # Check current project string
                        if author_context.current_context.current_project and "branding engine" in author_context.current_context.current_project.lower():
                            if "branding engine" in claim_context:
                                is_grounded = True

                if not is_grounded:
                    # If we couldn't ground it, fail the draft
                    result.add_error(
                        f"Ungrounded personal claim detected: '...{claim_context.strip()}...'. "
                        "This claim was not found in the injected Author Context."
                    )


class ValidatorRegistry:
    """Executes all validators against a generated post."""

    def __init__(self):
        self.length_validator = LengthValidator()
        self.banned_validator = BannedWordValidator()
        self.link_validator = LinkValidator()
        self.image_validator = ImageValidator()
        self.fact_validator = FactValidator()

    def validate(
        self,
        content_text: str,
        requires_image: bool = False,
        image_prompt: str = "",
        author_context: Optional[Any] = None,
    ) -> ValidationResult:
        """Run all validators and return aggregated ValidationResult."""
        result = ValidationResult(is_valid=True)

        self.length_validator.validate(content_text, result)
        self.banned_validator.validate(content_text, result)
        self.link_validator.validate(content_text, result)
        self.image_validator.validate(requires_image, image_prompt, result)
        self.fact_validator.validate(content_text, author_context, result)

        logger.info(
            f"[VALIDATOR REGISTRY] Validation complete. Valid: {result.is_valid}, "
            f"Errors: {len(result.errors)}, Warnings: {len(result.warnings)}"
        )
        return result
