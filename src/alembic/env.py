"""Alembic environment for pmis-project-service.

Key points:
- DATABASE_URL is read from app.core.config.settings (env-driven).
- target_metadata is Base.metadata from this service's own session module.
  It will contain only tables this service owns once models are added in
  Phase 2 (vendors, resource_types, projects, milestones, activities,
  tasks, subtasks, comments, attachments, divisions,
  project_status_transitions).
- version_table is ``alembic_version_project_svc`` so our migration chain
  does NOT collide with the monolith's ``alembic_version`` or the
  user-service's ``alembic_version_user_svc`` in the same DB.
"""
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

from app.core.config import settings
from app.infrastructure.db.session import Base
# Register every model on Base.metadata so autogenerate sees them.
from app.infrastructure.db import models  # noqa: F401


config = context.config

# Override the placeholder URL in alembic.ini with the real env-driven value.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# IMPORTANT: separate version table. Every context.configure() call below
# must pass this, or Alembic will default to 'alembic_version' and clash
# with the monolith.
VERSION_TABLE = "alembic_version_project_svc"


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        version_table=VERSION_TABLE,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            version_table=VERSION_TABLE,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
