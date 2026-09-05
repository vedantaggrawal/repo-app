"""Runtime configuration.

Everything is read from the environment (12-factor). The pod-identity fields are
populated by the Downward API in the Helm chart; they fall back to sensible
values so the app also runs bare with `uvicorn app.main:app`.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "devops-test-webserver"
    # Overridden at build time by the CI pipeline.
    app_version: str = "0.1.0"
    git_sha: str = "unknown"

    # local | dev | stg | prod — matches the GitOps environment directories.
    environment: str = "local"

    host: str = "0.0.0.0"  # noqa: S104 — binding all interfaces is required in a container.
    port: int = 8080

    log_level: str = "INFO"

    # Downward API (see the deployment's env block).
    pod_name: str = "local"
    node_name: str = "local"
    namespace: str = "default"

    # Target for /api/downstream. Defaults to calling ourselves through the
    # Service, which still produces a two-service trace in Tempo.
    downstream_url: str = "http://localhost:8080/api/info"
    downstream_timeout_seconds: float = 5.0


@lru_cache
def get_settings() -> Settings:
    """Cached so the environment is read once per process."""
    return Settings()
