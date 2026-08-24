import json

def get_visual_director_prompt(post_content: str) -> str:
    return f"""
    Analyze this technical LinkedIn post and act as an Art Director for a premium tech magazine.
    Your job is to decide the best visual medium for this post and generate the routing payload.
    
    Category Mappings:
    - Data/Databases: Modern server infrastructure, clean server racks, fiber optic patch panels, slate and graphite palette.
    - Developer Workflows: Overhead minimalist workstation, mechanical keyboard, espresso, natural window lighting.
    - Cloud/DevOps/Scale: Modern brutalist glass and concrete architecture, clean structural angles, dramatic natural daylight.
    - AI/Systems: Precision enterprise compute clusters, matte industrial finish, subtle status LEDs.
    - System Architecture/Data Flows: Use an architectural diagram to illustrate components.
    - Soft Skills/Generic Advice: No image needed.
    
    RULES:
    - If a photo is chosen: No In-Image Text Rule: Explicitly forbid text, typography, fake UIs, logos, and labels. NO fantasy, NO cyberpunk, NO robots, NO glowing floating cubes, NO generic AI art.
    - If a diagram is chosen: Output raw Mermaid.js syntax. IF YOU CHOOSE 'diagram', YOU MUST OBEY THESE STRICT SYNTAX RULES:
      1. Keep it EXTREMELY simple. Maximum 3 to 4 nodes.
      2. Use Top-Down (`graph TD` in Mermaid) or strictly linear layouts.
      3. Node labels must be incredibly short (1 to 3 words maximum). Do NOT put long sentences inside nodes or they will overlap and look terrible.
      4. Do NOT use complex subgraphs, nested boxes, or asymmetrical branching.
    
    POST CONTENT:
    {post_content}
    
    OUTPUT FORMAT:
    You must output ONLY a valid JSON object matching this schema exactly.
    
    {{
      "visual_type": "photo" | "diagram" | "none",
      "concept": "concrete visual description or diagram architecture",
      "prompt_or_code": "The detailed photography prompt OR the raw Mermaid.js syntax"
    }}
    
    For photography, format the prompt_or_code as:
    Editorial corporate technology photography, {{concrete_scene}}, natural light, 35mm photography, 8k resolution, minimalist composition. DO NOT INCLUDE: text, words, letters, logos, people, faces, 3d render, cartoon, glowing neon, cubes, pastel
    """
