"""
image_quality_gate.py
=====================
Deterministic image quality validation gate.

Validates structural properties of generated images before they are
persisted to the database. Does NOT use a vision model — instead checks
byte-level properties (size, format headers, corruption).
"""

import base64
import logging
from typing import Tuple

logger = logging.getLogger("branding_engine.generation.image_quality_gate")


class ImageQualityGate:
    """Validates image data URIs before persistence."""

    MIN_IMAGE_SIZE_BYTES = 10_000       # 10KB — reject broken/placeholder images
    MAX_IMAGE_SIZE_BYTES = 10_000_000   # 10MB — reject suspiciously large images

    # JPEG magic bytes: FF D8 FF
    JPEG_MAGIC = b'\xff\xd8\xff'
    # PNG magic bytes: 89 50 4E 47
    PNG_MAGIC = b'\x89PNG'

    @classmethod
    def validate(cls, image_data_uri: str) -> Tuple[bool, str]:
        """Validate a base64 data URI image.

        Checks:
        1. Data URI format is valid
        2. Base64 decodes without error
        3. Image size is within acceptable bounds
        4. Image has valid JPEG or PNG magic bytes

        Args:
            image_data_uri: A base64 data URI string (e.g., "data:image/jpeg;base64,...")

        Returns:
            Tuple of (is_valid, reason). reason is empty string if valid.
        """
        if not image_data_uri:
            return False, "Image data URI is empty or None"

        # Extract base64 payload
        if "," in image_data_uri:
            header, b64_data = image_data_uri.split(",", 1)
        else:
            b64_data = image_data_uri
            header = ""

        # Validate base64 decoding
        try:
            image_bytes = base64.b64decode(b64_data)
        except Exception as e:
            return False, f"Base64 decoding failed: {e}"

        byte_count = len(image_bytes)

        # Size gate
        if byte_count < cls.MIN_IMAGE_SIZE_BYTES:
            return False, (
                f"Image too small ({byte_count} bytes < {cls.MIN_IMAGE_SIZE_BYTES} bytes). "
                f"Likely a broken or placeholder image."
            )

        if byte_count > cls.MAX_IMAGE_SIZE_BYTES:
            return False, (
                f"Image too large ({byte_count} bytes > {cls.MAX_IMAGE_SIZE_BYTES} bytes)."
            )

        # Magic byte validation
        is_jpeg = image_bytes[:3] == cls.JPEG_MAGIC
        is_png = image_bytes[:4] == cls.PNG_MAGIC

        if not (is_jpeg or is_png):
            return False, (
                f"Image does not have valid JPEG or PNG header bytes. "
                f"First 4 bytes: {image_bytes[:4].hex()}"
            )

        logger.info(
            f"[IMAGE QUALITY GATE] PASSED — "
            f"{'JPEG' if is_jpeg else 'PNG'}, "
            f"{byte_count / 1024:.1f}KB"
        )

        return True, ""
