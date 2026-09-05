"""Start the API using the shared project environment configuration."""

import uvicorn

from app.settings import Settings


def main():
    settings = Settings()
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.server_host,
        port=settings.server_port,
        reload=settings.server_reload,
        log_level=settings.server_log_level,
    )


if __name__ == "__main__":
    main()
