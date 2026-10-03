"""Alembic 环境复用应用配置；不把密码放进 ini 或日志。"""

from alembic import context
from sqlalchemy import Connection, create_engine

from backend.persistence.database import configuration, database_url
from backend.persistence.models import Base


def migrate(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    url = database_url(configuration())
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    existing = context.config.attributes.get("connection")
    if isinstance(existing, Connection):
        migrate(existing)
    else:
        engine = create_engine(database_url(configuration()), hide_parameters=True)
        try:
            with engine.connect() as connection:
                migrate(connection)
        finally:
            engine.dispose()
