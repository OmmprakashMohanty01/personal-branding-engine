import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import engine, Base
from app.models.content import Persona, ContentDraft
from app.models.integration import LinkedInAccount

async def reset_db():
    print("Dropping all tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        print("Creating all tables freshly...")
        await conn.run_sync(Base.metadata.create_all)
    print("Database reset completed successfully!")

if __name__ == "__main__":
    asyncio.run(reset_db())
