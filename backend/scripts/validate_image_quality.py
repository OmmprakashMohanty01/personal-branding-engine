#!/usr/bin/env python3
"""
validate_image_quality.py
=========================
A standalone diagnostic script to evaluate the Image Generation pipeline.
Generates 5 images concurrently using Pollinations AI based on typical daily prompts
and saves them to the backend/artifacts folder for visual inspection.
"""

import asyncio
import base64
import os
import sys

# Ensure backend path is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.generation.providers import PollinationsImageProvider

PROMPTS = [
    "A sleek, modern illustration representing artificial intelligence and news analysis, minimalistic, tech-focused, digital art.",
    "A developer sitting in a cozy dark-mode coding environment solving a challenge, focus on glowing screens, highly detailed.",
    "A structured, abstract representation of software architecture and frameworks, clean geometric lines, professional blue tones.",
    "A professional and inspiring scene of career growth in software engineering, abstract data visualization, vibrant and clean.",
    "A sleek, futuristic representation of a new software tool being launched, glowing interface elements, minimalistic dark background."
]

async def validate_images():
    print("Starting Image Quality Validation Pipeline...")
    artifacts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "artifacts"))
    os.makedirs(artifacts_dir, exist_ok=True)
    
    provider = PollinationsImageProvider()
    sem = asyncio.Semaphore(1)
    
    async def fetch_and_save(index: int, prompt: str):
        async with sem:
            print(f"[{index+1}/5] Generating image for prompt: '{prompt[:50]}...'")
        
        try:
            # Generate the image data URI
            image_uri = await provider.generate_image(prompt)
            
            if not image_uri:
                print(f"❌ [{index+1}/5] Failed: Provider returned None.")
                return
                
            # Extract base64 content from data URI
            if not image_uri.startswith("data:image/jpeg;base64,"):
                print(f"❌ [{index+1}/5] Failed: Invalid data URI format.")
                return
                
            b64_data = image_uri.split(",", 1)[1]
            image_bytes = base64.b64decode(b64_data)
            
            # Save to artifacts directory
            filepath = os.path.join(artifacts_dir, f"validation_image_{index+1}.jpg")
            with open(filepath, "wb") as f:
                f.write(image_bytes)
                
            print(f"✅ [{index+1}/5] Success! Saved to {filepath}")
            
        except Exception as e:
            print(f"❌ [{index+1}/5] Error: {str(e)}")

    # Run concurrently
    tasks = [fetch_and_save(i, prompt) for i, prompt in enumerate(PROMPTS)]
    await asyncio.gather(*tasks)
    
    print("\nImage Generation complete. Please inspect the images in backend/artifacts/.")

if __name__ == "__main__":
    asyncio.run(validate_images())
