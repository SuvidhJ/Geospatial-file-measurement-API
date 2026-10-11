from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration; every field can be overridden with a GEOAPI_<NAME> env variable."""

    model_config = SettingsConfigDict(env_prefix="GEOAPI_", env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    database_url: str | None = None
    max_upload_bytes: int = 50 * 1024 * 1024
    max_uncompressed_bytes: int = 500 * 1024 * 1024
    max_archive_members: int = 200
    geodesic_warning_pct: float = 0.5
    log_level: str = "INFO"
    redis_url: str | None = None
    job_timeout_seconds: int = 600
    max_dem_cells_per_feature: int = 25_000_000

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def resolved_database_url(self) -> str:
        return self.database_url or f"sqlite:///{(self.data_dir / 'geoapi.db').as_posix()}"
