"""Alembic environment. The database URL comes from the app config (DATABASE_URL), never from alembic.ini."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from app import config
from app.db import Base, _engine_kwargs

cfg = context.config
if cfg.config_file_name:
    fileConfig(cfg.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.DATABASE_URL, target_metadata=target_metadata, literal_binds=True,
                      compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(config.DATABASE_URL, **{k: v for k, v in _engine_kwargs().items() if k != "pool_size"})
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
