import asyncio
import os
import sys

# Add backend directory to sys.path so we can import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.generation.visual_director import VisualDirector
from app.services.generation.router import sanitize_image_prompt

async def main():
    topics = [
        "Platforms locking out privacy focused operating systems like GrapheneOS exposes a deep fragility in our digital payment infrastructure...",
        "personal branding engine, FastAPI, Render, PostgreSQL, GitHub Actions, manual workers, external dependency shutdown, autonomous agents",
        "AI engineering and the future of personal branding engines"
    ]
    
    print("\n" + "="*50)
    print("VISUAL DIRECTOR TEST SCRIPT")
    print("="*50 + "\n")
    
    for i, topic in enumerate(topics):
        print(f"\n--- TEST TOPIC {i+1} ---")
        print(f"INPUT: {topic}")
        
        # Simulate draft text as same as topic for testing
        direction = await VisualDirector.generate_direction(topic, topic)
        
        print(f"\n[GENERATED JSON STRUCTURE]")
        print(f"Type: {direction.visual_type}")
        print(f"Subject: {direction.core_subject}")
        print(f"Metaphor: {direction.visual_metaphor}")
        print(f"Scene: {direction.scene}")
        print(f"Style: {direction.style}")
        print(f"Negative: {direction.negative_prompt}")
        
        final_prompt = sanitize_image_prompt(direction)
        print(f"\n[FINAL IMAGE PROMPT (Sent to Pollinations)]")
        print(final_prompt)
        print("-" * 50)

if __name__ == "__main__":
    asyncio.run(main())
