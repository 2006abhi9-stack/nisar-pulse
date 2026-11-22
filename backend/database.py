import os
from collections.abc import AsyncGenerator
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

# Load environment variables
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./nisar_pulse.db")

# For SQLite, ensure directory exists and path is anchored to backend
if "sqlite" in DATABASE_URL:
    db_file = DATABASE_URL.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
    if db_file and not db_file.startswith(":memory:"):
        db_path = Path(db_file)
        if not db_path.is_absolute():
            db_path = (Path(__file__).resolve().parent / db_path).resolve()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_db_str = db_path.as_posix()
        DATABASE_URL = f"sqlite+aiosqlite:///{resolved_db_str}"

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for obtaining async DB sessions."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """Initializes database tables asynchronously."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
