import json

def get_visual_director_prompt(post_content: str) -> str:
    return f"""
    Analyze this technical LinkedIn post and act as an Art Director for a premium tech magazine.
    Output a strictly formatted JSON object dictating the image generation parameters.
    
    RULES:
    - Focus on realistic, tangible enterprise infrastructure or modern workspaces.
    - NO fantasy, NO cyberpunk, NO robots, NO glowing floating cubes, NO generic AI art.
    - Palette: Graphite, navy, brushed aluminum, natural light.
    
    POST CONTENT:
    {post_content}
    
    EXPECTED JSON FORMAT:
    {{
      "visual_type": "editorial_technology",
      "concept": "concise description of the physical scene",
      "style": "premium technology editorial photography",
      "avoid": "cyberpunk, glowing neon, robots, text, floating cubes"
    }}
    """
