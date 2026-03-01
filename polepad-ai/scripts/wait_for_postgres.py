import asyncio
import os
import sys
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://polepad:polepad@postgres:5432/polepad")
MAX_ATTEMPTS = int(os.getenv("DB_WAIT_ATTEMPTS", "45"))
SLEEP_SECONDS = float(os.getenv("DB_WAIT_SLEEP", "2"))


async def main() -> int:
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    try:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
                print(f"[wait_for_postgres] Database ready after {attempt} attempt(s)")
                return 0
            except Exception as exc:
                print(f"[wait_for_postgres] attempt {attempt}/{MAX_ATTEMPTS} failed: {exc}")
                await asyncio.sleep(SLEEP_SECONDS)
        print("[wait_for_postgres] timed out waiting for database")
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
