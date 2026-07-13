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
        print("WARNING: DATABASE_URL environment variable is not set. Defaulting to local config/SQLite.")
    else:
        print(f"Connecting to database using provided DATABASE_URL: {db_url.split('@')[-1] if '@' in db_url else db_url}")

    try:
        async with AsyncSessionLocal() as session:
            # Check current records
            print("Attempting to delete LinkedIn account records...")
            stmt = delete(LinkedInAccount)
            result = await session.execute(stmt)
            await session.commit()
            print(f"SUCCESS: Deleted {result.rowcount} LinkedIn account record(s).")
    except Exception as e:
        print(f"ERROR: Failed to delete records: {e}", file=sys.stderr)
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
