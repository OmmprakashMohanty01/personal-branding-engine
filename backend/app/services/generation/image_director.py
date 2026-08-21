def get_visual_director_prompt(post_content: str) -> str:
    return f"""
    Analyze this technical LinkedIn post and act as an Art Director for a premium tech magazine.
    Your job is to map the technical content into a concrete, professional editorial scene.
    
    Category Mappings:
    - Data/Databases: Modern server infrastructure, clean server racks, fiber optic patch panels, slate and graphite palette.
    - Developer Workflows: Overhead minimalist workstation, mechanical keyboard, espresso, natural window lighting.
    - Cloud/DevOps/Scale: Modern brutalist glass and concrete architecture, clean structural angles, dramatic natural daylight.
    - AI/Systems: Precision enterprise compute clusters, matte industrial finish, subtle status LEDs.
    
    RULES:
    - No In-Image Text Rule: Explicitly forbid text, typography, fake UIs, logos, and labels inside the prompt.
    - NO fantasy, NO cyberpunk, NO robots, NO glowing floating cubes, NO generic AI art.
    
    POST CONTENT:
    {post_content}
    
    OUTPUT FORMAT:
    You must output ONLY a clean, prompt string wrapped EXACTLY in this format:
    Editorial corporate technology photography, {{concrete_scene}}, natural light, 35mm photography, 8k resolution, minimalist composition. DO NOT INCLUDE: text, words, letters, logos, people, faces, 3d render, cartoon, glowing neon, cubes, pastel
    """
