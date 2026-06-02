from typing import AsyncGenerator
from urllib.parse import urlparse, parse_qs, urlunparse, urlencode
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.config import settings

# Setup database dialect compatibility (enforce postgresql+asyncpg mode)
database_url = settings.DATABASE_URL
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

# Connection arguments setup
connect_args = {}
if "sqlite" in database_url:
    connect_args["check_same_thread"] = False
elif "postgresql" in database_url:
    # Handle sslmode parameter for asyncpg
    parsed_url = urlparse(database_url)
    query_params = parse_qs(parsed_url.query)
    
    if "sslmode" in query_params:
        sslmode = query_params.pop("sslmode")[0]
        # Translate sslmode to asyncpg's ssl argument
        if sslmode in ("require", "verify-ca", "verify-full"):
            connect_args["ssl"] = True
        else:
            connect_args["ssl"] = False
            
        # Reconstruct the URL without the sslmode query parameter to prevent asyncpg TypeError
        new_query = urlencode(query_params, doseq=True)
        database_url = urlunparse((
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            parsed_url.params,
            new_query,
            parsed_url.fragment
        ))

engine = create_async_engine(
    database_url,
    connect_args=connect_args,
    echo=False
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

Base = declarative_base()

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency injection session provider."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
