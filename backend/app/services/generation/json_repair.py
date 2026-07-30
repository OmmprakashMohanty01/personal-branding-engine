"""
json_repair.py
==============
JSONRepairStage — deterministic JSON cleaning and structural repair stage
before re-calling LLMs on formatting errors.
"""

import json
import logging
import re
from typing import Any, Dict, Tuple

logger = logging.getLogger("branding_engine.generation.json_repair")


class JSONRepairStage:
    """Strips markdown fences, fixes unescaped characters, and repairs malformed JSON."""

    @staticmethod
    def repair(raw_text: str) -> Tuple[Dict[str, Any], bool]:
        """Attempt to repair and parse JSON from raw text.

        Args:
            raw_text: String output from LLM.

        Returns:
            Tuple of (parsed_dict, was_repaired_bool).
        """
        if not raw_text or not raw_text.strip():
            return {"content_text": raw_text or ""}, False

        clean_output = raw_text.strip()
        was_repaired = False

        # 1. Strip Markdown Code Blocks
        code_block_match = re.search(r"```(?:json)?\s*(.*?)\s*```", clean_output, re.DOTALL)
        if code_block_match:
            clean_output = code_block_match.group(1).strip()
            was_repaired = True

        # 2. Try direct JSON parse
        try:
            parsed = json.loads(clean_output)
            if isinstance(parsed, dict):
                return parsed, was_repaired
        except json.JSONDecodeError as exc:
            logger.warning(f"[JSON REPAIR] Direct json.loads failed ({exc}). Attempting deterministic repairs.")
            was_repaired = True

        # 3. Clean trailing commas in objects and arrays
        repaired_text = re.sub(r",\s*([}\]])", r"\1", clean_output)

        try:
            parsed = json.loads(repaired_text)
            if isinstance(parsed, dict):
                return parsed, True
        except json.JSONDecodeError:
            pass

        # 4. Regex Fallback Extraction
        parsed_data: Dict[str, Any] = {}

        content_match = re.search(r'"content_text"\s*:\s*"(.*?)"\s*,\s*"requires_image"', clean_output, re.DOTALL)
        if not content_match:
            content_match = re.search(r'"content_text"\s*:\s*"(.*?)"\s*,\s*"metadata"', clean_output, re.DOTALL)
        if not content_match:
            content_match = re.search(r'"content_text"\s*:\s*"(.*?)"\s*}', clean_output, re.DOTALL)

        requires_img_match = re.search(r'"requires_image"\s*:\s*(true|false)', clean_output, re.IGNORECASE)
        img_prompt_match = re.search(r'"image_prompt"\s*:\s*"(.*?)"', clean_output, re.DOTALL)

        if content_match:
            val = content_match.group(1)
            # Unescape quotes/newlines
            val = val.replace('\\"', '"').replace("\\n", "\n")
            parsed_data["content_text"] = val
        else:
            # Utter fallback: raw text as content
            parsed_data["content_text"] = clean_output

        parsed_data["requires_image"] = requires_img_match.group(1).lower() == "true" if requires_img_match else True

        if img_prompt_match:
            parsed_data["image_prompt"] = img_prompt_match.group(1)

        logger.info(f"[JSON REPAIR] Extracted fallback JSON schema keys: {list(parsed_data.keys())}")
        return parsed_data, True
