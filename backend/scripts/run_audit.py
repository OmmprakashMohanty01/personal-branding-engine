import asyncio
import logging
import sys
import os

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import AsyncSessionLocal
from app.services.generation.pipeline import ContentGenerationPipeline
from app.services.generation.context import PipelineContext

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("audit")

async def run():
    pipeline = ContentGenerationPipeline()
    async with AsyncSessionLocal() as db:
        context = PipelineContext(
            topic="Data pipelines and web scraping infrastructure over twenty years.", 
            trace_id="audit-1",
            db=db
        )
        logger.info("=== STARTING PIPELINE E2E AUDIT ===")
        draft = await pipeline.run(context, commit_db=False)
        logger.info("=== PIPELINE E2E AUDIT COMPLETE ===")
        logger.info(f"Final saved draft content chars: {len(draft.content_text)}")

if __name__ == "__main__":
    asyncio.run(run())
