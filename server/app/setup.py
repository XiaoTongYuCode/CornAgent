"""Create only the configured local database, then apply versioned migrations."""

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.settings import Settings


def main():
    settings = Settings()
    url = make_url(settings.database_url)
    if url.get_backend_name() == "postgresql":
        engine = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
        with engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": url.database}
            ).scalar()
            if not exists:
                name = engine.dialect.identifier_preparer.quote_identifier(url.database)
                connection.execute(text(f"CREATE DATABASE {name}"))
        engine.dispose()
    command.upgrade(Config("alembic.ini"), "head")
    print("CornAgent database is ready.")


if __name__ == "__main__":
    main()
