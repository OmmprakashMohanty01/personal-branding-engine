import asyncio
import os
import sys

# Ensure backend directory is in python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import engine, AsyncSessionLocal
from app.models.integration import LinkedInAccount
from sqlalchemy import delete

async def main():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("INFO: DATABASE_URL environment variable is not set. Running on local SQLite database.")
    else:
        print(f"Connecting to database using DATABASE_URL: {db_url.split('@')[-1] if '@' in db_url else db_url}")

    try:
        async with AsyncSessionLocal() as session:
            print("Purging mock LinkedIn account records...")
            # Delete records where linkedin_person_urn contains 'mock'
            stmt = delete(LinkedInAccount).where(LinkedInAccount.linkedin_person_urn.like('%mock%'))
            result = await session.execute(stmt)
            await session.commit()
            print(f"SUCCESS: Deleted {result.rowcount} mock LinkedIn account record(s).")
    except Exception as e:
        print(f"ERROR: Failed to delete mock records: {e}", file=sys.stderr)
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
