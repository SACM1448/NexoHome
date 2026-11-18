"""Entorno compartido por CLI Alembic y arranque Docker."""
from alembic import context
from nexo.config import Settings
from nexo.database import Database, metadata


def run(connection):
    context.configure(connection=connection, target_metadata=metadata,
                      transactional_ddl=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is not None:
    run(connection)
else:
    database = Database(Settings.from_env().data_dir)
    database.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with database.engine.connect().execution_options(write=True) as connection:
            run(connection)
    finally:
        database.close()
