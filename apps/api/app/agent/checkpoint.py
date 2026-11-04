from functools import lru_cache

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy import make_url

from app.core.config import get_settings

SCHEMA = "agent_state"


def psycopg_url(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


def setup_checkpointer(owner_url: str, app_role: str) -> None:
    with Connection.connect(psycopg_url(owner_url), autocommit=True, row_factory=dict_row) as conn:
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        conn.execute(f"SET search_path TO {SCHEMA}")
        PostgresSaver(conn).setup()
        conn.execute(f'GRANT USAGE ON SCHEMA {SCHEMA} TO "{app_role}"')
        conn.execute(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {SCHEMA} TO "{app_role}"'
        )


@lru_cache
def _pool() -> AsyncConnectionPool:
    return AsyncConnectionPool(
        psycopg_url(get_settings().database_url),
        open=False,
        max_size=10,
        kwargs={
            "autocommit": True,
            "row_factory": dict_row,
            "prepare_threshold": 0,
            "options": f"-c search_path={SCHEMA}",
        },
    )


async def get_checkpointer() -> AsyncPostgresSaver:
    pool = _pool()
    await pool.open()
    return AsyncPostgresSaver(pool)  # type: ignore[arg-type]


async def close_checkpointer() -> None:
    if _pool.cache_info().currsize:
        await _pool().close()
        _pool.cache_clear()
