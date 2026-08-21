import io
import logging
from PIL import Image

logger = logging.getLogger(__name__)

def validate_image_bytes(image_bytes: bytes) -> bool:
    """
    Validates that the generated image bytes are actually a valid image
    of sufficient quality and size.
    """
    if not image_bytes:
        return False
        
    size_kb = len(image_bytes) / 1024
    if size_kb < 50:
        logger.warning(f"[QUALITY GATE] Image too small: {size_kb:.2f}KB (< 50KB)")
        return False
        
    try:
        # Check if PIL can parse it (catches HTML error pages disguised as images)
        img = Image.open(io.BytesIO(image_bytes))
        img.verify()  # Verify it is an image
        
        # We need to re-open to check dimensions because verify() might close it
        img = Image.open(io.BytesIO(image_bytes))
        width, height = img.size
        if width < 800 or height < 800:
            logger.warning(f"[QUALITY GATE] Image dimensions too small: {width}x{height}")
            return False
            
        logger.info(f"[QUALITY GATE] Image passed: {size_kb:.2f}KB, {width}x{height}")
        return True
    except Exception as e:
        logger.warning(f"[QUALITY GATE] Failed to parse image bytes: {e}")
        return False
