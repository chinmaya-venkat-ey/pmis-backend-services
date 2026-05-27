"""Alembic environment for pmis-project-management.

Owns schema `project` and version table `project.alembic_version_project`.
Mirror declarations (users.*, masters.*) are excluded from autogenerate.
"""
from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

from app.config import settings
from app.db import Base
import app.models  # noqa: F401


config = context.config
config.set_main_option(
    "sqlalchemy.url",
    settings.database_url_migrations or settings.database_url,
)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

VERSION_TABLE = "alembic_version_project"
VERSION_TABLE_SCHEMA = "project"


def include_object(object, name, type_, reflected, compare_to):
    if type_ == "table" and getattr(object, "schema", None) and object.schema != VERSION_TABLE_SCHEMA:
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=VERSION_TABLE,
        version_table_schema=VERSION_TABLE_SCHEMA,
        include_object=include_object,
        compare_type=True,
        compare_server_default=True,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    # Create the project schema outside any transaction so it persists even
    # if the migration transaction rolls back mid-run.
    with connectable.connect() as _bootstrap:
        from sqlalchemy import text as _text
        _bootstrap.execution_options(isolation_level="AUTOCOMMIT").execute(
            _text("CREATE SCHEMA IF NOT EXISTS project")
        )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=VERSION_TABLE,
            version_table_schema=VERSION_TABLE_SCHEMA,
            include_object=include_object,
            compare_type=True,
            compare_server_default=True,
            include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
