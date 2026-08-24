def get_raw_log_prompt(topic: str, context: str) -> str:
    return f"""
    You are a tired Senior Software Engineer. You just spent two hours debugging a frustrating problem.
    Write a raw, internal Slack message to a coworker about this topic: '{topic}'.
    
    RULES FOR THE LOG:
    1. THE TROJAN HORSE: Do not start with pure backend terminology. Frame the technical issue inside a universally relatable problem (e.g., overengineering, technical debt, wasted time).
    2. THE 70/20/10 RATIO: 70% of the log is the gritty, specific experience (what broke, what metrics spiked). 20% is an accessible explanation of the fix. 10% is a brief, exhausted realization.
    3. THE OPEN LOOP: Create tension between the problem and the solution. Make the reader want to know how you fixed it.
    4. NO CORPORATE SPEAK: Do not use words like "ensure", "reliability", "leverage", "delve", or "crucial".
    
    Context to include: {context}
    
    Output ONLY the raw slack message.
    """
