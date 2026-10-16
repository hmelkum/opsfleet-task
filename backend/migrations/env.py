import asyncio

from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The connection comes from the same POSTGRES__* settings the backend uses.
from src.config.service import ConfigService

# Import the entity modules so their tables register on each module's metadata.
# Every backend module owns its own Postgres schema.
from src.artifacts import entities as artifacts_entities  # noqa: F401
from src.artifacts.entities.base import BaseArtifactsEntity
from src.gateway import entities as gateway_entities  # noqa: F401
from src.gateway.entities.base import BaseChatEntity

target_metadata = [
    BaseChatEntity.metadata,
    BaseArtifactsEntity.metadata,
]

SCHEMAS = {metadata.schema for metadata in target_metadata}


def include_name(name, type_, parent_names) -> bool:
    """Only compare the schemas this backend owns."""
    if type_ == "schema":
        return name in SCHEMAS
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode, emitting SQL to the script output."""
    context.configure(
        url=ConfigService().postgres.url.render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_name=include_name,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = create_async_engine(
        ConfigService().postgres.url,
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
