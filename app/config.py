from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_nested_delimiter="__")

    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8400

    renegotiation_service_base_url: str = "http://localhost:9400"
    renegotiation_service_retry_attempts: int = 2

    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_tool_events_topic: str = "tool.executed"


def get_settings() -> Settings:
    return Settings()
