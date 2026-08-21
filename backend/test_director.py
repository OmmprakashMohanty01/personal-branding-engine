import asyncio
from app.services.generation.image_director import get_visual_director_prompt
from app.services.llm_provider import GeminiProvider

async def main():
    post_content = "When your Docker environments are syncing perfectly with production, there's no more 'it works on my machine' excuses. We just deployed a unified container strategy across our enterprise infrastructure, drastically reducing deployment times and eliminating environment drift. Clean configuration, reproducible builds, seamless scaling."
    
    prompt = get_visual_director_prompt(post_content)
    
    llm = GeminiProvider()
    response = await llm.generate(
        prompt=post_content,
        system_instruction=prompt,
        temperature=0.4
    )
    
    print("=== RAW RESPONSE ===")
    print(response)

if __name__ == "__main__":
    asyncio.run(main())
