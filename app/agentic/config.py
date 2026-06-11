from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    provider: str = Field(
        default="vertex",
        validation_alias=AliasChoices("FIREGUARD_INTELLIGENCE_PROVIDER", "DEEP_REPORT_PROVIDER"),
    )
    light_model: str = Field(
        default="gemini-3.1-pro-preview",
        validation_alias=AliasChoices("FIREGUARD_INTELLIGENCE_LIGHT_MODEL", "DEEP_REPORT_LIGHT_MODEL"),
    )
    pro_model: str = Field(
        default="gemini-3.1-pro-preview",
        validation_alias=AliasChoices("FIREGUARD_INTELLIGENCE_PRO_MODEL", "DEEP_REPORT_PRO_MODEL"),
    )

    host: str = Field(
        default="127.0.0.1",
        validation_alias=AliasChoices("FIREGUARD_INTELLIGENCE_HOST", "DEEP_REPORT_HOST"),
    )
    port: int = Field(
        default=8790,
        validation_alias=AliasChoices("FIREGUARD_INTELLIGENCE_PORT", "DEEP_REPORT_PORT"),
    )
    state_dir: Path = Field(
        default=Path("data/intelligence-state"),
        validation_alias=AliasChoices("FIREGUARD_INTELLIGENCE_STATE_DIR", "DEEP_REPORT_STATE_DIR"),
    )

    http_timeout_seconds: float = Field(
        default=3600.0,
        validation_alias=AliasChoices(
            "FIREGUARD_INTELLIGENCE_HTTP_TIMEOUT_SECONDS", "DEEP_REPORT_HTTP_TIMEOUT_SECONDS"
        ),
    )
    stream_timeout_seconds: float = Field(
        default=86400.0,
        validation_alias=AliasChoices(
            "FIREGUARD_INTELLIGENCE_STREAM_TIMEOUT_SECONDS", "DEEP_REPORT_STREAM_TIMEOUT_SECONDS"
        ),
    )
    max_retries: int = Field(
        default=6,
        validation_alias=AliasChoices("FIREGUARD_INTELLIGENCE_MAX_RETRIES", "DEEP_REPORT_MAX_RETRIES"),
    )
    retry_base_seconds: float = Field(
        default=1.0,
        validation_alias=AliasChoices(
            "FIREGUARD_INTELLIGENCE_RETRY_BASE_SECONDS", "DEEP_REPORT_RETRY_BASE_SECONDS"
        ),
    )
    retry_max_seconds: float = Field(
        default=60.0,
        validation_alias=AliasChoices(
            "FIREGUARD_INTELLIGENCE_RETRY_MAX_SECONDS", "DEEP_REPORT_RETRY_MAX_SECONDS"
        ),
    )
    max_agent_turns: int = Field(
        default=1_000_000,
        validation_alias=AliasChoices(
            "FIREGUARD_INTELLIGENCE_MAX_AGENT_TURNS", "DEEP_REPORT_MAX_AGENT_TURNS"
        ),
    )
    max_completion_tokens: int = Field(
        default=32768,
        validation_alias=AliasChoices(
            "FIREGUARD_INTELLIGENCE_MAX_COMPLETION_TOKENS",
            "DEEP_REPORT_MAX_COMPLETION_TOKENS",
        ),
    )
    max_parallel_tools: int = Field(
        default=128,
        validation_alias=AliasChoices(
            "FIREGUARD_INTELLIGENCE_MAX_PARALLEL_TOOLS", "DEEP_REPORT_MAX_PARALLEL_TOOLS"
        ),
    )
    max_fleet_concurrency: int = Field(
        default=128,
        validation_alias=AliasChoices(
            "FIREGUARD_INTELLIGENCE_MAX_FLEET_CONCURRENCY",
            "DEEP_REPORT_MAX_FLEET_CONCURRENCY",
        ),
    )
    default_agent_timeout_seconds: float = Field(
        default=86400.0,
        validation_alias=AliasChoices(
            "FIREGUARD_INTELLIGENCE_DEFAULT_AGENT_TIMEOUT_SECONDS",
            "DEEP_REPORT_DEFAULT_AGENT_TIMEOUT_SECONDS",
        ),
    )
    default_tool_timeout_seconds: float = Field(
        default=86400.0,
        validation_alias=AliasChoices(
            "FIREGUARD_INTELLIGENCE_DEFAULT_TOOL_TIMEOUT_SECONDS",
            "DEEP_REPORT_DEFAULT_TOOL_TIMEOUT_SECONDS",
        ),
    )
    exa_api_key: str = Field(default="", validation_alias="EXA_API_KEY")
    exa_base_url: str = Field(default="https://api.exa.ai", validation_alias="EXA_BASE_URL")
    google_cloud_project: str = Field(default="", validation_alias="GOOGLE_CLOUD_PROJECT")
    google_cloud_location: str = Field(default="global", validation_alias="GOOGLE_CLOUD_LOCATION")
    gemini_model: str = Field(default="gemini-3.1-pro-preview", validation_alias="GEMINI_MODEL")
    fireguard_elasticsearch_url: str = Field(default="", validation_alias="ELASTICSEARCH_URL")
    fireguard_elasticsearch_api_key: str = Field(
        default="", validation_alias="ELASTICSEARCH_API_KEY"
    )
    fireguard_elasticsearch_index_prefix: str = Field(
        default="fireguard", validation_alias="ELASTICSEARCH_INDEX_PREFIX"
    )
    fireguard_data_bootstrap_enabled: bool = Field(
        default=True, validation_alias="FIREGUARD_DATA_BOOTSTRAP_ENABLED"
    )
    fireguard_data_bootstrap_max_docs_per_index: int = Field(
        default=5000, validation_alias="FIREGUARD_DATA_BOOTSTRAP_MAX_DOCS_PER_INDEX"
    )
    fireguard_data_bootstrap_page_size: int = Field(
        default=500, validation_alias="FIREGUARD_DATA_BOOTSTRAP_PAGE_SIZE"
    )
    docker_sandbox_enabled: bool = Field(default=False, validation_alias="DOCKER_SANDBOX_ENABLED")
    docker_sandbox_image: str = Field(
        default="python:3.12-slim", validation_alias="DOCKER_SANDBOX_IMAGE"
    )
    docker_sandbox_container_prefix: str = Field(
        default="fireguard-intelligence-sandbox",
        validation_alias="DOCKER_SANDBOX_CONTAINER_PREFIX",
    )
    docker_sandbox_network: str = Field(default="bridge", validation_alias="DOCKER_SANDBOX_NETWORK")
    docker_sandbox_timeout_seconds: int = Field(
        default=3600, validation_alias="DOCKER_SANDBOX_TIMEOUT_SECONDS"
    )
    docker_sandbox_idle_timeout_seconds: int = Field(
        default=900, validation_alias="DOCKER_SANDBOX_IDLE_TIMEOUT_SECONDS"
    )
    docker_sandbox_setup_timeout_seconds: int = Field(
        default=1800, validation_alias="DOCKER_SANDBOX_SETUP_TIMEOUT_SECONDS"
    )
    docker_sandbox_pool_size: int = Field(default=1, validation_alias="DOCKER_SANDBOX_POOL_SIZE")
    docker_sandbox_install_packages_on_start: bool = Field(
        default=False,
        validation_alias="DOCKER_SANDBOX_INSTALL_PACKAGES_ON_START",
    )
    docker_sandbox_pip_packages: str = Field(
        default="numpy,pandas,scipy,scikit-learn,matplotlib,networkx,requests,beautifulsoup4,lxml,pyarrow,duckdb,polars,sympy",
        validation_alias="DOCKER_SANDBOX_PIP_PACKAGES",
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    @model_validator(mode="after")
    def validate_config(self) -> AppConfig:
        if len(self.provider.strip()) == 0:
            raise ValueError("FIREGUARD_INTELLIGENCE_PROVIDER must be a non-empty string")
        if self.provider != "vertex":
            raise ValueError("FIREGUARD_INTELLIGENCE_PROVIDER must be vertex")
        if len(self.light_model.strip()) == 0:
            raise ValueError("FIREGUARD_INTELLIGENCE_LIGHT_MODEL must be a non-empty string")
        if len(self.pro_model.strip()) == 0:
            raise ValueError("FIREGUARD_INTELLIGENCE_PRO_MODEL must be a non-empty string")
        if self.max_retries < 1:
            raise ValueError("FIREGUARD_INTELLIGENCE_MAX_RETRIES must be at least 1")
        if self.max_agent_turns < 1:
            raise ValueError("FIREGUARD_INTELLIGENCE_MAX_AGENT_TURNS must be at least 1")
        if self.max_completion_tokens < 1:
            raise ValueError("FIREGUARD_INTELLIGENCE_MAX_COMPLETION_TOKENS must be at least 1")
        if self.max_parallel_tools < 1:
            raise ValueError("FIREGUARD_INTELLIGENCE_MAX_PARALLEL_TOOLS must be at least 1")
        if self.max_fleet_concurrency < 1:
            raise ValueError("FIREGUARD_INTELLIGENCE_MAX_FLEET_CONCURRENCY must be at least 1")
        if not self.exa_base_url.startswith(("http://", "https://")):
            raise ValueError("EXA_BASE_URL must start with http:// or https://")
        if len(self.fireguard_elasticsearch_url.strip()) > 0 and not self.fireguard_elasticsearch_url.startswith(
            ("http://", "https://")
        ):
            raise ValueError("ELASTICSEARCH_URL must start with http:// or https://")
        if len(self.fireguard_elasticsearch_index_prefix.strip()) == 0:
            raise ValueError("ELASTICSEARCH_INDEX_PREFIX must be a non-empty string")
        if self.fireguard_data_bootstrap_max_docs_per_index < 1:
            raise ValueError("FIREGUARD_DATA_BOOTSTRAP_MAX_DOCS_PER_INDEX must be at least 1")
        if self.fireguard_data_bootstrap_page_size < 1:
            raise ValueError("FIREGUARD_DATA_BOOTSTRAP_PAGE_SIZE must be at least 1")
        if len(self.docker_sandbox_image.strip()) == 0:
            raise ValueError("DOCKER_SANDBOX_IMAGE must be a non-empty string")
        if len(self.google_cloud_location.strip()) == 0:
            raise ValueError("GOOGLE_CLOUD_LOCATION must be set when FIREGUARD_INTELLIGENCE_PROVIDER=vertex")
        if len(self.gemini_model.strip()) == 0:
            raise ValueError("GEMINI_MODEL must be a non-empty string")
        if len(self.docker_sandbox_container_prefix.strip()) == 0:
            raise ValueError("DOCKER_SANDBOX_CONTAINER_PREFIX must be a non-empty string")
        if len(self.docker_sandbox_network.strip()) == 0:
            raise ValueError("DOCKER_SANDBOX_NETWORK must be a non-empty string")
        if self.docker_sandbox_timeout_seconds < 1:
            raise ValueError("DOCKER_SANDBOX_TIMEOUT_SECONDS must be at least 1")
        if self.docker_sandbox_idle_timeout_seconds < 1:
            raise ValueError("DOCKER_SANDBOX_IDLE_TIMEOUT_SECONDS must be at least 1")
        if self.docker_sandbox_setup_timeout_seconds < 1:
            raise ValueError("DOCKER_SANDBOX_SETUP_TIMEOUT_SECONDS must be at least 1")
        if self.docker_sandbox_pool_size < 0:
            raise ValueError("DOCKER_SANDBOX_POOL_SIZE must be at least 0")
        return self

    def ensure_state_dir(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)


def get_config() -> AppConfig:
    config = AppConfig()
    config.ensure_state_dir()
    return config
