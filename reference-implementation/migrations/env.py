"""Alembic environment.

Reads the database DSN from the LEDGER_DSN environment variable so the
same migrations work against developer Postgres, CI, BYOC, and
air-gapped deployments without committing connection strings.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _dsn() -> str:
    dsn = os.environ.get("LEDGER_DSN")
    if not dsn:
        raise RuntimeError(
            "LEDGER_DSN environment variable is required. Example: "
            "postgresql://ski:secret@localhost:5432/ski_ledger"
        )
    # Alembic uses SQLAlchemy's sync engine; ensure psycopg driver, not the
    # async one used by the runtime.
    if dsn.startswith("postgresql+psycopg://"):
        dsn = dsn.replace("postgresql+psycopg://", "postgresql://", 1)
    return dsn


def run_migrations_offline() -> None:
    """Generate SQL without connecting to a database (useful for review)."""
    context.configure(
        url=_dsn(),
        target_metadata=None,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against the live database."""
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _dsn()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
