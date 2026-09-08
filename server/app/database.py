"""Bounded SQLAlchemy pool shared by HTTP and the durable execution worker."""

from tempfile import NamedTemporaryFile

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.settings import Settings


class Database:
    def __init__(self, settings: Settings):
        self._ssl_ca_file = None
        options = {"pool_pre_ping": True, "hide_parameters": True}
        if settings.database_url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False, "timeout": 30}
        else:
            options.update(
                pool_size=settings.database_pool_size,
                max_overflow=settings.database_max_overflow,
                pool_timeout=30,
            )
            if settings.database_ssl_ca_pem:
                # libpq needs a file; retain it for future pooled connections.
                self._ssl_ca_file = NamedTemporaryFile(  # noqa: SIM115
                    mode="w+", prefix="cornagent-db-ca-"
                )
                self._ssl_ca_file.write(settings.database_ssl_ca_pem)
                self._ssl_ca_file.flush()
                options["connect_args"] = {
                    "sslrootcert": self._ssl_ca_file.name,
                    "sslmode": "verify-full",
                }
        self.engine = create_engine(settings.database_url, **options)
        if self.engine.dialect.name == "sqlite":

            @event.listens_for(self.engine, "connect")
            def enable_foreign_keys(connection, _record):
                connection.isolation_level = None
                connection.execute("PRAGMA foreign_keys=ON")

            @event.listens_for(self.engine, "begin")
            def serialize_test_transactions(connection):
                # SQLite has no SELECT FOR UPDATE. Reserve its writer before any
                # read so concurrent Root/Child test workers cannot lose updates.
                # Production PostgreSQL uses per-Root row locks instead.
                connection.exec_driver_sql("BEGIN IMMEDIATE")

        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)

    def ping(self):
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def close(self):
        self.engine.dispose()
        if self._ssl_ca_file is not None:
            self._ssl_ca_file.close()
