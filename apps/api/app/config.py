from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../../.env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    demo_mode: bool = True
    demo_region: str = "bc"
    api_cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    elasticsearch_url: str | None = None
    elasticsearch_api_key: str | None = None
    elasticsearch_cloud_id: str | None = None

    fivetran_api_key: str | None = None
    fivetran_api_secret: str | None = None
    fivetran_destination_name: str = "fireguard_bigquery"
    fivetran_connection_name: str = "fireguard_ingestion"
    fivetran_connection_id: str | None = None
    fivetran_bigquery_project: str | None = None
    fivetran_bigquery_dataset: str = "fireguard_ingestion"

    nasa_firms_map_key: str | None = None
    nasa_firms_source: str = "VIIRS_SNPP_NRT"
    nasa_firms_bbox: str = "-122.2,52.0,-121.3,52.9"

    google_cloud_project: str | None = None
    google_cloud_location: str = "global"
    google_application_credentials: str | None = None
    gemini_model: str = "gemini-3.1-flash-lite-preview"
    google_genai_use_vertexai: bool = True
    gemini_assessment_enabled: bool = True
    google_maps_api_key: str | None = None

    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_from_number: str | None = None
    twilio_allowlist: str = Field(default="+15555550123,+15555550124")
    demo_resident_zone_a_phone: str | None = None

    phoenix_tracing_enabled: bool = True
    phoenix_collector_endpoint: str = "http://localhost:6006/v1/traces"
    phoenix_project_name: str = "fireguard"
    phoenix_api_key: str | None = None
    phoenix_auth_enabled: bool = False
    phoenix_status_timeout_seconds: float = 10.0
    phoenix_storage_backend: str = "local_or_external"

    action_webhook_secret: str = "dev-secret"
    shelter_webhook_url: str | None = None
    road_ops_webhook_url: str | None = None
    dispatch_webhook_url: str | None = None

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]

    @property
    def twilio_allowlist_numbers(self) -> set[str]:
        return {number.strip() for number in self.twilio_allowlist.split(",") if number.strip()}

    @property
    def firms_bbox_values(self) -> tuple[float, float, float, float]:
        west, south, east, north = self.nasa_firms_bbox.split(",")
        return float(west), float(south), float(east), float(north)


@lru_cache
def get_settings() -> Settings:
    return Settings()
