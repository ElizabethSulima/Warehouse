import os

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str) -> str:
    return os.getenv(name) or default


DATABASE_URL = _env(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/warehouse",
)
REDIS_URL = _env("REDIS_URL", "redis://localhost:6379/0")
API_HOST = _env("API_HOST", "0.0.0.0")
API_PORT = int(_env("API_PORT", "8080"))
