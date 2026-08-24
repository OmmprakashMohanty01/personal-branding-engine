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
    - If a diagram is chosen: Output raw PlantUML syntax. IF YOU CHOOSE 'diagram', YOU MUST OBEY THESE STRICT SYNTAX RULES:
      1. You MUST use PlantUML syntax. Do NOT use Mermaid.
      2. Start the code with `@startuml` and end with `@enduml`.
      3. Use the `skinparam` directive to enforce a clean, minimalist style. Example:
         skinparam monochrome true
         skinparam shadowing false
         skinparam defaultFontName Arial
      4. Keep it EXTREMELY simple. Maximum 3 to 4 nodes.
      5. Use Top-Down (`top to bottom direction`) or strictly linear layouts.
      6. Node labels must be short. Use `rectangle` or `component` shapes.
    
    POST CONTENT:
    {post_content}
    
    OUTPUT FORMAT:
    You must output ONLY a valid JSON object matching this schema exactly.
    
    {{
      "visual_type": "photo" | "diagram" | "none",
      "concept": "concrete visual description or diagram architecture",
      "prompt_or_code": "The detailed photography prompt OR the raw PlantUML syntax"
    }}
    
    For photography, format the prompt_or_code as:
    Editorial corporate technology photography, {{concrete_scene}}, natural light, 35mm photography, 8k resolution, minimalist composition. DO NOT INCLUDE: text, words, letters, logos, people, faces, 3d render, cartoon, glowing neon, cubes, pastel
    """
