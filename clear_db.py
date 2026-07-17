"""Dev-only: wipe every row in every table (dynamic — doesn't need updating as tables are added),
so you can re-run the signup -> onboarding flow from scratch. Connects as the DB OWNER (bypasses
RLS and any grant edge cases with TRUNCATE), NEVER used by the app itself.

Not wired into any Makefile/CI target on purpose — run it by hand:

    ./.venv/Scripts/python.exe clear_db.py     # Windows
    ./.venv/bin/python clear_db.py             # Unix

Destructive. Local/dev database only — never point this at anything real.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_owner_url)
    async with engine.begin() as conn:
        rows = await conn.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename != 'alembic_version'"
            )
        )
        tables = [r[0] for r in rows.fetchall()]
        if not tables:
            print("No tables found — nothing to clear.")
            return
        table_list = ", ".join(f'"{t}"' for t in tables)
        await conn.execute(text(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE"))
        print(f"Cleared {len(tables)} tables: {', '.join(sorted(tables))}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
