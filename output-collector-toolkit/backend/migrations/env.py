from alembic import context

from app.config import Settings
from app.database import create_database_engine
from app.models import Base


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is not None:
    run(connection)
else:
    engine = create_database_engine(Settings())
    with engine.connect() as connection:
        run(connection)
    engine.dispose()
