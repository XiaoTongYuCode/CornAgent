from pathlib import Path

from sqlalchemy.engine import make_url

from app.database import Database
from app.settings import Settings


def test_private_ca_requires_server_verification_and_lives_until_pool_closes(monkeypatch):
    captured = {}

    class Engine:
        dialect = type("Dialect", (), {"name": "postgresql"})()

        def dispose(self):
            assert Path(captured["connect_args"]["sslrootcert"]).exists()

    def create_engine(url, **options):
        captured.update(options)
        assert make_url(url).query["sslmode"] == "disable"
        return Engine()

    monkeypatch.setattr("app.database.create_engine", create_engine)
    database = Database(
        Settings(
            _env_file=None,
            database_url="postgresql+psycopg://localhost/test?sslmode=disable",
            database_ssl_ca_pem="test CA contents",
        )
    )
    ca_file = Path(captured["connect_args"]["sslrootcert"])
    assert captured["connect_args"]["sslmode"] == "verify-full"
    assert ca_file.read_text() == "test CA contents"
    assert ca_file.stat().st_mode & 0o777 == 0o600
    database.close()
    assert not ca_file.exists()
