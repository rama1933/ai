from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"

    database_url: str
    database_url_readonly: str

    ollama_base_url: str = "http://localhost:11434"
    ollama_llm_model: str = "llama3.2:3b"
    ollama_embedding_model: str = "nomic-embed-text"
    embedding_dim: int = 768

    upload_dir: Path = Path("../storage/uploads")
    max_upload_bytes: int = 10 * 1024 * 1024

    cors_origins: list[str] = ["http://localhost:5173"]

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    sql_tool_allowed_tables: list[str] = ["documents"]
    sql_tool_timeout_ms: int = 3000

    agent_max_iterations: int = 5
    agent_temperature: float = 0.0
    agent_seed: int = 0

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
