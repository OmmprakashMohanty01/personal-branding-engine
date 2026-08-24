def get_compiler_prompt(raw_log: str) -> str:
    return f"""
    You are an elite technical editor. Take this raw engineering log and format it for a broad audience.
    
    RAW LOG:
    {raw_log}
    
    ABSOLUTE FORBIDDEN LAWS (Failing these means immediate rejection):
    1. FORBIDDEN TYPOGRAPHY: You MUST NOT use hyphens or dashes (-) anywhere in the text. You MUST NOT use bullet points, asterisks, or numbered lists.
    2. FORBIDDEN HOOKS: Never start with "I realized", "I could be wrong", "In today's", or "It's amazing how". 
    3. FORBIDDEN TONE: Do not add a moral, a lesson, or broad advice at the end. The story IS the lesson. Let the reader figure it out.
    4. FORBIDDEN WORDS: delve, tapestry, landscape, game-changer, seamless, robust, absolute.
    
    FORMATTING & RETENTION:
    - Break the text into 1 to 2 sentence paragraphs maximum. Use ample white space for extreme scannability.
    - Keep the gritty, frustrated, or direct tone of the original log. Show the tiny imperfections and uncertainty.
    - End the post by asking a single, specific question to invite the audience to share their own frustrating experiences.
    
    Output ONLY the final text.
    """
