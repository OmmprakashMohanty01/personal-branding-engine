import os
import io
import base64
import urllib.request
import textwrap
import logging
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("branding_engine.generation.image_card")

def get_font(size: int = 40) -> ImageFont.FreeTypeFont:
    """Fetch and return a clear monospace font."""
    font_path = "/tmp/RobotoMono-Regular.ttf"
    try:
        if not os.path.exists(font_path):
            url = "https://github.com/googlefonts/RobotoMono/raw/main/fonts/ttf/RobotoMono-Regular.ttf"
            urllib.request.urlretrieve(url, font_path)
        return ImageFont.truetype(font_path, size)
    except Exception as e:
        logger.warning(f"Failed to load TTF font, falling back to default: {e}")
        return ImageFont.load_default()

def extract_hook(text: str) -> str:
    """Extract the first 1-2 sentences (or first paragraph) as the hook."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return ""
    
    # Take the first paragraph
    hook = paragraphs[0]
    
    # If it's too long, truncate it nicely
    if len(hook) > 180:
        sentences = hook.split(". ")
        if len(sentences) > 1 and len(sentences[0]) < 180:
            hook = sentences[0] + "."
        else:
            hook = hook[:177] + "..."
    return hook

def generate_quote_card(text: str) -> str:
    """
    Generate a 1080x1080 Dark-Mode Quote Card from the post text.
    Returns a base64 encoded data URI.
    """
    hook = extract_hook(text)
    if not hook:
        hook = "Building in public."

    width, height = 1080, 1080
    bg_color = "#0F172A"  # Dark slate
    
    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)
    
    font = get_font(size=44)
    
    # Draw editor window frame
    window_margin_x = 100
    window_margin_y = 250
    draw.rounded_rectangle(
        [(window_margin_x, window_margin_y), (width - window_margin_x, height - window_margin_y)],
        radius=20,
        fill="#1E293B",
        outline="#334155",
        width=3
    )
    
    # Draw 3 subtle colored dots (macOS style window controls)
    dot_y = window_margin_y + 30
    draw.ellipse([(140, dot_y), (160, dot_y + 20)], fill="#EF4444")  # Red
    draw.ellipse([(180, dot_y), (200, dot_y + 20)], fill="#F59E0B")  # Yellow
    draw.ellipse([(220, dot_y), (240, dot_y + 20)], fill="#10B981")  # Green
    
    # Word wrapping for text
    max_chars_per_line = 32
    lines = textwrap.wrap(hook, width=max_chars_per_line)
    
    # Calculate vertical centering
    # Using a typical height per line approximation
    try:
        line_heights = [draw.textbbox((0, 0), line, font=font)[3] - draw.textbbox((0, 0), line, font=font)[1] for line in lines]
        total_text_height = sum(line_heights) + (len(lines) - 1) * 20
    except Exception:
        # Fallback for default font
        total_text_height = len(lines) * 50

    start_y = window_margin_y + 80 + ( (height - 2 * window_margin_y - 80) - total_text_height ) / 2
    
    y_text = start_y
    for line in lines:
        try:
            left, top, right, bottom = draw.textbbox((0, 0), line, font=font)
            line_width = right - left
        except Exception:
            line_width = len(line) * 20
            bottom, top = 20, 0
            
        x_text = (width - line_width) / 2
        draw.text((x_text, y_text), line, font=font, fill="#F8FAFC")
        y_text += (bottom - top) + 20
        
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    b64_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64_str}"
